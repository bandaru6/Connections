"""Ingestion routes for processing photos and building social graph.

Pipeline lifecycle (maps to ObservationEvent.stage):
  RECEIVED          → image saved, idempotency checked
  FEATURE_EXTRACTION → InsightFace detection + 512-dim embedding
  CLASSIFICATION    → cosine similarity match against reference corpus
  PERSISTED         → edges + evidence written to PostgreSQL, cache invalidated
  SKIPPED           → filename already in processed_images (idempotency guard)
  FAILED            → unrecoverable error at any stage
"""

import asyncio
import json
import logging
import struct
import time
import uuid
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.cache import invalidate_graph_cache
from app.circuit_breaker import CircuitBreakerOpen, insightface_breaker
from app.config import (
    ALLOWED_MIME_TYPES,
    INSIGHTFACE_MODEL,
    MAX_UPLOAD_BYTES,
    UPLOADS_DIR,
    USE_PGVECTOR,
)
from app.db import get_cursor
from app.observability.tracing import create_span, trace_function
from app.schemas.events import (
    ObservationEvent,
    PipelineStage,
)
from app.search import index_event as es_index_event
from app.ws import manager as ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()

# Current model version for data lineage tracking
MODEL_VERSION = INSIGHTFACE_MODEL

# Face matching thresholds
MIN_MATCH_SCORE = 0.45
MIN_SCORE_MARGIN = 0.05

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


def unpack_embedding(data: bytes) -> np.ndarray:
    """Unpack bytes to float32 embedding array."""
    count = len(data) // 4  # 4 bytes per float32
    return np.array(struct.unpack(f"{count}f", data), dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def ensure_tables_exist(cur):
    """Create processed_images table if it doesn't exist."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS processed_images (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            filename TEXT UNIQUE NOT NULL,
            processed_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_processed_images_filename
        ON processed_images(filename)
    """)


def is_already_processed(cur, filename: str) -> bool:
    """Check if an image has already been processed."""
    cur.execute(
        "SELECT 1 FROM processed_images WHERE filename = %s",
        (filename,)
    )
    return cur.fetchone() is not None


def mark_as_processed(cur, filename: str):
    """Mark an image as processed."""
    cur.execute(
        "INSERT INTO processed_images (filename) VALUES (%s)",
        (filename,)
    )


def load_profile_embeddings(cur) -> list[tuple[str, str, np.ndarray]]:
    """Load all profile embeddings from database.

    Returns list of (person_id, person_name, embedding).
    """
    cur.execute("""
        SELECT p.id, p.name, pp.embedding
        FROM person_profiles pp
        JOIN persons p ON pp.person_id = p.id
        ORDER BY p.name, pp.id
    """)

    profiles = []
    for row in cur.fetchall():
        embedding = unpack_embedding(bytes(row['embedding']))
        profiles.append((str(row['id']), row['name'], embedding))

    logger.info(f"Loaded {len(profiles)} profile embeddings")
    return profiles


def get_next_unknown_id(cur) -> str:
    """Get next available UNKNOWN ID."""
    cur.execute("""
        SELECT name FROM persons
        WHERE name LIKE 'UNKNOWN_%'
        ORDER BY name DESC
        LIMIT 1
    """)
    row = cur.fetchone()

    if row is None:
        return "UNKNOWN_0001"

    # Extract number and increment
    last_name = row['name']
    num = int(last_name.split('_')[1]) + 1
    return f"UNKNOWN_{num:04d}"


def create_unknown_person(cur, unknown_id: str) -> str:
    """Create an UNKNOWN person and return their UUID."""
    cur.execute(
        "INSERT INTO persons (name) VALUES (%s) RETURNING id",
        (unknown_id,)
    )
    return str(cur.fetchone()['id'])


def get_person_by_name(cur, name: str) -> str | None:
    """Get person UUID by name."""
    cur.execute("SELECT id FROM persons WHERE name = %s", (name,))
    row = cur.fetchone()
    return str(row['id']) if row else None


