"""Profile management routes for creating and managing person profiles."""

import logging
import os
import struct
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import INSIGHTFACE_MODEL
from app.db import get_cursor

logger = logging.getLogger(__name__)
router = APIRouter()

# Profile matching threshold (configurable via env)
PROFILE_MATCH_THRESHOLD = float(os.getenv("PROFILE_MATCH_THRESHOLD", "0.50"))

# Directory to store profile images (use project-relative path from config)
from app.config import PROFILES_DIR
PROFILE_IMAGES_DIR = PROFILES_DIR

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
    count = len(data) // 4
    return np.array(struct.unpack(f"{count}f", data), dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def extract_largest_face(image_path: Path) -> Tuple[Optional[np.ndarray], Optional[str]]:
    """
    Extract the largest face embedding from an image.
    Returns (embedding, None) on success or (None, error_message) on failure.
    """
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return None, f"Failed to read image: {image_path}"

        face_app = get_face_app()
        faces = face_app.get(img)

        if len(faces) == 0:
            return None, f"No faces detected in {image_path.name}"

        # Pick the largest face by bounding box area
        largest_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        embedding = largest_face.normed_embedding

        return embedding, None

    except Exception as e:
        return None, f"Error processing {image_path.name}: {e}"


def load_all_profile_embeddings(cur) -> List[Tuple[str, str, np.ndarray]]:
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

    return profiles


def find_best_match(
    embedding: np.ndarray,
    profiles: List[Tuple[str, str, np.ndarray]]
) -> Tuple[Optional[str], float]:
    """
    Find the best matching profile for an embedding.
    Returns (person_name, best_score) or (None, 0.0) if no profiles.
    """
    if not profiles:
        return None, 0.0

    best_name = None
    best_score = 0.0

    # Group by person and take max similarity per person
    scores_by_person = {}
    for person_id, person_name, profile_emb in profiles:
        sim = cosine_similarity(embedding, profile_emb)
        if person_name not in scores_by_person or sim > scores_by_person[person_name]:
            scores_by_person[person_name] = sim

    if scores_by_person:
        best_name = max(scores_by_person, key=scores_by_person.get)
        best_score = scores_by_person[best_name]

    return best_name, best_score


@router.get("/list")
def list_profiles(include_unknown: bool = False, limit: int = 100):
    """
    List all known profiles.

    Query params:
    - include_unknown: Include UNKNOWN_* profiles (default: False)
    - limit: Max results (default: 100)
    """
    try:
        with get_cursor() as cur:
            if include_unknown:
                cur.execute("""
                    SELECT p.id, p.name, COUNT(pp.id) as profile_count
                    FROM persons p
                    LEFT JOIN person_profiles pp ON p.id = pp.person_id
                    GROUP BY p.id, p.name
                    ORDER BY p.name
                    LIMIT %s
                """, (limit,))
            else:
                cur.execute("""
                    SELECT p.id, p.name, COUNT(pp.id) as profile_count
                    FROM persons p
                    LEFT JOIN person_profiles pp ON p.id = pp.person_id
                    WHERE p.name NOT LIKE 'UNKNOWN_%%'
                    GROUP BY p.id, p.name
                    ORDER BY p.name
                    LIMIT %s
                """, (limit,))

            profiles = []
            for row in cur.fetchall():
                profiles.append({
                    "id": str(row["id"]),
                    "name": row["name"],
                    "profile_count": row["profile_count"]
                })

            return {
                "profiles": profiles,
                "total": len(profiles)
            }

    except Exception as e:
        logger.error(f"List profiles failed: {e}")
        raise HTTPException(status_code=500, detail=f"List profiles failed: {e}")


@router.post("/check-match")
async def check_match(image: UploadFile = File(...)):
    """
    Check if a face in an uploaded image matches any existing profile.

    Returns the best match and similarity score.
    """
    # Save to temp location
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        contents = await image.read()
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        # Extract face embedding
        embedding, error = extract_largest_face(tmp_path)
        if error:
            raise HTTPException(status_code=400, detail=error)

        with get_cursor() as cur:
            profiles = load_all_profile_embeddings(cur)
            best_name, best_score = find_best_match(embedding, profiles)

            return {
                "best_match": best_name,
                "similarity": round(best_score, 4),
                "threshold": PROFILE_MATCH_THRESHOLD,
                "is_match": best_score >= PROFILE_MATCH_THRESHOLD if best_name else False
            }

    finally:
        # Clean up temp file
        tmp_path.unlink(missing_ok=True)


@router.post("/create")
async def create_profile(
    name: str = Form(...),
    images: List[UploadFile] = File(...),
    confirm: bool = Form(False),
    mode: str = Form("new")  # "new" or "merge"
):
    """
    Create a new person profile from uploaded face images.

    Form params:
    - name: Person name
    - images: 1-5 face images (multipart files)
    - confirm: If True, proceed even if there's a potential match
    - mode: "new" to create new person, "merge" to add to existing person

    Flow:
    1. Extract face embeddings from each image
    2. Compare against existing profiles
    3. If best_match >= threshold and not confirmed:
       - Return warning with best_match info, require confirm=True
    4. If confirm=True and mode="merge":
       - Add embeddings to existing person
    5. If confirm=True and mode="new" OR no match:
       - Create new person and add embeddings

    After creation, embeddings are immediately available for subsequent ingests.
    """
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    if len(images) < 1 or len(images) > 5:
        raise HTTPException(status_code=400, detail="Provide 1-5 images")

    name = name.strip()
    logger.info(f"Creating profile for: {name} with {len(images)} images")

    # Create profile images directory
    PROFILE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    person_dir = PROFILE_IMAGES_DIR / name.replace(" ", "_")
    person_dir.mkdir(parents=True, exist_ok=True)

    # Process each image and extract embeddings
    embeddings = []
    saved_images = []
    errors = []

    for i, img_file in enumerate(images):
        # Save image to disk
        filename = f"{name.replace(' ', '_')}_{i+1}.jpg"
        file_path = person_dir / filename

        try:
            contents = await img_file.read()
            with open(file_path, "wb") as f:
                f.write(contents)
            saved_images.append(str(file_path))

            # Extract embedding
            embedding, error = extract_largest_face(file_path)
            if error:
                errors.append({"image": filename, "error": error})
                continue

            embeddings.append((embedding, str(file_path)))

        except Exception as e:
            errors.append({"image": img_file.filename, "error": str(e)})

    if not embeddings:
        raise HTTPException(
            status_code=400,
            detail=f"No valid faces found in any image. Errors: {errors}"
        )

    # Check for matches against existing profiles
    try:
        with get_cursor() as cur:
            profiles = load_all_profile_embeddings(cur)

            # Find best match across all provided embeddings
            overall_best_name = None
            overall_best_score = 0.0

            for embedding, _ in embeddings:
                best_name, best_score = find_best_match(embedding, profiles)
                if best_score > overall_best_score:
                    overall_best_name = best_name
                    overall_best_score = best_score

            # Check if confirmation is needed
            if overall_best_score >= PROFILE_MATCH_THRESHOLD and not confirm:
                return {
                    "status": "confirmation_required",
                    "message": f"Potential match found: {overall_best_name} (similarity: {overall_best_score:.3f})",
                    "best_match": {
                        "name": overall_best_name,
                        "similarity": round(overall_best_score, 4)
                    },
                    "threshold": PROFILE_MATCH_THRESHOLD,
                    "options": [
                        "Set confirm=true and mode=merge to add to existing person",
                        "Set confirm=true and mode=new to create new person anyway"
                    ],
                    "embeddings_extracted": len(embeddings),
                    "errors": errors
                }

            # Determine target person
            person_id = None
            created_new = False

            if mode == "merge" and confirm and overall_best_name:
                # Merge into existing person
                cur.execute("SELECT id FROM persons WHERE name = %s", (overall_best_name,))
                row = cur.fetchone()
                if row:
                    person_id = str(row["id"])
                    name = overall_best_name  # Use existing name
                    logger.info(f"Merging into existing person: {name}")

            if person_id is None:
                # Check if person with this name already exists
                cur.execute("SELECT id FROM persons WHERE name = %s", (name,))
                row = cur.fetchone()
                if row:
                    person_id = str(row["id"])
                    logger.info(f"Adding to existing person: {name}")
                else:
                    # Create new person
                    cur.execute(
                        "INSERT INTO persons (name) VALUES (%s) RETURNING id",
                        (name,)
                    )
                    person_id = str(cur.fetchone()["id"])
                    created_new = True
                    logger.info(f"Created new person: {name}")

            # Insert embeddings
            embeddings_added = 0
            for embedding, source_image in embeddings:
                embedding_bytes = pack_embedding(embedding)
                cur.execute(
                    """
                    INSERT INTO person_profiles (person_id, source_image, embedding)
                    VALUES (%s, %s, %s)
                    """,
                    (person_id, source_image, embedding_bytes)
                )
                embeddings_added += 1

            return {
                "status": "completed",
                "created": created_new,
                "merged": mode == "merge" and confirm,
                "person_name": name,
                "person_id": person_id,
                "embeddings_added": embeddings_added,
                "best_match": {
                    "name": overall_best_name,
                    "similarity": round(overall_best_score, 4)
                } if overall_best_name else None,
                "threshold": PROFILE_MATCH_THRESHOLD,
                "saved_images": saved_images,
                "errors": errors
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Profile creation failed: {e}")


@router.delete("/{name}")
def delete_profile(name: str):
    """
    Delete a person profile by name.

    This removes the person and all their profile embeddings.
    Edges involving this person will also be deleted (CASCADE).
    """
    try:
        with get_cursor() as cur:
            cur.execute("SELECT id FROM persons WHERE name = %s", (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Person not found: {name}")

            person_id = str(row["id"])
            cur.execute("DELETE FROM persons WHERE id = %s", (person_id,))

            return {
                "status": "deleted",
                "person_name": name,
                "person_id": person_id
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete profile failed: {e}")
        raise HTTPException(status_code=500, detail=f"Delete profile failed: {e}")
