"""Ingestion routes for processing photos and building social graph."""

import json
import logging
import struct
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import UPLOADS_DIR, INSIGHTFACE_MODEL
from app.db import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter()

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


def load_profile_embeddings(cur) -> List[Tuple[str, str, np.ndarray]]:
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


def get_person_by_name(cur, name: str) -> Optional[str]:
    """Get person UUID by name."""
    cur.execute("SELECT id FROM persons WHERE name = %s", (name,))
    row = cur.fetchone()
    return str(row['id']) if row else None


def match_face_to_person(
    face_embedding: np.ndarray,
    profiles: List[Tuple[str, str, np.ndarray]]
) -> Tuple[Optional[str], float, float]:
    """Match a face embedding against known profiles.

    Returns (person_name, best_score, second_best_score).
    Returns (None, 0, 0) if no profiles available.
    """
    if not profiles:
        return None, 0.0, 0.0

    # Compute similarities to all profiles
    scores_by_person: Dict[str, float] = {}

    for person_id, person_name, profile_emb in profiles:
        sim = cosine_similarity(face_embedding, profile_emb)
        # Keep max score per person (a person may have multiple profiles)
        if person_name not in scores_by_person or sim > scores_by_person[person_name]:
            scores_by_person[person_name] = sim

    if not scores_by_person:
        return None, 0.0, 0.0

    # Sort by score descending
    sorted_scores = sorted(scores_by_person.items(), key=lambda x: x[1], reverse=True)

    best_name, best_score = sorted_scores[0]
    second_best_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

    return best_name, best_score, second_best_score


def detect_faces(image_path: Path) -> List[dict]:
    """Detect faces in an image.

    Returns list of face dicts sorted left-to-right by bounding box x-coordinate.
    Each dict has: bbox, embedding
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Failed to read image: {image_path}")

    face_app = get_face_app()
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


def upsert_edge(cur, person_a_id: str, person_b_id: str) -> Tuple[str, str, bool]:
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


def store_edge_evidence(cur, person_a_id: str, person_b_id: str, upload_id: str):
    """Store edge evidence."""
    # Ensure ordered pair
    if person_a_id > person_b_id:
        person_a_id, person_b_id = person_b_id, person_a_id

    cur.execute(
        """
        INSERT INTO edge_evidence (person_a_id, person_b_id, upload_id)
        VALUES (%s, %s, %s)
        """,
        (person_a_id, person_b_id, upload_id)
    )


def process_single_image(cur, image_path: Path, profiles: List[Tuple[str, str, np.ndarray]]) -> dict:
    """Process a single image through the ingestion pipeline.

    Returns stats dict with: faces_detected, known_matches, unknown_faces, edges_created
    """
    filename = image_path.name
    logger.info(f"Processing image: {filename}")

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
    face_identities = []  # List of (person_id, person_name, is_unknown)
    known_matches = 0
    unknown_faces = 0

    for i, face in enumerate(faces):
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
            known_matches += 1
            logger.info(f"  Face {i+1}: Matched to {person_name} (score={best_score:.3f}, margin={margin:.3f})")
        else:
            # Unknown person
            unknown_id = get_next_unknown_id(cur)
            person_id = create_unknown_person(cur, unknown_id)
            person_name = unknown_id
            is_unknown = True
            unknown_faces += 1
            if person_name is not None:
                logger.info(f"  Face {i+1}: UNKNOWN (best={best_score:.3f} to {person_name}, margin={margin:.3f})")
            else:
                logger.info(f"  Face {i+1}: UNKNOWN (no profiles to match)")

        # Store face
        store_face(cur, upload_id, face, person_id, best_score if not is_unknown else 0.0)
        face_identities.append((person_id, person_name, is_unknown))

    # Create edges for all pairs
    edges_created = 0

    if len(face_identities) >= 2:
        for (id_a, name_a, _), (id_b, name_b, _) in combinations(face_identities, 2):
            a_id, b_id, is_new = upsert_edge(cur, id_a, id_b)
            store_edge_evidence(cur, a_id, b_id, upload_id)
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


@router.post("/upload")
async def ingest_upload(image: UploadFile = File(...)):
    """
    Ingest a single uploaded image.

    Accepts multipart form with:
    - image: The image file to process

    Returns stats about faces detected, matches, and edges created.
    """
    # Ensure uploads directory exists
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # Save uploaded file
    filename = image.filename
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    file_path = UPLOADS_DIR / filename

    try:
        contents = await image.read()
        with open(file_path, "wb") as f:
            f.write(contents)
        logger.info(f"Saved uploaded file: {file_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    try:
        with get_cursor() as cur:
            # Ensure tables exist
            ensure_tables_exist(cur)

            # Check if already processed
            if is_already_processed(cur, filename):
                raise HTTPException(
                    status_code=400,
                    detail=f"Image {filename} has already been processed"
                )

            # Load profile embeddings
            profiles = load_profile_embeddings(cur)

            # Process the image
            stats = process_single_image(cur, file_path, profiles)

            return stats

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")


@router.post("/folder")
def ingest_folder():
    """
    Process all images in the uploads folder.

    Skips files that have already been processed.
    Processes images in sorted filename order for determinism.

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

                # Check if already processed
                if is_already_processed(cur, filename):
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

            return {
                'total_images': len(image_files),
                'processed': processed,
                'skipped': skipped,
                'total_faces_detected': total_faces,
                'total_known_matches': total_known,
                'total_unknown_faces': total_unknown,
                'total_edges_created': total_edges,
                'results': results
            }

    except Exception as e:
        logger.error(f"Batch ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Batch ingestion failed: {e}")
