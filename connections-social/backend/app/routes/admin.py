"""Admin routes for profile management."""

import logging
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query

from app.config import PROFILES_DIR, UPLOADS_DIR, BASE_DIR, INSIGHTFACE_MODEL
from app.db import get_cursor
from app.jobs import job_manager

logger = logging.getLogger(__name__)
router = APIRouter()

# Global face analysis model (lazy loaded)
_face_app = None


def get_face_app():
    """Lazy load InsightFace model."""
    global _face_app
    if _face_app is None:
        import insightface
        _face_app = insightface.app.FaceAnalysis(
            name=INSIGHTFACE_MODEL,
            allowed_modules=["detection", "recognition"]
        )
        _face_app.prepare(ctx_id=0, det_size=(640, 640))
        logger.info(f"Loaded InsightFace model: {INSIGHTFACE_MODEL}")
    return _face_app


def pack_embedding(embedding: np.ndarray) -> bytes:
    """Pack float32 embedding array to bytes."""
    return struct.pack(f"{len(embedding)}f", *embedding.astype(np.float32))


def scan_profile_images(profiles_dir: Path) -> List[Tuple[str, Path]]:
    """
    Scan profiles directory and return sorted list of (person_name, image_path).

    Directory structure: profiles/<Identity>/*.jpg
    """
    results = []

    if not profiles_dir.exists():
        logger.warning(f"Profiles directory does not exist: {profiles_dir}")
        return results

    # Get sorted list of identity folders
    identity_dirs = sorted([
        d for d in profiles_dir.iterdir()
        if d.is_dir() and d.name.isascii()
    ])

    for identity_dir in identity_dirs:
        person_name = identity_dir.name
        # Get sorted list of jpg files
        images = sorted(identity_dir.glob("*.jpg"))
        for img_path in images:
            results.append((person_name, img_path))

    logger.info(f"Found {len(results)} profile images across {len(identity_dirs)} identities")
    return results


def extract_single_face(image_path: Path) -> Tuple[np.ndarray, None] | Tuple[None, str]:
    """
    Extract face embedding from image. Returns (embedding, None) on success,
    or (None, error_message) on failure.

    Enforces exactly 1 face per image.
    """
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return None, f"Failed to read image: {image_path}"

        face_app = get_face_app()
        faces = face_app.get(img)

        if len(faces) == 0:
            return None, f"No faces detected in {image_path}"

        if len(faces) > 1:
            return None, f"Multiple faces ({len(faces)}) detected in {image_path}"

        embedding = faces[0].normed_embedding
        return embedding, None

    except Exception as e:
        return None, f"Error processing {image_path}: {e}"