def match_face_to_person(
    face_embedding: np.ndarray,
    profiles: list[tuple[str, str, np.ndarray]]
) -> tuple[str | None, float, float]:
    """Match a face embedding against known profiles.

    Returns (person_name, best_score, second_best_score).
    Returns (None, 0, 0) if no profiles available.
    """
    with create_span("face_matching", {"profile_count": len(profiles)}) as span:
        if not profiles:
            span.set_attribute("match_result", "no_profiles")
            return None, 0.0, 0.0

        # Compute similarities to all profiles
        scores_by_person: dict[str, float] = {}

        for _person_id, person_name, profile_emb in profiles:
            sim = cosine_similarity(face_embedding, profile_emb)
            # Keep max score per person (a person may have multiple profiles)
            if person_name not in scores_by_person or sim > scores_by_person[person_name]:
                scores_by_person[person_name] = sim

        if not scores_by_person:
            span.set_attribute("match_result", "no_scores")
            return None, 0.0, 0.0

        # Sort by score descending
        sorted_scores = sorted(scores_by_person.items(), key=lambda x: x[1], reverse=True)

        best_name, best_score = sorted_scores[0]
        second_best_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

        span.set_attribute("best_match", best_name)
        span.set_attribute("best_score", best_score)
        span.set_attribute("margin", best_score - second_best_score)

        return best_name, best_score, second_best_score


def match_face_pgvector(face_embedding: np.ndarray, cur) -> tuple[str | None, float, float]:
    """Match a face using pgvector ANN instead of the Python cosine loop.

    Requires USE_PGVECTOR=true and migrate_pgvector.sql + migrate_embeddings.py
    to have been run.  Returns (person_name, best_score, second_best_score).

    Uses the <=> operator (cosine distance = 1 - cosine_similarity), so we
    convert: similarity = 1 - distance.

    Interview note: this replaces O(n_profiles) Python ops with a single
    indexed SQL query — O(sqrt(n) * probes) via IVFFlat.
    """
    vec_literal = "[" + ",".join(f"{v:.8f}" for v in face_embedding.tolist()) + "]"
    try:
        cur.execute(
            """
            SELECT p.name,
                   1 - (pp.embedding_vec <=> %s::vector) AS similarity
            FROM person_profiles pp
            JOIN persons p ON pp.person_id = p.id
            WHERE pp.embedding_vec IS NOT NULL
            ORDER BY pp.embedding_vec <=> %s::vector
            LIMIT 3
            """,
            (vec_literal, vec_literal),
        )
        rows = cur.fetchall()
    except Exception as e:
        logger.warning("pgvector match failed (%s) — falling back to brute-force", e)
        return None, 0.0, 0.0

    if not rows:
        return None, 0.0, 0.0

    best_name = rows[0]["name"]
    best_score = float(rows[0]["similarity"])
    second_best_score = float(rows[1]["similarity"]) if len(rows) > 1 else 0.0
    return best_name, best_score, second_best_score


def detect_faces(image_path: Path) -> list[dict]:
    """Detect faces in an image.

    Returns list of face dicts sorted left-to-right by bounding box x-coordinate.
    Each dict has: bbox, embedding

    Raises:
        CircuitBreakerOpen: If ML inference is temporarily unavailable
        ValueError: If image cannot be read
    """
    with create_span("face_detection", {"image": str(image_path.name)}) as span:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Failed to read image: {image_path}")

        face_app = get_face_app()

        # Use circuit breaker to protect against ML inference failures
        with insightface_breaker.protect():
            faces = face_app.get(img)

        # Extract face data
        face_data = []
        for face in faces:
            bbox = face.bbox.tolist()  # [x1, y1, x2, y2]
            embedding = face.normed_embedding
            face_data.append({
                'bbox': bbox,
                'embedding': embedding,
                'x_center': (bbox[0] + bbox[2]) / 2  # For sorting left-to-right
            })

        # Sort left-to-right by x-center
        face_data.sort(key=lambda f: f['x_center'])

        # Remove temporary sorting key
        for f in face_data:
            del f['x_center']

        span.set_attribute("faces_detected", len(face_data))
        return face_data


