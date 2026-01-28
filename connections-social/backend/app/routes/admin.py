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