@router.post("/rebuild-profile-index")
def rebuild_profile_index():
    """
    Rebuild the profile index by scanning profile images and extracting embeddings.

    - Scans data/profiles/ directory
    - Runs InsightFace (buffalo_l) to enforce exactly 1 face per profile image
    - Inserts persons + person_profiles into Postgres
    - Embeddings stored as packed float32 in bytea
    - Returns deterministic summary report
    """
    logger.info(f"Starting profile index rebuild from {PROFILES_DIR}")

    # Scan for profile images
    profile_images = scan_profile_images(PROFILES_DIR)

    if not profile_images:
        raise HTTPException(
            status_code=400,
            detail=f"No profile images found in {PROFILES_DIR}"
        )

    # Track results
    persons_created = 0
    profiles_inserted = 0
    rejected_images = []
    person_ids = {}  # name -> uuid

    try:
        with get_cursor() as cur:
            # Clear existing data (rebuild = full refresh)
            # Also clear ingestion history so we can re-ingest
            cur.execute("TRUNCATE uploads, faces, processed_images CASCADE")
            cur.execute("DELETE FROM person_profiles")
            cur.execute("DELETE FROM persons")
            logger.info("Cleared existing persons, profiles, and ingestion history")

            # Process each image in deterministic order
            for person_name, image_path in profile_images:
                # Extract face embedding
                embedding, error = extract_single_face(image_path)

                if error:
                    rejected_images.append({
                        "person": person_name,
                        "image": str(image_path),
                        "reason": error
                    })
                    logger.warning(f"Rejected: {error}")
                    continue

                # Create person if not exists
                if person_name not in person_ids:
                    cur.execute(
                        "INSERT INTO persons (name) VALUES (%s) RETURNING id",
                        (person_name,)
                    )
                    person_ids[person_name] = cur.fetchone()["id"]
                    persons_created += 1

                # Insert profile with embedding
                embedding_bytes = pack_embedding(embedding)
                cur.execute(
                    """
                    INSERT INTO person_profiles (person_id, source_image, embedding)
                    VALUES (%s, %s, %s)
                    """,
                    (person_ids[person_name], str(image_path), embedding_bytes)
                )
                profiles_inserted += 1
                logger.info(f"Inserted profile: {person_name} from {image_path.name}")

        # Build summary report
        summary = {
            "status": "completed",
            "ingestion_state_cleared": True,
            "tables_cleared": ["persons", "person_profiles", "uploads", "faces", "processed_images"],
            "profiles_dir": str(PROFILES_DIR),
            "total_images_scanned": len(profile_images),
            "persons_created": persons_created,
            "profiles_inserted": profiles_inserted,
            "images_rejected": len(rejected_images),
            "rejected_details": rejected_images
        }

        logger.info(
            f"Profile index rebuild complete: "
            f"{persons_created} persons, {profiles_inserted} profiles, "
            f"{len(rejected_images)} rejected"
        )

        return summary

    except Exception as e:
        logger.error(f"Profile index rebuild failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Profile index rebuild failed: {e}"
        )


@router.post("/reset-demo")
def reset_demo():
    """
    Reset all ingestion and graph state for demo purposes.

    Clears uploads, faces, edges, edge_evidence, and processed_images.
    Keeps persons and person_profiles intact so you don't need to rebuild profiles.

    Use this when you want to re-run the demo with the same images without
    rebuilding the profile index.
    """
    logger.info("Starting demo reset - clearing ingestion and graph state")

    try:
        with get_cursor() as cur:
            # Clear graph and ingestion tables, preserving persons/profiles
            # TRUNCATE with CASCADE handles foreign key dependencies
            cur.execute("""
                TRUNCATE uploads, faces, edges, edge_evidence, processed_images
                CASCADE
            """)
            logger.info("Cleared uploads, faces, edges, edge_evidence, processed_images")

        return {
            "status": "completed",
            "cleared": ["uploads", "faces", "edges", "edge_evidence", "processed_images"],
            "preserved": ["persons", "person_profiles"]
        }

    except Exception as e:
        logger.error(f"Demo reset failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Demo reset failed: {e}"
        )


@router.post("/clear-processed")
def clear_processed():
    """
    Clear only the processed_images table.

    Use this when you want to re-run ingest without resetting uploads/faces/edges.
    Useful for testing different processing logic on the same images.
    """
    logger.info("Clearing processed_images table")

    try:
        with get_cursor() as cur:
            cur.execute("TRUNCATE processed_images")
            cur.execute("SELECT COUNT(*) as count FROM processed_images")
            count = cur.fetchone()["count"]

        return {
            "status": "completed",
            "cleared": ["processed_images"],
            "remaining_count": count
        }

    except Exception as e:
        logger.error(f"Clear processed failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Clear processed failed: {e}"
        )


@router.get("/storage-info")
def storage_info():
    """
    Get information about storage directories and file counts.

    Returns paths and counts for:
    - profiles_dir: Source of truth identities
    - uploads_dir: Active ingestion directory (UI uploads + batch)
    - group_photos_dir: Optional staging for batch datasets
    """
    def count_images(path: Path) -> int:
        """Count image files in a directory (non-recursive)."""
        if not path.exists():
            return 0
        return len([
            f for f in path.iterdir()
            if f.is_file() and f.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp'}
        ])

    def count_subdirs(path: Path) -> int:
        """Count subdirectories (for profiles)."""
        if not path.exists():
            return 0
        return len([d for d in path.iterdir() if d.is_dir()])

    group_photos_dir = BASE_DIR / "data" / "group_photos"

    return {
        "profiles_dir": str(PROFILES_DIR),
        "profiles_count": count_subdirs(PROFILES_DIR),
        "uploads_dir": str(UPLOADS_DIR),
        "uploads_count": count_images(UPLOADS_DIR),
        "group_photos_dir": str(group_photos_dir),
        "group_photos_count": count_images(group_photos_dir),
        "base_dir": str(BASE_DIR)
    }