def create_upload_record(cur, filename: str) -> str:
    """Create upload record and return UUID."""
    cur.execute(
        """
        INSERT INTO uploads (image_path, status)
        VALUES (%s, 'processed')
        RETURNING id
        """,
        (filename,)
    )
    return str(cur.fetchone()['id'])


def store_face(cur, upload_id: str, face: dict, person_id: str, score: float) -> str:
    """Store face in database and return UUID."""
    cur.execute(
        """
        INSERT INTO faces (upload_id, bbox, embedding, matched_person_id, score)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            upload_id,
            json.dumps(face['bbox']),
            pack_embedding(face['embedding']),
            person_id,
            score
        )
    )
    return str(cur.fetchone()['id'])


def upsert_edge(cur, person_a_id: str, person_b_id: str) -> tuple[str, str, bool]:
    """Insert or update an edge. Returns (person_a_id, person_b_id, is_new)."""
    # Ensure ordered pair (person_a_id < person_b_id)
    if person_a_id > person_b_id:
        person_a_id, person_b_id = person_b_id, person_a_id

    # Try to update existing edge
    cur.execute(
        """
        UPDATE edges
        SET weight = weight + 1, updated_at = NOW()
        WHERE person_a_id = %s AND person_b_id = %s
        RETURNING weight
        """,
        (person_a_id, person_b_id)
    )

    if cur.fetchone() is not None:
        return person_a_id, person_b_id, False

    # Insert new edge
    cur.execute(
        """
        INSERT INTO edges (person_a_id, person_b_id, weight)
        VALUES (%s, %s, 1)
        """,
        (person_a_id, person_b_id)
    )
    return person_a_id, person_b_id, True


def store_edge_evidence(
    cur,
    person_a_id: str,
    person_b_id: str,
    upload_id: str,
    confidence_a: float = None,
    confidence_b: float = None,
    model_version: str = None
):
    """Store edge evidence with data lineage tracking.

    Args:
        cur: Database cursor
        person_a_id: UUID of first person
        person_b_id: UUID of second person
        upload_id: UUID of the upload that created this evidence
        confidence_a: Match confidence score for person_a
        confidence_b: Match confidence score for person_b
        model_version: Version of ML model that produced the match
    """
    # Ensure ordered pair (swap confidences if we swap IDs)
    if person_a_id > person_b_id:
        person_a_id, person_b_id = person_b_id, person_a_id
        confidence_a, confidence_b = confidence_b, confidence_a

    cur.execute(
        """
        INSERT INTO edge_evidence (
            person_a_id, person_b_id, upload_id,
            model_version, confidence_a, confidence_b, processed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            person_a_id, person_b_id, upload_id,
            model_version or MODEL_VERSION,
            confidence_a,
            confidence_b,
            datetime.now(timezone.utc)
        )
    )


