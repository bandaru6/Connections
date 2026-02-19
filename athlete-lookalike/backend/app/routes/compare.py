"""
Face comparison endpoints - find your athlete lookalike!
"""

import struct
import uuid
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from insightface.app import FaceAnalysis

from .. import config
from ..db import get_cursor

router = APIRouter()

# Initialize face analysis model (lazy loading)
_face_app: Optional[FaceAnalysis] = None


def get_face_app() -> FaceAnalysis:
    """Get or initialize the face analysis model."""
    global _face_app
    if _face_app is None:
        _face_app = FaceAnalysis(
            name=config.INSIGHTFACE_MODEL,
            providers=["CPUExecutionProvider"]
        )
        _face_app.prepare(ctx_id=0, det_size=(640, 640))
    return _face_app


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def unpack_embedding(data: bytes) -> np.ndarray:
    """Unpack embedding from binary format."""
    return np.array(struct.unpack(f"{len(data)//4}f", data), dtype=np.float32)


def detect_face(image_path: Path) -> Optional[np.ndarray]:
    """Detect face and extract embedding from image."""
    app = get_face_app()
    img = cv2.imread(str(image_path))
    if img is None:
        return None

    faces = app.get(img)
    if not faces:
        return None

    # Return embedding of the largest face
    largest_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return largest_face.embedding


def find_matches(
    face_embedding: np.ndarray,
    league: Optional[str] = None,
    top_k: int = 10
) -> list[dict]:
    """Find the top matching athletes for a face embedding."""
    matches = []

    with get_cursor() as cursor:
        # Build query based on league filter
        if league:
            cursor.execute("""
                SELECT a.id, a.name, a.league, a.team, a.position,
                       ap.embedding, ap.image_path
                FROM athletes a
                JOIN athlete_profiles ap ON a.id = ap.athlete_id
                WHERE a.league = %s
            """, (league,))
        else:
            cursor.execute("""
                SELECT a.id, a.name, a.league, a.team, a.position,
                       ap.embedding, ap.image_path
                FROM athletes a
                JOIN athlete_profiles ap ON a.id = ap.athlete_id
            """)

        rows = cursor.fetchall()

    # Compare against all profiles
    for row in rows:
        profile_embedding = unpack_embedding(row["embedding"])
        similarity = cosine_similarity(face_embedding, profile_embedding)

        # Convert file path to URL
        image_path = row["image_path"]
        profiles_dir = str(config.PROFILES_DIR)
        if image_path and image_path.startswith(profiles_dir):
            image_url = "/images" + image_path[len(profiles_dir):]
        else:
            image_url = None

        matches.append({
            "athlete_id": str(row["id"]),
            "name": row["name"],
            "league": row["league"],
            "team": row["team"],
            "position": row["position"],
            "similarity": round(similarity * 100, 2),
            "image_url": image_url
        })

    # Sort by similarity and return top K (always return closest matches)
    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches[:top_k]


def get_aarav_matches() -> list[dict]:
    """Special matches for Aarav."""
    aarav_athletes = [
        ("Cody Mauch", "nfl", 47.3),
        ("Mekhi Becton", "nfl", 44.8),
        ("Paul McQuistan", "nfl", 42.1),
        ("Joshua Dobbs", "nfl", 39.6),
        ("Lamar Jackson", "nfl", 36.4),
        ("Caleb Williams", "nfl", 33.9),
        ("Jordan Walsh", "nba", 31.2),
        ("Micah Parsons", "nfl", 28.7),
    ]

    matches = []
    for name, league, similarity in aarav_athletes:
        # Convert name to folder format
        folder_name = name.replace(" ", "_")
        image_url = f"/images/{league}/{folder_name}/{folder_name}.png"

        matches.append({
            "athlete_id": f"aarav-{name.lower().replace(' ', '-')}",
            "name": name,
            "league": league,
            "team": None,
            "position": None,
            "similarity": similarity,
            "image_url": image_url
        })

    return matches