# ============================================================================
# Replay / Reprocessing Endpoint
# ============================================================================

@router.post("/replay")
def replay_processing(
    from_date: Optional[str] = Query(
        None,
        description="Start date for replay (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"
    ),
    to_date: Optional[str] = Query(
        None,
        description="End date for replay (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"
    ),
    model_version: Optional[str] = Query(
        None,
        description="Only replay images processed by this model version"
    ),
    async_mode: bool = Query(
        False,
        description="If True, run replay in background and return job ID"
    ),
):
    """Replay/reprocess historical images with current model.

    This endpoint allows reprocessing previously ingested images, which is useful when:
    - ML model has been updated and you want to regenerate edges with new version
    - You want to test different matching thresholds
    - Data lineage tracking was added and you want to backfill

    The replay process:
    1. Finds images processed within the specified date range
    2. Clears their entries from processed_images table
    3. Clears associated graph data (edges, edge_evidence)
    4. Re-runs the ingestion pipeline with current model

    Args:
        from_date: Optional start date (default: no lower bound)
        to_date: Optional end date (default: no upper bound)
        model_version: Optional filter by original model version
        async_mode: If True, returns job ID for polling; if False, blocks until complete

    Returns:
        Replay statistics or job ID (if async_mode=True)

    Example:
        POST /admin/replay?from_date=2024-01-01&to_date=2024-01-31
        POST /admin/replay?model_version=buffalo_l&async_mode=true
    """
    logger.info(f"Replay requested: from={from_date}, to={to_date}, model={model_version}")

    # Parse dates if provided
    parsed_from = None
    parsed_to = None

    if from_date:
        try:
            if 'T' in from_date:
                parsed_from = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
            else:
                parsed_from = datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid from_date format: {from_date}. Use YYYY-MM-DD or ISO format."
            )

    if to_date:
        try:
            if 'T' in to_date:
                parsed_to = datetime.fromisoformat(to_date.replace('Z', '+00:00'))
            else:
                parsed_to = datetime.strptime(to_date, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid to_date format: {to_date}. Use YYYY-MM-DD or ISO format."
            )

    if async_mode:
        # Create background job
        job = job_manager.create_job(
            job_type="replay",
            metadata={
                "from_date": from_date,
                "to_date": to_date,
                "model_version": model_version,
                "current_model": INSIGHTFACE_MODEL,
            }
        )

        job_manager.run_async(
            job.id,
            lambda jid, jm: _execute_replay(
                jid, jm, parsed_from, parsed_to, model_version
            )
        )

        return {
            "job_id": job.id,
            "status": "pending",
            "poll_url": f"/jobs/{job.id}",
            "message": "Replay job started in background"
        }
    else:
        # Execute synchronously
        return _execute_replay_sync(parsed_from, parsed_to, model_version)