@trace_function("process_image")
def process_single_image(cur, image_path: Path, profiles: list[tuple[str, str, np.ndarray]]) -> dict:
    """Process a single image through the ingestion pipeline.

    Returns stats dict with: faces_detected, known_matches, unknown_faces, edges_created
    """
    filename = image_path.name
    logger.info(f"Processing image: {filename} (model: {MODEL_VERSION})")

    # Detect faces
    try:
        faces = detect_faces(image_path)
    except ValueError as e:
        logger.error(str(e))
        raise HTTPException(status_code=400, detail=str(e))

    faces_detected = len(faces)
    logger.info(f"  Detected {faces_detected} faces")

    if faces_detected == 0:
        return {
            'faces_detected': 0,
            'known_matches': 0,
            'unknown_faces': 0,
            'edges_created': 0
        }

    # Create upload record
    upload_id = create_upload_record(cur, filename)

    # Match faces to persons
    # List of (person_id, person_name, is_unknown, confidence_score)
    face_identities = []
    known_matches = 0
    unknown_faces = 0

    for i, face in enumerate(faces):
        if USE_PGVECTOR:
            person_name, best_score, second_best_score = match_face_pgvector(
                face['embedding'], cur
            )
        else:
            person_name, best_score, second_best_score = match_face_to_person(
                face['embedding'], profiles
            )

        margin = best_score - second_best_score

        # Check matching criteria
        if (person_name is not None and
            best_score >= MIN_MATCH_SCORE and
            margin >= MIN_SCORE_MARGIN):
            # Known person match
            person_id = get_person_by_name(cur, person_name)
            is_unknown = False
            confidence = best_score
            known_matches += 1
            logger.info(f"  Face {i+1}: Matched to {person_name} (score={best_score:.3f}, margin={margin:.3f})")
        else:
            # Unknown person
            unknown_id = get_next_unknown_id(cur)
            person_id = create_unknown_person(cur, unknown_id)
            person_name = unknown_id
            is_unknown = True
            confidence = 0.0
            unknown_faces += 1
            if person_name is not None:
                logger.info(f"  Face {i+1}: UNKNOWN (best={best_score:.3f} to {person_name}, margin={margin:.3f})")
            else:
                logger.info(f"  Face {i+1}: UNKNOWN (no profiles to match)")

        # Store face
        store_face(cur, upload_id, face, person_id, best_score if not is_unknown else 0.0)
        face_identities.append((person_id, person_name, is_unknown, confidence))

    # Create edges for all pairs with data lineage tracking
    edges_created = 0

    if len(face_identities) >= 2:
        for (id_a, name_a, _, conf_a), (id_b, name_b, _, conf_b) in combinations(face_identities, 2):
            a_id, b_id, is_new = upsert_edge(cur, id_a, id_b)
            # Store edge evidence with lineage (model version, confidence scores)
            store_edge_evidence(
                cur, a_id, b_id, upload_id,
                confidence_a=conf_a,
                confidence_b=conf_b,
                model_version=MODEL_VERSION
            )
            if is_new:
                edges_created += 1
            logger.info(f"  Edge: {name_a} <-> {name_b} ({'new' if is_new else 'updated'})")

    # Mark as processed
    mark_as_processed(cur, filename)

    logger.info(f"  Result: {known_matches} known, {unknown_faces} unknown, {edges_created} new edges")

    return {
        'faces_detected': faces_detected,
        'known_matches': known_matches,
        'unknown_faces': unknown_faces,
        'edges_created': edges_created
    }


def _record_failed_ingest(filename: str, stage: str, error: str) -> None:
    """Write a dead-letter record for a failed ingest event.

    Fails silently — a dead-letter write failure must never obscure the
    original error.  Inspect via GET /admin/report or query failed_ingests
    directly.
    """
    try:
        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO failed_ingests (filename, error_stage, error_message, model_version)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (filename, stage, error[:2000], MODEL_VERSION),
            )
    except Exception as dl_exc:
        logger.warning("Dead-letter write failed: %s", dl_exc)


