#!/usr/bin/env python3
"""
Repopulate profiles directory by downloading images for each known person.

Uses Wikipedia/Wikimedia Commons API to find images of public figures.
Falls back to DuckDuckGo image search if Wikipedia doesn't have an image.

Usage:
    python scripts/repopulate_profiles.py

Requirements:
    pip install requests pillow
"""

import os
import re
import sys
import time
import json
import struct
import requests
from pathlib import Path
from urllib.parse import quote
from typing import Optional, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import psycopg2
from psycopg2.extras import RealDictCursor

# Configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://connections:connections@localhost:5433/connections"
)
PROFILES_DIR = Path(__file__).parent.parent / "data" / "profiles"
USER_AGENT = "ConnectionsSocial/1.0 (Profile Image Downloader)"

# Rate limiting
REQUEST_DELAY = 1.0  # seconds between requests


def get_db_connection():
    """Get database connection."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def get_known_persons() -> List[str]:
    """Get list of known (non-UNKNOWN) person names from database."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT name FROM persons
                WHERE name NOT LIKE 'UNKNOWN_%'
                ORDER BY name
            """)
            return [row['name'] for row in cur.fetchall()]
    finally:
        conn.close()


def search_wikipedia_image(person_name: str) -> Optional[str]:
    """
    Search Wikipedia for a person's image URL.
    Returns the URL of the main image if found.
    """
    # Clean up name for Wikipedia search
    search_name = person_name.replace("_", " ")

    # First, search for the page
    search_url = "https://en.wikipedia.org/w/api.php"
    search_params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": search_name,
        "srlimit": 1
    }

    try:
        resp = requests.get(search_url, params=search_params, headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("query", {}).get("search"):
            print(f"  No Wikipedia page found for: {person_name}")
            return None

        page_title = data["query"]["search"][0]["title"]

        # Now get the page image
        image_params = {
            "action": "query",
            "format": "json",
            "titles": page_title,
            "prop": "pageimages",
            "pithumbsize": 500  # Request 500px thumbnail
        }

        resp = requests.get(search_url, params=image_params, headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            if "thumbnail" in page_data:
                return page_data["thumbnail"]["source"]

        print(f"  No image found on Wikipedia page for: {person_name}")
        return None

    except Exception as e:
        print(f"  Wikipedia search error for {person_name}: {e}")
        return None


def search_duckduckgo_image(person_name: str) -> Optional[str]:
    """
    Fallback: Search DuckDuckGo for a person's image.
    Uses the instant answer API which sometimes has images.
    """
    search_name = person_name.replace("_", " ")
    url = f"https://api.duckduckgo.com/?q={quote(search_name)}&format=json&no_html=1"

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # Try to get the main image
        if data.get("Image"):
            image_url = data["Image"]
            if not image_url.startswith("http"):
                image_url = "https://duckduckgo.com" + image_url
            return image_url

        return None

    except Exception as e:
        print(f"  DuckDuckGo search error for {person_name}: {e}")
        return None


def download_image(url: str, save_path: Path) -> bool:
    """Download an image from URL and save to path."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, stream=True)
        resp.raise_for_status()

        # Check content type
        content_type = resp.headers.get("Content-Type", "")
        if "image" not in content_type:
            print(f"  Not an image: {content_type}")
            return False

        # Save the image
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # Verify it's a valid image
        file_size = save_path.stat().st_size
        if file_size < 1000:  # Less than 1KB is probably not a real image
            print(f"  Image too small ({file_size} bytes), skipping")
            save_path.unlink()
            return False

        return True

    except Exception as e:
        print(f"  Download error: {e}")
        if save_path.exists():
            save_path.unlink()
        return False


def repopulate_profiles():
    """Main function to repopulate all profiles."""
    print("=" * 60)
    print("Profile Repopulation Script")
    print("=" * 60)

    # Get list of known persons
    print("\nFetching known persons from database...")
    persons = get_known_persons()
    print(f"Found {len(persons)} known persons\n")

    # Create profiles directory
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    # Track results
    success = []
    failed = []
    skipped = []

    for i, person_name in enumerate(persons, 1):
        print(f"[{i}/{len(persons)}] {person_name}")

        # Create person directory
        # Convert spaces to underscores for directory name
        dir_name = person_name.replace(" ", "_")
        person_dir = PROFILES_DIR / dir_name

        # Check if already has images
        if person_dir.exists():
            existing_images = list(person_dir.glob("*.jpg")) + list(person_dir.glob("*.png"))
            if existing_images:
                print(f"  Already has {len(existing_images)} image(s), skipping")
                skipped.append(person_name)
                continue

        # Search for image
        image_url = search_wikipedia_image(person_name)

        if not image_url:
            image_url = search_duckduckgo_image(person_name)

        if not image_url:
            print(f"  FAILED: No image found")
            failed.append(person_name)
            time.sleep(REQUEST_DELAY)
            continue

        # Download image
        save_path = person_dir / f"{dir_name}_1.jpg"
        if download_image(image_url, save_path):
            print(f"  SUCCESS: Saved to {save_path.name}")
            success.append(person_name)
        else:
            print(f"  FAILED: Could not download image")
            failed.append(person_name)

        # Rate limiting
        time.sleep(REQUEST_DELAY)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total persons: {len(persons)}")
    print(f"Successfully downloaded: {len(success)}")
    print(f"Skipped (already exists): {len(skipped)}")
    print(f"Failed: {len(failed)}")

    if failed:
        print(f"\nFailed persons:")
        for name in failed:
            print(f"  - {name}")

    print(f"\nProfiles directory: {PROFILES_DIR}")
    print("\nNext steps:")
    print("1. Review downloaded images for quality")
    print("2. Run 'curl -X POST http://localhost:8000/admin/rebuild-profile-index'")
    print("   to rebuild the profile index with the new images")


if __name__ == "__main__":
    repopulate_profiles()