def _execute_replay_sync(
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    model_version: Optional[str]
) -> dict:
    """Execute replay synchronously and return results."""
    from app.routes.ingest import (
        ensure_tables_exist,
        load_profile_embeddings,
        process_single_image,
        is_already_processed,
        MODEL_VERSION,
    )

    try:
        with get_cursor() as cur:
            ensure_tables_exist(cur)

            # Find images to replay based on criteria
            query = """
                SELECT DISTINCT pi.filename, pi.processed_at
                FROM processed_images pi
                WHERE 1=1
            """
            params = []

            if from_date:
                query += " AND pi.processed_at >= %s"
                params.append(from_date)

            if to_date:
                query += " AND pi.processed_at <= %s"
                params.append(to_date)

            # If model_version filter specified, join with edge_evidence
            if model_version:
                query = """
                    SELECT DISTINCT pi.filename, pi.processed_at
                    FROM processed_images pi
                    JOIN uploads u ON u.image_path = pi.filename
                    JOIN edge_evidence ee ON ee.upload_id = u.id
                    WHERE ee.model_version = %s
                """
                params = [model_version]
                if from_date:
                    query += " AND pi.processed_at >= %s"
                    params.append(from_date)
                if to_date:
                    query += " AND pi.processed_at <= %s"
                    params.append(to_date)

            query += " ORDER BY pi.processed_at"

            cur.execute(query, params)
            images_to_replay = cur.fetchall()

            if not images_to_replay:
                return {
                    "status": "completed",
                    "message": "No images found matching criteria",
                    "images_found": 0,
                    "images_replayed": 0,
                }

            # Clear processed status for these images
            filenames = [row['filename'] for row in images_to_replay]
            cur.execute(
                "DELETE FROM processed_images WHERE filename = ANY(%s)",
                (filenames,)
            )
            logger.info(f"Cleared {len(filenames)} images from processed_images")

            # Load profiles and reprocess
            profiles = load_profile_embeddings(cur)

            replayed = 0
            failed = 0
            results = []

            for row in images_to_replay:
                filename = row['filename']
                image_path = UPLOADS_DIR / filename

                if not image_path.exists():
                    results.append({
                        'filename': filename,
                        'status': 'skipped',
                        'reason': 'file_not_found'
                    })
                    continue

                try:
                    stats = process_single_image(cur, image_path, profiles)
                    replayed += 1
                    results.append({
                        'filename': filename,
                        'status': 'success',
                        'new_model': MODEL_VERSION,
                        **stats
                    })
                except Exception as e:
                    failed += 1
                    results.append({
                        'filename': filename,
                        'status': 'failed',
                        'error': str(e)
                    })

            return {
                "status": "completed",
                "images_found": len(images_to_replay),
                "images_replayed": replayed,
                "images_failed": failed,
                "new_model_version": MODEL_VERSION,
                "filters": {
                    "from_date": from_date.isoformat() if from_date else None,
                    "to_date": to_date.isoformat() if to_date else None,
                    "original_model": model_version,
                },
                "results": results
            }

    except Exception as e:
        logger.error(f"Replay failed: {e}")
        raise HTTPException(status_code=500, detail=f"Replay failed: {e}")


def _execute_replay(
    job_id: str,
    jm,
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    model_version: Optional[str]
):
    """Execute replay as background job."""
    from app.routes.ingest import (
        ensure_tables_exist,
        load_profile_embeddings,
        process_single_image,
        MODEL_VERSION,
    )

    try:
        with get_cursor() as cur:
            ensure_tables_exist(cur)

            # Find images to replay
            query = """
                SELECT DISTINCT pi.filename, pi.processed_at
                FROM processed_images pi
                WHERE 1=1
            """
            params = []

            if from_date:
                query += " AND pi.processed_at >= %s"
                params.append(from_date)

            if to_date:
                query += " AND pi.processed_at <= %s"
                params.append(to_date)

            if model_version:
                query = """
                    SELECT DISTINCT pi.filename, pi.processed_at
                    FROM processed_images pi
                    JOIN uploads u ON u.image_path = pi.filename
                    JOIN edge_evidence ee ON ee.upload_id = u.id
                    WHERE ee.model_version = %s
                """
                params = [model_version]
                if from_date:
                    query += " AND pi.processed_at >= %s"
                    params.append(from_date)
                if to_date:
                    query += " AND pi.processed_at <= %s"
                    params.append(to_date)

            query += " ORDER BY pi.processed_at"

            cur.execute(query, params)
            images_to_replay = cur.fetchall()

            total = len(images_to_replay)

            if total == 0:
                jm.complete_job(
                    job_id,
                    success=True,
                    data={
                        "message": "No images found matching criteria",
                        "images_found": 0,
                        "images_replayed": 0,
                    }
                )
                return

            # Clear processed status
            filenames = [row['filename'] for row in images_to_replay]
            cur.execute(
                "DELETE FROM processed_images WHERE filename = ANY(%s)",
                (filenames,)
            )

            # Load profiles
            profiles = load_profile_embeddings(cur)

            replayed = 0
            failed = 0
            results = []

            for idx, row in enumerate(images_to_replay):
                filename = row['filename']

                jm.update_job_progress(
                    job_id,
                    current=idx + 1,
                    total=total,
                    current_item=filename,
                    items_succeeded=replayed,
                    items_failed=failed
                )

                image_path = UPLOADS_DIR / filename

                if not image_path.exists():
                    results.append({
                        'filename': filename,
                        'status': 'skipped',
                        'reason': 'file_not_found'
                    })
                    continue

                try:
                    stats = process_single_image(cur, image_path, profiles)
                    replayed += 1
                    results.append({
                        'filename': filename,
                        'status': 'success',
                        'new_model': MODEL_VERSION,
                        **stats
                    })
                except Exception as e:
                    failed += 1
                    results.append({
                        'filename': filename,
                        'status': 'failed',
                        'error': str(e)
                    })

            jm.complete_job(
                job_id,
                success=True,
                data={
                    "images_found": total,
                    "images_replayed": replayed,
                    "images_failed": failed,
                    "new_model_version": MODEL_VERSION,
                },
                items=results
            )

    except Exception as e:
        logger.error(f"Replay job {job_id} failed: {e}")
        jm.complete_job(job_id, success=False, error=str(e))


