#!/usr/bin/env python3
"""
Download headshot-style profile images from Wikimedia Commons.
Validates each image with InsightFace to ensure exactly 1 face is detected.
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional
import json
import hashlib

import cv2
import requests
from insightface.app import FaceAnalysis

# Constants
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
PROFILES_DIR = PROJECT_ROOT / "data" / "profiles"
CACHE_DIR = PROJECT_ROOT / "artifacts" / ".download_cache"

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "Phase2ProfileDownloader/1.0 (educational project)"

# Rate limiting
REQUEST_DELAY = 1.0  # seconds between API requests
DOWNLOAD_DELAY = 0.5  # seconds between image downloads


def get_face_analyzer() -> FaceAnalysis:
    """Initialize InsightFace analyzer."""
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    return app


def count_existing_images(identity_dir: Path) -> int:
    """Count existing jpg/jpeg/png images in a directory."""
    count = 0
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        count += len(list(identity_dir.glob(ext)))
    return count


def search_wikimedia_images(query: str, limit: int = 20) -> list[dict]:
    """Search Wikimedia Commons for images matching query."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": "6",  # File namespace
        "gsrsearch": f'"{query}" portrait OR headshot OR face',
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|size|mime",
        "iiurlwidth": 800,  # Request thumbnail for efficiency
    }

    try:
        resp = requests.get(
            WIKIMEDIA_API,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        results = []
        for page in pages.values():
            imageinfo = page.get("imageinfo", [{}])[0]
            if imageinfo.get("mime", "").startswith("image/"):
                url = imageinfo.get("thumburl") or imageinfo.get("url")
                if url:
                    results.append({
                        "title": page.get("title", ""),
                        "url": url,
                        "width": imageinfo.get("thumbwidth") or imageinfo.get("width", 0),
                        "height": imageinfo.get("thumbheight") or imageinfo.get("height", 0),
                    })
        return results
    except Exception as e:
        print(f"    [WARN] Search failed: {e}")
        return []


def download_image(url: str, dest_path: Path) -> bool:
    """Download an image from URL to destination path."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=60,
            stream=True,
        )
        resp.raise_for_status()

        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"    [WARN] Download failed: {e}")
        return False


def validate_image(img_path: Path, face_app: FaceAnalysis) -> tuple[bool, str]:
    """
    Validate an image has exactly 1 face.
    Returns (is_valid, reason).
    """
    img = cv2.imread(str(img_path))
    if img is None:
        return False, "load_error"

    try:
        faces = face_app.get(img)
        if len(faces) == 0:
            return False, "no_face"
        elif len(faces) > 1:
            return False, "multi_face"
        else:
            return True, "valid"
    except Exception as e:
        return False, f"detection_error: {e}"


def process_identity(
    identity: str,
    target_count: int,
    face_app: FaceAnalysis,
    force: bool = False,
) -> dict:
    """
    Download and validate images for a single identity.
    Returns stats dict.
    """
    identity_dir = PROFILES_DIR / identity
    identity_dir.mkdir(parents=True, exist_ok=True)

    existing = count_existing_images(identity_dir)
    stats = {
        "identity": identity,
        "existing": existing,
        "downloaded": 0,
        "kept": 0,
        "rejected_no_face": 0,
        "rejected_multi_face": 0,
        "rejected_load_error": 0,
        "rejected_other": 0,
    }

    if existing >= target_count and not force:
        print(f"  [{identity}] Already has {existing} images, skipping (use --force to override)")
        stats["skipped"] = True
        return stats

    stats["skipped"] = False
    needed = target_count - existing if not force else target_count
    print(f"  [{identity}] Need {needed} images (existing: {existing})")

    # Search for images
    time.sleep(REQUEST_DELAY)
    candidates = search_wikimedia_images(identity, limit=needed * 5)

    if not candidates:
        print(f"    No candidates found on Wikimedia Commons")
        return stats

    print(f"    Found {len(candidates)} candidates")

    # Download and validate
    kept_count = 0
    img_index = existing + 1 if not force else 1

    for candidate in candidates:
        if kept_count >= needed:
            break

        url = candidate["url"]
        # Create temp filename
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        temp_path = identity_dir / f"_temp_{url_hash}.jpg"

        time.sleep(DOWNLOAD_DELAY)
        if not download_image(url, temp_path):
            continue

        stats["downloaded"] += 1

        # Validate with InsightFace
        is_valid, reason = validate_image(temp_path, face_app)

        if is_valid:
            # Rename to final name
            final_name = f"{identity}{img_index}.jpg"
            final_path = identity_dir / final_name
            temp_path.rename(final_path)
            print(f"    Kept: {final_name}")
            kept_count += 1
            img_index += 1
            stats["kept"] += 1
        else:
            # Remove invalid image
            temp_path.unlink()
            if reason == "no_face":
                stats["rejected_no_face"] += 1
            elif reason == "multi_face":
                stats["rejected_multi_face"] += 1
            elif reason == "load_error":
                stats["rejected_load_error"] += 1
            else:
                stats["rejected_other"] += 1

    final_count = count_existing_images(identity_dir)
    if final_count < target_count:
        print(f"    [WARN] Only achieved {final_count}/{target_count} images")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Download profile images from Wikimedia Commons"
    )
    parser.add_argument(
        "--per-id",
        type=int,
        default=3,
        help="Number of images to download per identity (default: 3)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if identity already has enough images",
    )
    parser.add_argument(
        "--identity",
        type=str,
        help="Process only this specific identity (for testing)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("Wikimedia Profile Image Downloader")
    print("=" * 70)

    # Get list of identities from folder names
    if args.identity:
        identities = [args.identity]
    else:
        identities = sorted([
            d.name for d in PROFILES_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ])

    print(f"\nIdentities to process: {len(identities)}")
    print(f"Target images per identity: {args.per_id}")
    print(f"Force re-download: {args.force}")
    print()

    # Initialize face analyzer
    print("Initializing InsightFace...")
    face_app = get_face_analyzer()
    print("Model loaded.\n")

    # Process each identity
    all_stats = []
    for i, identity in enumerate(identities, 1):
        print(f"[{i}/{len(identities)}] Processing: {identity}")
        stats = process_identity(identity, args.per_id, face_app, args.force)
        all_stats.append(stats)

    # Final report
    print("\n" + "=" * 70)
    print("FINAL REPORT")
    print("=" * 70)

    total_downloaded = sum(s["downloaded"] for s in all_stats)
    total_kept = sum(s["kept"] for s in all_stats)
    total_no_face = sum(s["rejected_no_face"] for s in all_stats)
    total_multi_face = sum(s["rejected_multi_face"] for s in all_stats)
    total_load_error = sum(s["rejected_load_error"] for s in all_stats)
    total_other = sum(s["rejected_other"] for s in all_stats)

    print(f"\nSummary:")
    print(f"  Total identities: {len(identities)}")
    print(f"  Total downloaded: {total_downloaded}")
    print(f"  Total kept (single-face): {total_kept}")
    print(f"  Rejected - no face: {total_no_face}")
    print(f"  Rejected - multi face: {total_multi_face}")
    print(f"  Rejected - load error: {total_load_error}")
    print(f"  Rejected - other: {total_other}")

    # Identities that didn't reach target
    incomplete = []
    for s in all_stats:
        if s.get("skipped"):
            continue
        final_count = count_existing_images(PROFILES_DIR / s["identity"])
        if final_count < args.per_id:
            incomplete.append((s["identity"], final_count))

    if incomplete:
        print(f"\nIdentities below target ({args.per_id} images):")
        for name, count in incomplete:
            print(f"  {name}: {count} images")
    else:
        print(f"\nAll processed identities reached target of {args.per_id} images!")

    # Per-identity breakdown
    print("\nPer-identity breakdown:")
    print(f"{'Identity':<30} {'Existing':>8} {'Downloaded':>10} {'Kept':>6} {'Rejected':>8}")
    print("-" * 70)
    for s in all_stats:
        rejected = (
            s["rejected_no_face"]
            + s["rejected_multi_face"]
            + s["rejected_load_error"]
            + s["rejected_other"]
        )
        status = "(skipped)" if s.get("skipped") else ""
        print(
            f"{s['identity']:<30} {s['existing']:>8} {s['downloaded']:>10} {s['kept']:>6} {rejected:>8} {status}"
        )

    print("\n" + "=" * 70)
    print("Download complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()
