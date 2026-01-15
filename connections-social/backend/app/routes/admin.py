"""Admin routes for profile management."""

import logging
import struct
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException

from app.config import PROFILES_DIR, INSIGHTFACE_MODEL
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

    - Scans ~/Connections/phase2-engine/data/profiles
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
            cur.execute("DELETE FROM person_profiles")
            cur.execute("DELETE FROM persons")
            logger.info("Cleared existing persons and person_profiles")

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