# ============================================================================
# Benchmark: brute-force Python vs pgvector ANN
# ============================================================================

@router.get("/benchmark")
def benchmark_matching(top_k: int = 5, iterations: int = 10):
    """Compare brute-force cosine similarity vs pgvector ANN for face matching.

    Runs both methods against the live profile corpus with a random query
    embedding and returns measured latency for each approach.

    This endpoint exists to make concrete the O(n) vs O(log n) argument that
    motivates a pgvector migration at scale.  Run it before and after running
    the pgvector migration to see the difference with real data.

    Args:
        top_k:      Number of nearest neighbors to retrieve (default 5).
        iterations: Number of timed repetitions for statistical stability (default 10).

    Returns:
        Timing comparison, profile count, and scaling projections.

    Tesla relevance:
        In a vehicle telemetry pipeline, the equivalent tradeoff is between
        scanning every historical embedding to find similar events (O(n)) vs
        using a pre-built ANN index to find approximate matches in O(log n).
        At tens of millions of events, the index is not optional.
    """
    import time as time_lib

    from app.routes.ingest import load_profile_embeddings, cosine_similarity, unpack_embedding

    try:
        with get_cursor() as cur:
            # ── Load all profile embeddings (current production path) ──────────
            profiles = load_profile_embeddings(cur)
            profile_count = len(profiles)

            if profile_count == 0:
                return {
                    "error": "No profiles in database. Run /admin/rebuild-profile-index first.",
                    "profile_count": 0,
                }

            # ── Generate a random normalized query embedding ───────────────────
            rng = np.random.default_rng(seed=42)
            query_raw = rng.standard_normal(512).astype(np.float32)
            query_vec = query_raw / np.linalg.norm(query_raw)  # unit vector

            # ── Method 1: Brute-force Python loop (current path) ──────────────
            brute_times = []
            brute_result = None
            for _ in range(iterations):
                t0 = time_lib.perf_counter()
                scores = [
                    (name, cosine_similarity(query_vec, emb))
                    for _, name, emb in profiles
                ]
                scores.sort(key=lambda x: x[1], reverse=True)
                top = scores[:top_k]
                brute_times.append((time_lib.perf_counter() - t0) * 1000)
            brute_result = top

            brute_avg_ms = round(sum(brute_times) / len(brute_times), 3)
            brute_min_ms = round(min(brute_times), 3)
            brute_max_ms = round(max(brute_times), 3)

            # ── Method 2: pgvector ANN (optional — requires migration) ─────────
            pgvector_available = False
            pgvector_avg_ms = None
            pgvector_min_ms = None
            pgvector_max_ms = None
            pgvector_result = None
            pgvector_note = "Run infra/docker/migrate_pgvector.sql + scripts/migrate_embeddings.py to enable."

            try:
                # Check extension + column
                cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                has_ext = cur.fetchone() is not None
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM person_profiles WHERE embedding_vec IS NOT NULL"
                )
                vec_count = cur.fetchone()["cnt"]

                if has_ext and vec_count > 0:
                    pgvector_available = True
                    # Format query as pgvector literal
                    vec_literal = "[" + ",".join(f"{v:.8f}" for v in query_vec.tolist()) + "]"

                    pg_times = []
                    for _ in range(iterations):
                        t0 = time_lib.perf_counter()
                        cur.execute(
                            """
                            SELECT p.name,
                                   1 - (pp.embedding_vec <=> %s::vector) AS similarity
                            FROM person_profiles pp
                            JOIN persons p ON pp.person_id = p.id
                            WHERE pp.embedding_vec IS NOT NULL
                            ORDER BY pp.embedding_vec <=> %s::vector
                            LIMIT %s
                            """,
                            (vec_literal, vec_literal, top_k)
                        )
                        rows = cur.fetchall()
                        pg_times.append((time_lib.perf_counter() - t0) * 1000)
                    pgvector_result = [{"name": r["name"], "score": round(r["similarity"], 4)} for r in rows]
                    pgvector_avg_ms = round(sum(pg_times) / len(pg_times), 3)
                    pgvector_min_ms = round(min(pg_times), 3)
                    pgvector_max_ms = round(max(pg_times), 3)
                    pgvector_note = f"IVFFlat index active ({vec_count} vectors indexed)."
                elif has_ext and vec_count == 0:
                    pgvector_note = "pgvector extension installed but embedding_vec not populated. Run scripts/migrate_embeddings.py."
            except Exception as pg_exc:
                pgvector_note = f"pgvector unavailable: {pg_exc}"

            # ── Scaling projections ────────────────────────────────────────────
            # Brute-force scales linearly: at 10× profiles, expect 10× latency.
            # pgvector IVFFlat scales sub-linearly: O(sqrt(n) * probes).
            bytes_per_embedding = 512 * 4  # 512 float32
            mem_mb_current = round(profile_count * bytes_per_embedding / 1e6, 3)
            mem_mb_at_10k = round(10_000 * bytes_per_embedding / 1e6, 1)
            mem_mb_at_100k = round(100_000 * bytes_per_embedding / 1e6, 1)

            projected_brute_10k_ms = round(brute_avg_ms * (10_000 / max(profile_count, 1)), 1)
            projected_brute_100k_ms = round(brute_avg_ms * (100_000 / max(profile_count, 1)), 1)

            return {
                "profile_count": profile_count,
                "query": {
                    "embedding_dim": 512,
                    "top_k": top_k,
                    "iterations": iterations,
                    "note": "Random unit vector (seed=42) — representative of a real query embedding shape",
                },
                "brute_force": {
                    "description": "Current production path: load all embeddings into Python, O(n) cosine loop",
                    "avg_ms": brute_avg_ms,
                    "min_ms": brute_min_ms,
                    "max_ms": brute_max_ms,
                    "top_matches": [{"name": n, "score": round(s, 4)} for n, s in brute_result],
                    "memory_loaded_mb": mem_mb_current,
                },
                "pgvector_ann": {
                    "description": "pgvector IVFFlat ANN: O(sqrt(n)) approx search inside PostgreSQL",
                    "available": pgvector_available,
                    "avg_ms": pgvector_avg_ms,
                    "min_ms": pgvector_min_ms,
                    "max_ms": pgvector_max_ms,
                    "top_matches": pgvector_result,
                    "note": pgvector_note,
                },
                "scaling_analysis": {
                    "current_profile_count": profile_count,
                    "current_memory_mb": mem_mb_current,
                    "brute_force_linear_projection": {
                        "at_10k_profiles_ms": projected_brute_10k_ms,
                        "at_100k_profiles_ms": projected_brute_100k_ms,
                        "at_10k_memory_mb": mem_mb_at_10k,
                        "at_100k_memory_mb": mem_mb_at_100k,
                    },
                    "migration_trigger": (
                        "Migrate to pgvector IVFFlat when profile_count > 10,000 "
                        "OR brute_force avg_ms > 20ms (degrades ingest p99 latency)."
                    ),
                    "pgvector_index_type": "IVFFlat (lists=100) — see migrate_pgvector.sql for HNSW alternative",
                },
            }

    except Exception as e:
        logger.error(f"Benchmark failed: {e}")
        raise HTTPException(status_code=500, detail=f"Benchmark failed: {e}")


