"""Admin routes for profile management."""

import logging
import struct
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException

from app.config import PROFILES_DIR, UPLOADS_DIR, BASE_DIR, INSIGHTFACE_MODEL
from app.db import get_cursor

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