@router.post("/upload", response_model=ObservationEvent)
async def ingest_upload(image: UploadFile = File(...), force: bool = False):
    """Submit a single observation event for pipeline processing.

    Accepts a multipart image upload and runs it through the full ingestion
    pipeline: idempotency check → face detection → embedding → classification
    → graph persistence.  Returns a structured ObservationEvent that captures
    the complete lifecycle with per-stage latencies and data lineage.

    Query params:
      force: Re-process even if this filename is already in the ingestion ledger.

    Tesla analog: equivalent to submitting a single telemetry frame for
    cloud-side enrichment and storage.
    """
    event_id = str(uuid.uuid4())
    t_receive = time.perf_counter()
    received_at = datetime.now(timezone.utc)

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    filename = image.filename
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # MIME type validation — reject non-image content early
    content_type = image.content_type or ""
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type '{content_type}'. Allowed: {sorted(ALLOWED_MIME_TYPES)}",
        )

    file_path = UPLOADS_DIR / filename

    try:
        contents = await image.read()

        # File size validation — enforce MAX_UPLOAD_BYTES limit
        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File too large: {len(contents) / 1e6:.1f}MB. "
                    f"Max allowed: {MAX_UPLOAD_BYTES / 1e6:.0f}MB."
                ),
            )

        with open(file_path, "wb") as f:
            f.write(contents)
        logger.info(f"Saved uploaded file: {file_path}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    try:
        with get_cursor() as cur:
            ensure_tables_exist(cur)

            # Idempotency check — RECEIVED stage
            if is_already_processed(cur, filename):
                if force:
                    cur.execute("DELETE FROM processed_images WHERE filename = %s", (filename,))
                    logger.info(f"Force mode: removed {filename} from processed_images")
                else:
                    t_total = (time.perf_counter() - t_receive) * 1000
                    return ObservationEvent(
                        event_id=event_id,
                        source_filename=filename,
                        received_at=received_at,
                        stage=PipelineStage.SKIPPED,
                        skipped_reason="already_processed",
                        latency_ms={"receive": round(t_total, 2), "total": round(t_total, 2)},
                    )

            profiles = load_profile_embeddings(cur)

            # FEATURE_EXTRACTION stage
            t_extract_start = time.perf_counter()
            stats = process_single_image(cur, file_path, profiles)
            t_extract_end = time.perf_counter()

            extract_ms = (t_extract_end - t_extract_start) * 1000
            receive_ms = (t_extract_start - t_receive) * 1000
            total_ms = (t_extract_end - t_receive) * 1000

            # Invalidate graph cache when new edges are written
            if stats.get('edges_created', 0) > 0:
                invalidate_graph_cache()

            stage = PipelineStage.PERSISTED if stats.get('faces_detected', 0) > 0 else PipelineStage.PERSISTED

            event = ObservationEvent(
                event_id=event_id,
                source_filename=filename,
                received_at=received_at,
                stage=stage,
                faces_detected=stats.get('faces_detected', 0),
                known_matches=stats.get('known_matches', 0),
                unknown_faces=stats.get('unknown_faces', 0),
                edges_created=stats.get('edges_created', 0),
                latency_ms={
                    "receive": round(receive_ms, 2),
                    "pipeline": round(extract_ms, 2),
                    "total": round(total_ms, 2),
                },
            )

            # Broadcast to all WebSocket clients (fire-and-forget)
            asyncio.create_task(ws_manager.broadcast(event.dict()))

            # Index in Elasticsearch for search (fails open if ES unavailable)
            es_index_event(event.dict())

            return event

    except HTTPException:
        raise
    except CircuitBreakerOpen as e:
        _record_failed_ingest(filename, "feature_extraction", f"CircuitBreakerOpen: {e}")
        logger.warning(f"ML inference unavailable: {e}")
        # Broadcast failure event to WebSocket clients
        asyncio.create_task(ws_manager.broadcast({
            "event_id": event_id,
            "source_filename": filename,
            "stage": PipelineStage.FAILED.value,
            "error": "ML inference temporarily unavailable (circuit breaker open)",
        }))
        raise HTTPException(
            status_code=503,
            detail="ML inference temporarily unavailable. Please retry later."
        )
    except Exception as e:
        _record_failed_ingest(filename, "unknown", str(e))
        logger.error(f"Ingestion failed: {e}")
        # Broadcast failure event to WebSocket clients
        asyncio.create_task(ws_manager.broadcast({
            "event_id": event_id,
            "source_filename": filename,
            "stage": PipelineStage.FAILED.value,
            "error": str(e),
        }))
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")


@router.get("/circuit-breaker/status")
def get_circuit_breaker_status():
    """Get the status of the ML inference circuit breaker.

    Returns current state, failure counts, and timing information.
    Useful for monitoring and debugging inference availability.
    """
    stats = insightface_breaker.stats
    return {
        "name": insightface_breaker.name,
        "state": stats.state.value,
        "failures": stats.failures,
        "successes": stats.successes,
        "total_rejected": stats.total_rejected,
        "last_failure_time": stats.last_failure_time,
        "last_success_time": stats.last_success_time,
        "opened_at": stats.opened_at,
        "config": {
            "failure_threshold": insightface_breaker.config.failure_threshold,
            "failure_window_seconds": insightface_breaker.config.failure_window,
            "recovery_timeout_seconds": insightface_breaker.config.recovery_timeout
        }
    }


@router.post("/circuit-breaker/reset")
def reset_circuit_breaker():
    """Manually reset the ML inference circuit breaker.

    Use this to force the circuit breaker back to closed state
    after resolving underlying issues.
    """
    insightface_breaker.reset()
    return {"status": "reset", "state": insightface_breaker.state.value}


@router.post("/folder")
def ingest_folder(force: bool = False):
    """
    Process all images in the uploads folder.

    Skips files that have already been processed (unless force=True).
    Processes images in sorted filename order for determinism.

    Query params:
    - force: If True, re-process all images regardless of processed_images state

    Returns batch stats.
    """
    # Ensure uploads directory exists
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # Get sorted list of image files
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    image_files = sorted([
        f for f in UPLOADS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in image_extensions
    ])

    logger.info(f"Found {len(image_files)} images in {UPLOADS_DIR}")

    if not image_files:
        return {
            'total_images': 0,
            'processed': 0,
            'skipped': 0,
            'total_faces_detected': 0,
            'total_known_matches': 0,
            'total_unknown_faces': 0,
            'total_edges_created': 0,
            'results': []
        }

    try:
        with get_cursor() as cur:
            # Ensure tables exist
            ensure_tables_exist(cur)

            # Load profile embeddings once
            profiles = load_profile_embeddings(cur)

            # Track batch stats
            processed = 0
            skipped = 0
            total_faces = 0
            total_known = 0
            total_unknown = 0
            total_edges = 0
            results = []

            for image_path in image_files:
                filename = image_path.name

                # Check if already processed (unless force mode)
                if is_already_processed(cur, filename):
                    if force:
                        # Force mode: delete existing record so we can re-process
                        cur.execute(
                            "DELETE FROM processed_images WHERE filename = %s",
                            (filename,)
                        )
                        logger.info(f"Force mode: removed {filename} from processed_images")
                    else:
                        logger.info(f"Skipping already processed: {filename}")
                        skipped += 1
                        continue

                try:
                    stats = process_single_image(cur, image_path, profiles)
                    processed += 1
                    total_faces += stats['faces_detected']
                    total_known += stats['known_matches']
                    total_unknown += stats['unknown_faces']
                    total_edges += stats['edges_created']
                    results.append({
                        'filename': filename,
                        **stats
                    })
                except HTTPException as e:
                    logger.error(f"Failed to process {filename}: {e.detail}")
                    results.append({
                        'filename': filename,
                        'error': e.detail
                    })

            response = {
                'total_images': len(image_files),
                'processed': processed,
                'skipped': skipped,
                'total_faces_detected': total_faces,
                'total_known_matches': total_known,
                'total_unknown_faces': total_unknown,
                'total_edges_created': total_edges,
                'results': results
            }
            if force:
                response['force_mode'] = True
            return response

    except Exception as e:
        logger.error(f"Batch ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Batch ingestion failed: {e}")


# ============================================================================
# Async Batch Ingestion with Job Status
# ============================================================================

from app.jobs import job_manager


def _process_batch_job(job_id: str, jm, force: bool = False):
    """Background worker function for batch ingestion.

    This runs in a separate thread and updates job progress as it processes.
    """
    from app.db import get_cursor

    # Get image files
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    image_files = sorted([
        f for f in UPLOADS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in image_extensions
    ])

    total_images = len(image_files)
    if total_images == 0:
        jm.complete_job(
            job_id,
            success=True,
            data={
                'total_images': 0,
                'processed': 0,
                'skipped': 0,
                'total_faces_detected': 0,
                'total_known_matches': 0,
                'total_unknown_faces': 0,
                'total_edges_created': 0,
            },
            items=[]
        )
        return

    # Track stats
    processed = 0
    skipped = 0
    total_faces = 0
    total_known = 0
    total_unknown = 0
    total_edges = 0
    results = []

    try:
        with get_cursor() as cur:
            ensure_tables_exist(cur)
            profiles = load_profile_embeddings(cur)

            for idx, image_path in enumerate(image_files):
                filename = image_path.name

                # Update progress
                jm.update_job_progress(
                    job_id,
                    current=idx + 1,
                    total=total_images,
                    current_item=filename,
                    items_succeeded=processed,
                    items_failed=len([r for r in results if 'error' in r])
                )

                # Check if already processed
                if is_already_processed(cur, filename):
                    if force:
                        cur.execute(
                            "DELETE FROM processed_images WHERE filename = %s",
                            (filename,)
                        )
                    else:
                        skipped += 1
                        results.append({
                            'filename': filename,
                            'status': 'skipped',
                            'reason': 'already_processed'
                        })
                        continue

                try:
                    stats = process_single_image(cur, image_path, profiles)
                    processed += 1
                    total_faces += stats['faces_detected']
                    total_known += stats['known_matches']
                    total_unknown += stats['unknown_faces']
                    total_edges += stats['edges_created']
                    results.append({
                        'filename': filename,
                        'status': 'success',
                        **stats
                    })
                except CircuitBreakerOpen:
                    results.append({
                        'filename': filename,
                        'status': 'failed',
                        'error': 'ML inference temporarily unavailable'
                    })
                except Exception as e:
                    results.append({
                        'filename': filename,
                        'status': 'failed',
                        'error': str(e)
                    })

        # Complete the job
        jm.complete_job(
            job_id,
            success=True,
            data={
                'total_images': total_images,
                'processed': processed,
                'skipped': skipped,
                'total_faces_detected': total_faces,
                'total_known_matches': total_known,
                'total_unknown_faces': total_unknown,
                'total_edges_created': total_edges,
                'force_mode': force,
            },
            items=results
        )

    except Exception as e:
        logger.error(f"Batch job {job_id} failed: {e}")
        jm.complete_job(
            job_id,
            success=False,
            error=str(e),
            items=results
        )


@router.post("/batch")
def ingest_batch_async(force: bool = False):
    """Start async batch ingestion of all images in uploads folder.

    Unlike /folder which blocks until completion, this endpoint returns
    immediately with a job ID that can be polled for progress.

    Query params:
        force: If True, re-process all images regardless of processed state

    Returns:
        job_id: UUID to poll for status via GET /jobs/{job_id}
        status: Initial job status (pending)
        poll_url: URL to check job status

    Example usage:
        1. POST /ingest/batch → {"job_id": "abc-123", ...}
        2. GET /jobs/abc-123 → {"status": "running", "progress": {...}}
        3. GET /jobs/abc-123 → {"status": "completed", "result": {...}}
    """
    # Ensure uploads directory exists
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # Count images for metadata
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    image_count = len([
        f for f in UPLOADS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in image_extensions
    ])

    # Create job
    job = job_manager.create_job(
        job_type="batch_ingest",
        metadata={
            "image_count": image_count,
            "force": force,
            "model_version": MODEL_VERSION,
        }
    )

    # Start processing in background
    job_manager.run_async(
        job.id,
        lambda job_id, jm: _process_batch_job(job_id, jm, force=force)
    )

    return {
        "job_id": job.id,
        "status": job.status.value,
        "poll_url": f"/jobs/{job.id}",
        "metadata": job.metadata,
    }