def get_prerith_matches() -> list[dict]:
    """Special matches for Prerith."""
    prerith_athletes = [
        ("Khris Middleton", "nba", 48.0),
        ("Scottie Barnes", "nba", 45.2),
        ("Dennis Schroder", "nba", 42.7),
        ("Joakim Noah", "nba", 40.1),
        ("Shelden Williams", "nba", 37.8),
        ("Cody Mauch", "nfl", 35.4),
        ("Mekhi Becton", "nfl", 33.1),
        ("Paul McQuistan", "nfl", 30.6),
        ("Joshua Dobbs", "nfl", 28.3),
        ("Lamar Jackson", "nfl", 25.9),
    ]

    matches = []
    for name, league, similarity in prerith_athletes:
        # Convert name to folder format
        folder_name = name.replace(" ", "_")
        image_url = f"/images/{league}/{folder_name}/{folder_name}.png"

        matches.append({
            "athlete_id": f"prerith-{name.lower().replace(' ', '-')}",
            "name": name,
            "league": league,
            "team": None,
            "position": None,
            "similarity": similarity,
            "image_url": image_url
        })

    return matches


@router.post("/upload")
async def compare_face(
    file: UploadFile = File(...),
    league: Optional[str] = Query(None, description="Filter by league: nba or nfl"),
    top_k: int = Query(10, ge=1, le=50, description="Number of top matches to return")
):
    """
    Upload a photo and find your athlete lookalike!

    Returns the top matching athletes based on facial similarity.
    """
    # Validate file type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # Validate league filter
    if league and league.lower() not in ["nba", "nfl"]:
        raise HTTPException(status_code=400, detail="League must be 'nba' or 'nfl'")

    # Easter egg for Aarav
    if file.filename and "aarav" in file.filename.lower():
        matches = get_aarav_matches()
        if league:
            matches = [m for m in matches if m["league"] == league.lower()]
        return {
            "success": True,
            "message": f"Found {len(matches)} matching athletes!",
            "top_match": matches[0] if matches else None,
            "matches": matches[:top_k]
        }

    # Easter egg for Prerith or Sanjay
    if file.filename and ("prerith" in file.filename.lower() or "sanjay" in file.filename.lower()):
        matches = get_prerith_matches()
        if league:
            matches = [m for m in matches if m["league"] == league.lower()]
        return {
            "success": True,
            "message": f"Found {len(matches)} matching athletes!",
            "top_match": matches[0] if matches else None,
            "matches": matches[:top_k]
        }

    # Save uploaded file temporarily
    upload_id = str(uuid.uuid4())
    upload_path = config.UPLOADS_DIR / f"{upload_id}_{file.filename}"

    try:
        contents = await file.read()
        with open(upload_path, "wb") as f:
            f.write(contents)

        # Detect face and get embedding
        face_embedding = detect_face(upload_path)
        if face_embedding is None:
            raise HTTPException(
                status_code=400,
                detail="No face detected in the uploaded image. Please upload a clear photo of a face."
            )

        # Find matches
        matches = find_matches(
            face_embedding,
            league=league.lower() if league else None,
            top_k=top_k
        )

        if not matches:
            return {
                "success": True,
                "message": "No matching athletes found. Try a different photo or remove the league filter.",
                "matches": []
            }

        return {
            "success": True,
            "message": f"Found {len(matches)} matching athletes!",
            "top_match": matches[0] if matches else None,
            "matches": matches
        }

    finally:
        # Clean up uploaded file
        if upload_path.exists():
            upload_path.unlink()


@router.post("/url")
async def compare_face_from_url(
    image_url: str,
    league: Optional[str] = Query(None, description="Filter by league: nba or nfl"),
    top_k: int = Query(10, ge=1, le=50, description="Number of top matches to return")
):
    """
    Compare a face from a URL to find athlete lookalikes.
    """
    import requests

    # Validate league filter
    if league and league.lower() not in ["nba", "nfl"]:
        raise HTTPException(status_code=400, detail="League must be 'nba' or 'nfl'")

    # Download image
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download image: {e}")

    # Save temporarily
    upload_id = str(uuid.uuid4())
    upload_path = config.UPLOADS_DIR / f"{upload_id}.jpg"

    try:
        with open(upload_path, "wb") as f:
            f.write(response.content)

        # Detect face
        face_embedding = detect_face(upload_path)
        if face_embedding is None:
            raise HTTPException(
                status_code=400,
                detail="No face detected in the image. Please provide a clear photo of a face."
            )

        # Find matches
        matches = find_matches(
            face_embedding,
            league=league.lower() if league else None,
            top_k=top_k
        )

        return {
            "success": True,
            "message": f"Found {len(matches)} matching athletes!",
            "top_match": matches[0] if matches else None,
            "matches": matches
        }

    finally:
        if upload_path.exists():
            upload_path.unlink()
