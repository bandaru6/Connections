"""
Admin endpoints for managing athlete data and embeddings.
"""

import json
import struct
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, BackgroundTasks
from insightface.app import FaceAnalysis

from .. import config
from ..db import get_cursor

router = APIRouter()

# Face analysis model
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


def pack_embedding(embedding: np.ndarray) -> bytes:
    """Pack embedding into binary format for storage."""
    return struct.pack(f"{len(embedding)}f", *embedding.tolist())


def extract_embedding(image_path: Path) -> Optional[np.ndarray]:
    """Extract face embedding from an image."""
    app = get_face_app()
    img = cv2.imread(str(image_path))
    if img is None:
        return None

    faces = app.get(img)
    if not faces:
        return None

    # Return embedding of the largest face
    largest = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return largest.embedding


@router.post("/rebuild-index")
async def rebuild_profile_index():
    """
    Scan the profiles directory and rebuild all athlete embeddings.

    Expected directory structure:
    data/profiles/
    ├── nba/
    │   ├── LeBron_James/
    │   │   └── LeBron_James.png
    │   └── Stephen_Curry/
    │       └── Stephen_Curry.png
    └── nfl/
        ├── Patrick_Mahomes/
        │   └── Patrick_Mahomes.png
        └── ...
    """
    profiles_dir = config.PROFILES_DIR
    results = {"processed": 0, "skipped": 0, "errors": [], "by_league": {}}

    # Also check for manifest files
    for manifest_file in profiles_dir.glob("*_players.json"):
        league = manifest_file.stem.replace("_players", "")
        with open(manifest_file) as f:
            players = json.load(f)
            results["by_league"][league] = {"manifest_count": len(players)}

    for league_dir in profiles_dir.iterdir():
        if not league_dir.is_dir():
            continue

        league = league_dir.name.lower()
        if league not in ["nba", "nfl"]:
            continue

        league_stats = results["by_league"].get(league, {})
        league_stats["processed"] = 0
        league_stats["skipped"] = 0

        for player_dir in league_dir.iterdir():
            if not player_dir.is_dir():
                continue

            player_name = player_dir.name.replace("_", " ")

            # Find image file
            image_files = list(player_dir.glob("*.png")) + list(player_dir.glob("*.jpg"))
            if not image_files:
                league_stats["skipped"] = league_stats.get("skipped", 0) + 1
                results["skipped"] += 1
                continue

            image_path = image_files[0]

            try:
                # Extract embedding
                embedding = extract_embedding(image_path)
                if embedding is None:
                    results["errors"].append(f"No face found: {player_name}")
                    league_stats["skipped"] = league_stats.get("skipped", 0) + 1
                    results["skipped"] += 1
                    continue

                # Upsert athlete and profile
                with get_cursor() as cursor:
                    # Insert or get athlete
                    cursor.execute("""
                        INSERT INTO athletes (name, league)
                        VALUES (%s, %s)
                        ON CONFLICT (name, league) DO UPDATE SET name = EXCLUDED.name
                        RETURNING id
                    """, (player_name, league))
                    athlete_id = cursor.fetchone()["id"]

                    # Delete existing profiles for this athlete
                    cursor.execute(
                        "DELETE FROM athlete_profiles WHERE athlete_id = %s",
                        (athlete_id,)
                    )

                    # Insert new profile
                    cursor.execute("""
                        INSERT INTO athlete_profiles (athlete_id, image_path, embedding)
                        VALUES (%s, %s, %s)
                    """, (athlete_id, str(image_path), pack_embedding(embedding)))

                results["processed"] += 1
                league_stats["processed"] = league_stats.get("processed", 0) + 1

            except Exception as e:
                results["errors"].append(f"{player_name}: {str(e)}")

        results["by_league"][league] = league_stats

    return {
        "status": "complete",
        "total_processed": results["processed"],
        "total_skipped": results["skipped"],
        "by_league": results["by_league"],
        "errors": results["errors"][:20] if results["errors"] else []
    }


@router.post("/reset")
async def reset_database():
    """Clear all athlete data (use with caution!)."""
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM athlete_profiles")
        cursor.execute("DELETE FROM athletes")

    return {"status": "complete", "message": "All athlete data cleared"}


@router.get("/status")
async def system_status():
    """Get system status and database statistics."""
    with get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as count FROM athletes")
        athlete_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM athlete_profiles")
        profile_count = cursor.fetchone()["count"]

        cursor.execute("""
            SELECT league, COUNT(*) as count
            FROM athletes
            GROUP BY league
        """)
        by_league = {row["league"]: row["count"] for row in cursor.fetchall()}

    # Check profiles directory
    profile_dirs = {
        "nba": len(list((config.PROFILES_DIR / "nba").glob("*"))) if (config.PROFILES_DIR / "nba").exists() else 0,
        "nfl": len(list((config.PROFILES_DIR / "nfl").glob("*"))) if (config.PROFILES_DIR / "nfl").exists() else 0
    }

    return {
        "status": "healthy",
        "database": {
            "athletes": athlete_count,
            "profiles": profile_count,
            "by_league": by_league
        },
        "filesystem": {
            "profile_directories": profile_dirs
        },
        "config": {
            "min_match_score": config.MIN_MATCH_SCORE,
            "model": config.INSIGHTFACE_MODEL
        }
    }