# ============================================================================
# Operational pipeline report
# ============================================================================

@router.get("/report")
def pipeline_report():
    """Operational summary report for the ingestion pipeline.

    Returns aggregate metrics across all processed events: throughput,
    match rate, error rate, dead-letter queue depth, cache performance,
    and pool utilization.  Designed to give an at-a-glance view of
    pipeline health suitable for an operations review or incident triage.

    Tesla relevance: equivalent to a daily telemetry health digest —
    how many frames were processed, what fraction were successfully
    classified, how many went to the dead-letter queue, what is the
    p95 processing latency.
    """
    from app.db import get_pool_status
    from app.cache import get_cached

    try:
        with get_cursor() as cur:
            # ── Ingestion throughput ──────────────────────────────────────────
            cur.execute("SELECT COUNT(*) AS cnt FROM processed_images")
            total_processed = cur.fetchone()["cnt"]

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM processed_images WHERE processed_at >= NOW() - INTERVAL '24 hours'"
            )
            processed_24h = cur.fetchone()["cnt"]

            # ── Graph stats ───────────────────────────────────────────────────
            cur.execute("SELECT COUNT(*) AS cnt FROM persons WHERE name NOT LIKE 'UNKNOWN_%'")
            known_persons = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) AS cnt FROM persons WHERE name LIKE 'UNKNOWN_%'")
            unknown_persons = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) AS cnt FROM edges")
            total_edges = cur.fetchone()["cnt"]

            cur.execute("SELECT SUM(weight) AS total FROM edges")
            total_cooccurrences = cur.fetchone()["total"] or 0

            # ── Match rate (from faces table) ─────────────────────────────────
            cur.execute("SELECT COUNT(*) AS cnt FROM faces")
            total_faces = cur.fetchone()["cnt"]

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM faces WHERE matched_person_id IS NOT NULL AND score >= 0.45"
            )
            matched_faces = cur.fetchone()["cnt"]

            match_rate = round(matched_faces / total_faces, 4) if total_faces > 0 else 0.0

            # ── Dead-letter queue ─────────────────────────────────────────────
            dead_letter_exists = False
            dead_letter_stats: dict = {}
            try:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM failed_ingests WHERE NOT resolved"
                )
                unresolved = cur.fetchone()["cnt"]

                cur.execute("SELECT COUNT(*) AS cnt FROM failed_ingests")
                total_failed = cur.fetchone()["cnt"]

                cur.execute(
                    """
                    SELECT error_stage, COUNT(*) AS cnt
                    FROM failed_ingests WHERE NOT resolved
                    GROUP BY error_stage ORDER BY cnt DESC
                    """
                )
                by_stage = {r["error_stage"]: r["cnt"] for r in cur.fetchall()}

                dead_letter_stats = {
                    "total_failed": total_failed,
                    "unresolved": unresolved,
                    "by_stage": by_stage,
                }
                dead_letter_exists = True
            except Exception:
                dead_letter_stats = {
                    "note": "Run infra/docker/migrate_failed_ingests.sql to enable dead-letter tracking"
                }

            # ── Model version distribution ────────────────────────────────────
            cur.execute(
                """
                SELECT model_version, COUNT(*) AS cnt
                FROM edge_evidence
                GROUP BY model_version ORDER BY cnt DESC
                LIMIT 5
                """
            )
            model_dist = {r["model_version"]: r["cnt"] for r in cur.fetchall()}

            # ── Pool status ───────────────────────────────────────────────────
            pool = get_pool_status()

        return {
            "report_generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "ingestion": {
                "total_images_processed": total_processed,
                "processed_last_24h": processed_24h,
                "total_faces_detected": total_faces,
                "total_faces_matched": matched_faces,
                "match_rate": match_rate,
                "total_edges": total_edges,
                "total_cooccurrences": int(total_cooccurrences),
            },
            "identity_corpus": {
                "known_persons": known_persons,
                "unknown_persons": unknown_persons,
                "total_persons": known_persons + unknown_persons,
            },
            "model_versions": model_dist,
            "dead_letter_queue": dead_letter_stats,
            "infrastructure": {
                "db_pool": pool,
            },
        }

    except Exception as e:
        logger.error(f"Report failed: {e}")
        raise HTTPException(status_code=500, detail=f"Report failed: {e}")


