#!/usr/bin/env python3
"""
Smoke test: Run InsightFace on real photos from profiles and ingest folders.
Verifies face detection and embedding extraction without modifying any data.
"""

import os
from pathlib import Path

import cv2
from insightface.app import FaceAnalysis

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
PROFILES_DIR = PROJECT_ROOT / "data" / "profiles"
INGEST_DIR = PROJECT_ROOT / "data" / "ingest"


def get_sample_images(directory: Path, limit: int = 2) -> list[Path]:
    """Get up to `limit` jpg images from a directory (recursive for profiles)."""
    images = []
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        images.extend(directory.rglob(ext) if directory == PROFILES_DIR else directory.glob(ext))
        if len(images) >= limit:
            break
    return images[:limit]


def analyze_image(app: FaceAnalysis, img_path: Path) -> None:
    """Run face analysis on an image and print results."""
    img = cv2.imread(str(img_path))
    if img is None:
        print(f"  [ERROR] Could not load: {img_path.name}")
        return

    faces = app.get(img)
    print(f"  {img_path.name}")
    print(f"    Faces detected: {len(faces)}")
    if faces:
        print(f"    First face embedding dim: {faces[0].embedding.shape[0]}")


def main():
    print("=" * 60)
    print("InsightFace Smoke Test - Real Photos")
    print("=" * 60)

    # Initialize FaceAnalysis
    print("\nInitializing InsightFace (buffalo_l model)...")
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    print("Model loaded.\n")

    # Test profile images
    print("--- Profile Images ---")
    profile_images = get_sample_images(PROFILES_DIR, limit=2)
    if not profile_images:
        print("  No profile images found.")
    for img_path in profile_images:
        analyze_image(app, img_path)

    # Test ingest images
    print("\n--- Ingest Images ---")
    ingest_images = get_sample_images(INGEST_DIR, limit=2)
    if not ingest_images:
        print("  No ingest images found.")
    for img_path in ingest_images:
        analyze_image(app, img_path)

    print("\n" + "=" * 60)
    print("Smoke test complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