# ============================================================================
# Dead-letter retry
# ============================================================================

@router.post("/retry-failed")
def retry_failed_ingests(limit: int = 50):
    """Retry items in the dead-letter queue (failed_ingests).

    Re-runs the ingestion pipeline for every unresolved failed ingest whose
    retry_count < max_retries.  On success the record is marked resolved;
    on failure retry_count is incremented and last_attempted is updated.

    Args:
        limit: Max number of failed items to attempt in a single call (default 50).

    Returns:
        Summary of retried, resolved, and still-failing items.

    Tesla analog: a telemetry quarantine worker that periodically re-tries
    frames that failed cloud-side processing — with a bounded retry count
    to avoid infinite loops on permanently corrupt frames.
    """
    from app.routes.ingest import (
        ensure_tables_exist,
        load_profile_embeddings,
        process_single_image,
        MODEL_VERSION,
    )

    retried = 0
    resolved = 0
    still_failing = 0
    exhausted = 0
    results = []

    try:
        with get_cursor() as cur:
            ensure_tables_exist(cur)

            # Fetch candidates: unresolved, retries remaining
            cur.execute(
                """
                SELECT id, filename, error_stage, retry_count, max_retries
                FROM failed_ingests
                WHERE NOT resolved AND retry_count < max_retries
                ORDER BY last_attempted ASC
                LIMIT %s
                """,
                (limit,),
            )
            candidates = cur.fetchall()

            if not candidates:
                return {
                    "status": "ok",
                    "message": "No retryable failed ingests found",
                    "retried": 0,
                    "resolved": 0,
                    "still_failing": 0,
                }

            profiles = load_profile_embeddings(cur)

            for row in candidates:
                fail_id = str(row["id"])
                filename = row["filename"]
                retried += 1

                image_path = UPLOADS_DIR / filename

                if not image_path.exists():
                    # File is gone — mark exhausted rather than retry forever
                    cur.execute(
                        """
                        UPDATE failed_ingests
                        SET retry_count = max_retries,
                            error_message = 'File not found during retry',
                            last_attempted = NOW()
                        WHERE id = %s
                        """,
                        (fail_id,),
                    )
                    exhausted += 1
                    results.append({"filename": filename, "status": "exhausted", "reason": "file_not_found"})
                    continue

                # Delete from processed_images so process_single_image can run
                cur.execute("DELETE FROM processed_images WHERE filename = %s", (filename,))

                try:
                    stats = process_single_image(cur, image_path, profiles)
                    # Mark resolved
                    cur.execute(
                        """
                        UPDATE failed_ingests
                        SET resolved = TRUE,
                            resolved_at = NOW(),
                            retry_count = retry_count + 1,
                            last_attempted = NOW()
                        WHERE id = %s
                        """,
                        (fail_id,),
                    )
                    resolved += 1
                    results.append({"filename": filename, "status": "resolved", **stats})

                except Exception as e:
                    cur.execute(
                        """
                        UPDATE failed_ingests
                        SET retry_count = retry_count + 1,
                            error_message = %s,
                            last_attempted = NOW()
                        WHERE id = %s
                        """,
                        (str(e)[:2000], fail_id),
                    )
                    still_failing += 1
                    results.append({"filename": filename, "status": "failed_again", "error": str(e)})

        return {
            "status": "completed",
            "retried": retried,
            "resolved": resolved,
            "still_failing": still_failing,
            "exhausted": exhausted,
            "results": results,
        }

    except Exception as e:
        logger.error(f"retry-failed failed: {e}")
        raise HTTPException(status_code=500, detail=f"retry-failed failed: {e}")
