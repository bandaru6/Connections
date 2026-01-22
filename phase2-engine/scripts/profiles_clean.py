#!/usr/bin/env python3
"""
Profile Image Cleaner & Downloader

Downloads headshot-style profile images from Wikimedia Commons/Wikipedia.
Validates each image with InsightFace to ensure exactly 1 face detected.
Uses a two-pass approach: coverage first, then fill to target.
"""

import argparse
import json
import os
import sys
import time
import random
import hashlib
import functools
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from datetime import datetime

import cv2
import numpy as np
import requests
from insightface.app import FaceAnalysis

# Force unbuffered output
print = functools.partial(print, flush=True)

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
PROFILES_DIR = PROJECT_ROOT / "data" / "profiles"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
CACHE_FILE = ARTIFACTS_DIR / "wiki_cache.json"
REPORT_FILE = ARTIFACTS_DIR / "profiles_clean_report.json"

# API endpoints
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

USER_AGENT = "Phase2ProfileCleaner/1.0 (educational project; contact: github.com/phase2)"

# Minimum image dimensions
MIN_WIDTH = 150
MIN_HEIGHT = 150


@dataclass
class IdentityStats:
    """Stats for a single identity."""
    name: str
    existing_before: int = 0
    existing_after: int = 0
    downloaded_ok: int = 0
    rejected_no_face: int = 0
    rejected_multi_face: int = 0
    rejected_load_error: int = 0
    rejected_too_small: int = 0
    api_429_count: int = 0
    candidates_tried: int = 0


@dataclass
class GlobalStats:
    """Global run statistics."""
    total_identities: int = 0
    met_target: int = 0
    partial: int = 0
    empty: int = 0
    total_accepted: int = 0
    total_rejected_no_face: int = 0
    total_rejected_multi_face: int = 0
    total_rejected_load_error: int = 0
    total_rejected_too_small: int = 0
    total_api_429: int = 0
    identities_still_empty: list = field(default_factory=list)
    identities_partial: list = field(default_factory=list)
    identities_met_target: list = field(default_factory=list)


class RateLimiter:
    """Handle rate limiting with exponential backoff."""

    def __init__(self, base_delay: float = 1.0):
        self.base_delay = base_delay
        self.consecutive_429s = 0
        self.last_request_time = 0

    def wait(self):
        """Wait appropriate time before next request."""
        now = time.time()
        elapsed = now - self.last_request_time

        # Add jitter to avoid thundering herd
        delay = self.base_delay + random.uniform(0, 0.5)

        # Exponential backoff if we've hit rate limits
        if self.consecutive_429s > 0:
            delay = min(delay * (2 ** self.consecutive_429s), 60)

        if elapsed < delay:
            time.sleep(delay - elapsed)

        self.last_request_time = time.time()

    def handle_429(self, response: requests.Response) -> float:
        """Handle 429 response, return wait time."""
        self.consecutive_429s += 1

        # Check Retry-After header
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                wait_time = int(retry_after)
            except ValueError:
                wait_time = 30
        else:
            wait_time = min(self.base_delay * (2 ** self.consecutive_429s), 120)

        return wait_time

    def reset_backoff(self):
        """Reset backoff after successful request."""
        self.consecutive_429s = 0


class WikiCache:
    """Cache for Wikipedia/Wikimedia search results."""

    def __init__(self, cache_file: Path):
        self.cache_file = cache_file
        self.cache = self._load()

    def _load(self) -> dict:
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def save(self):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w") as f:
            json.dump(self.cache, f, indent=2)

    def get(self, identity: str) -> Optional[list]:
        return self.cache.get(identity)

    def set(self, identity: str, urls: list):
        self.cache[identity] = {
            "urls": urls,
            "timestamp": datetime.now().isoformat(),
        }
        self.save()

    def get_urls(self, identity: str) -> Optional[list]:
        data = self.cache.get(identity)
        if data:
            return data.get("urls", [])
        return None


def get_face_analyzer() -> FaceAnalysis:
    """Initialize InsightFace analyzer."""
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    return app


def count_existing_images(identity_dir: Path) -> int:
    """Count existing jpg/jpeg/png images."""
    count = 0
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        count += len(list(identity_dir.glob(ext)))
    return count


def get_next_image_number(identity_dir: Path) -> int:
    """Get next available image number."""
    existing = []
    for f in identity_dir.glob("*.jpg"):
        try:
            num = int(f.stem)
            existing.append(num)
        except ValueError:
            pass
    return max(existing, default=0) + 1


def search_wikimedia_commons(
    identity: str,
    rate_limiter: RateLimiter,
    limit: int = 50
) -> tuple[list[dict], int]:
    """
    Search Wikimedia Commons for images.
    Returns (list of image info, 429 count).
    """
    rate_limiter.wait()

    # Try multiple search strategies
    search_queries = [
        f'"{identity}" portrait',
        f'"{identity}" headshot',
        f'"{identity}"',
    ]

    all_results = []
    seen_urls = set()
    api_429_count = 0

    for query in search_queries:
        if len(all_results) >= limit:
            break

        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": "6",  # File namespace
            "gsrsearch": query,
            "gsrlimit": min(limit - len(all_results), 30),
            "prop": "imageinfo",
            "iiprop": "url|size|mime",
            "iiurlwidth": 800,
        }

        try:
            resp = requests.get(
                WIKIMEDIA_API,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )

            if resp.status_code == 429:
                api_429_count += 1
                wait_time = rate_limiter.handle_429(resp)
                print(f"    [429] Rate limited, waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue

            resp.raise_for_status()
            rate_limiter.reset_backoff()

            data = resp.json()
            pages = data.get("query", {}).get("pages", {})

            for page in pages.values():
                imageinfo = page.get("imageinfo", [{}])[0]
                mime = imageinfo.get("mime", "")

                if not mime.startswith("image/") or "svg" in mime:
                    continue

                url = imageinfo.get("thumburl") or imageinfo.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append({
                        "title": page.get("title", ""),
                        "url": url,
                        "width": imageinfo.get("thumbwidth") or imageinfo.get("width", 0),
                        "height": imageinfo.get("thumbheight") or imageinfo.get("height", 0),
                    })

        except requests.exceptions.RequestException as e:
            print(f"    [WARN] Search error: {e}")

        rate_limiter.wait()

    return all_results, api_429_count


def search_wikipedia_infobox(
    identity: str,
    rate_limiter: RateLimiter
) -> tuple[list[dict], int]:
    """
    Try to get the main Wikipedia infobox image for a person.
    Returns (list of image info, 429 count).
    """
    rate_limiter.wait()
    api_429_count = 0

    # First, get the page and its images
    params = {
        "action": "query",
        "format": "json",
        "titles": identity,
        "prop": "pageimages|images",
        "pithumbsize": 800,
        "pilicense": "any",
    }

    try:
        resp = requests.get(
            WIKIPEDIA_API,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )

        if resp.status_code == 429:
            api_429_count += 1
            wait_time = rate_limiter.handle_429(resp)
            print(f"    [429] Rate limited, waiting {wait_time:.1f}s...")
            time.sleep(wait_time)
            return [], api_429_count

        resp.raise_for_status()
        rate_limiter.reset_backoff()

        data = resp.json()
        pages = data.get("query", {}).get("pages", {})

        results = []
        for page in pages.values():
            # Try pageimages (main infobox image)
            thumbnail = page.get("thumbnail", {})
            if thumbnail.get("source"):
                results.append({
                    "title": f"Wikipedia infobox: {identity}",
                    "url": thumbnail["source"],
                    "width": thumbnail.get("width", 0),
                    "height": thumbnail.get("height", 0),
                    "priority": True,  # Prioritize infobox images
                })

        return results, api_429_count

    except requests.exceptions.RequestException as e:
        print(f"    [WARN] Wikipedia search error: {e}")
        return [], api_429_count


def download_image(url: str, dest_path: Path, rate_limiter: RateLimiter) -> tuple[bool, int]:
    """
    Download image from URL.
    Returns (success, 429_count).
    """
    rate_limiter.wait()
    api_429_count = 0

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=60,
            stream=True,
        )

        if resp.status_code == 429:
            api_429_count += 1
            wait_time = rate_limiter.handle_429(resp)
            print(f"    [429] Download rate limited, waiting {wait_time:.1f}s...")
            time.sleep(wait_time)
            return False, api_429_count

        resp.raise_for_status()
        rate_limiter.reset_backoff()

        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return True, api_429_count

    except requests.exceptions.RequestException as e:
        return False, api_429_count


def validate_image(
    img_path: Path,
    face_app: FaceAnalysis,
    min_width: int = MIN_WIDTH,
    min_height: int = MIN_HEIGHT
) -> tuple[str, Optional[float]]:
    """
    Validate image has exactly 1 face.
    Returns (status, face_area_ratio).
    Status: "valid", "no_face", "multi_face", "load_error", "too_small"
    """
    img = cv2.imread(str(img_path))
    if img is None:
        return "load_error", None

    h, w = img.shape[:2]
    if w < min_width or h < min_height:
        return "too_small", None

    try:
        faces = face_app.get(img)

        if len(faces) == 0:
            return "no_face", None
        elif len(faces) > 1:
            return "multi_face", None
        else:
            # Calculate face area ratio (larger = better headshot)
            face = faces[0]
            bbox = face.bbox
            face_w = bbox[2] - bbox[0]
            face_h = bbox[3] - bbox[1]
            face_area = face_w * face_h
            img_area = w * h
            ratio = face_area / img_area if img_area > 0 else 0
            return "valid", ratio

    except Exception as e:
        return "load_error", None


def get_candidates(
    identity: str,
    cache: WikiCache,
    rate_limiter: RateLimiter,
    max_candidates: int
) -> tuple[list[dict], int]:
    """
    Get candidate image URLs for an identity.
    Uses cache if available.
    Returns (candidates, api_429_count).
    """
    # Check cache first
    cached = cache.get_urls(identity)
    if cached is not None:
        print(f"    Using {len(cached)} cached candidates")
        return [{"url": u, "title": "cached"} for u in cached], 0

    print(f"    Searching Wikipedia/Wikimedia...")
    all_candidates = []
    api_429_count = 0

    # Try Wikipedia infobox first (usually best quality)
    wiki_results, count = search_wikipedia_infobox(identity, rate_limiter)
    all_candidates.extend(wiki_results)
    api_429_count += count

    # Then search Wikimedia Commons
    commons_results, count = search_wikimedia_commons(
        identity, rate_limiter, limit=max_candidates
    )
    all_candidates.extend(commons_results)
    api_429_count += count

    # Sort: prioritize infobox, then by resolution
    all_candidates.sort(
        key=lambda x: (
            -int(x.get("priority", False)),
            -(x.get("width", 0) * x.get("height", 0))
        )
    )

    # Limit and cache
    candidates = all_candidates[:max_candidates]
    cache.set(identity, [c["url"] for c in candidates])

    print(f"    Found {len(candidates)} candidates")
    return candidates, api_429_count


def process_identity(
    identity: str,
    target: int,
    face_app: FaceAnalysis,
    cache: WikiCache,
    rate_limiter: RateLimiter,
    max_candidates: int,
    max_downloads: int,
    force: bool,
    pass_target: int,  # 1 for pass1 (coverage), target for pass2
) -> IdentityStats:
    """
    Process a single identity.
    Downloads images until reaching pass_target or exhausting candidates.
    """
    identity_dir = PROFILES_DIR / identity
    identity_dir.mkdir(parents=True, exist_ok=True)

    stats = IdentityStats(name=identity)
    stats.existing_before = count_existing_images(identity_dir)

    # Skip if already at pass target (unless force)
    if stats.existing_before >= pass_target and not force:
        stats.existing_after = stats.existing_before
        return stats

    needed = pass_target - stats.existing_before
    if needed <= 0:
        stats.existing_after = stats.existing_before
        return stats

    # Get candidates
    candidates, api_429 = get_candidates(identity, cache, rate_limiter, max_candidates)
    stats.api_429_count += api_429

    if not candidates:
        print(f"    No candidates found")
        stats.existing_after = count_existing_images(identity_dir)
        return stats

    # Download and validate
    accepted = 0
    next_num = get_next_image_number(identity_dir)
    downloads_this_run = 0

    for candidate in candidates:
        if accepted >= needed:
            break
        if downloads_this_run >= max_downloads:
            print(f"    Hit max downloads limit ({max_downloads})")
            break

        stats.candidates_tried += 1
        url = candidate["url"]

        # Create temp file
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        temp_path = identity_dir / f"_temp_{url_hash}.jpg"

        # Download
        success, api_429 = download_image(url, temp_path, rate_limiter)
        stats.api_429_count += api_429

        if not success:
            if temp_path.exists():
                temp_path.unlink()
            continue

        downloads_this_run += 1

        # Validate
        status, face_ratio = validate_image(temp_path, face_app)

        if status == "valid":
            # Save with proper name
            final_path = identity_dir / f"{next_num}.jpg"
            temp_path.rename(final_path)
            print(f"    Kept: {next_num}.jpg (face ratio: {face_ratio:.2%})")
            accepted += 1
            next_num += 1
            stats.downloaded_ok += 1
        else:
            # Remove invalid
            if temp_path.exists():
                temp_path.unlink()

            if status == "no_face":
                stats.rejected_no_face += 1
            elif status == "multi_face":
                stats.rejected_multi_face += 1
            elif status == "load_error":
                stats.rejected_load_error += 1
            elif status == "too_small":
                stats.rejected_too_small += 1

    stats.existing_after = count_existing_images(identity_dir)
    return stats


def run_pass(
    identities: list[str],
    pass_name: str,
    pass_target: int,
    target: int,
    face_app: FaceAnalysis,
    cache: WikiCache,
    rate_limiter: RateLimiter,
    max_candidates: int,
    max_downloads: int,
    force: bool,
    all_stats: dict[str, IdentityStats],
) -> int:
    """
    Run a single pass over identities.
    Returns number of identities processed.
    """
    print(f"\n{'='*70}")
    print(f"{pass_name}: Target = {pass_target} image(s) per identity")
    print(f"{'='*70}\n")

    processed = 0
    for i, identity in enumerate(identities, 1):
        current_count = count_existing_images(PROFILES_DIR / identity)

        # Skip if already at pass target
        if current_count >= pass_target and not force:
            continue

        print(f"[{i}/{len(identities)}] {identity} (currently: {current_count})")

        stats = process_identity(
            identity=identity,
            target=target,
            face_app=face_app,
            cache=cache,
            rate_limiter=rate_limiter,
            max_candidates=max_candidates,
            max_downloads=max_downloads,
            force=force,
            pass_target=pass_target,
        )

        # Merge stats
        if identity in all_stats:
            existing = all_stats[identity]
            existing.existing_after = stats.existing_after
            existing.downloaded_ok += stats.downloaded_ok
            existing.rejected_no_face += stats.rejected_no_face
            existing.rejected_multi_face += stats.rejected_multi_face
            existing.rejected_load_error += stats.rejected_load_error
            existing.rejected_too_small += stats.rejected_too_small
            existing.api_429_count += stats.api_429_count
            existing.candidates_tried += stats.candidates_tried
        else:
            all_stats[identity] = stats

        processed += 1

    return processed


def generate_report(
    all_stats: dict[str, IdentityStats],
    target: int,
) -> GlobalStats:
    """Generate global statistics from per-identity stats."""
    global_stats = GlobalStats()
    global_stats.total_identities = len(all_stats)

    for stats in all_stats.values():
        # Aggregate
        global_stats.total_accepted += stats.downloaded_ok
        global_stats.total_rejected_no_face += stats.rejected_no_face
        global_stats.total_rejected_multi_face += stats.rejected_multi_face
        global_stats.total_rejected_load_error += stats.rejected_load_error
        global_stats.total_rejected_too_small += stats.rejected_too_small
        global_stats.total_api_429 += stats.api_429_count

        # Categorize
        final_count = stats.existing_after
        if final_count >= target:
            global_stats.met_target += 1
            global_stats.identities_met_target.append(stats.name)
        elif final_count > 0:
            global_stats.partial += 1
            global_stats.identities_partial.append(stats.name)
        else:
            global_stats.empty += 1
            global_stats.identities_still_empty.append(stats.name)

    return global_stats


def save_report(
    all_stats: dict[str, IdentityStats],
    global_stats: GlobalStats,
    target: int,
):
    """Save machine-readable report."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "timestamp": datetime.now().isoformat(),
        "target": target,
        "global": asdict(global_stats),
        "per_identity": {name: asdict(s) for name, s in all_stats.items()},
    }

    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport saved to: {REPORT_FILE}")


def print_summary(global_stats: GlobalStats, target: int):
    """Print summary table."""
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print(f"\n{'Metric':<35} {'Count':>10}")
    print("-" * 50)
    print(f"{'Total identities':<35} {global_stats.total_identities:>10}")
    print(f"{'Met target (>=' + str(target) + ')':<35} {global_stats.met_target:>10}")
    print(f"{'Partial (1-' + str(target-1) + ')':<35} {global_stats.partial:>10}")
    print(f"{'Empty (0)':<35} {global_stats.empty:>10}")
    print("-" * 50)
    print(f"{'Total accepted downloads':<35} {global_stats.total_accepted:>10}")
    print(f"{'Rejected - no face':<35} {global_stats.total_rejected_no_face:>10}")
    print(f"{'Rejected - multi face':<35} {global_stats.total_rejected_multi_face:>10}")
    print(f"{'Rejected - load error':<35} {global_stats.total_rejected_load_error:>10}")
    print(f"{'Rejected - too small':<35} {global_stats.total_rejected_too_small:>10}")
    print(f"{'API 429 errors':<35} {global_stats.total_api_429:>10}")

    if global_stats.identities_still_empty:
        print(f"\nIdentities still empty ({len(global_stats.identities_still_empty)}):")
        for name in sorted(global_stats.identities_still_empty):
            print(f"  - {name}")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Download and validate profile headshot images"
    )
    parser.add_argument(
        "--target",
        type=int,
        default=3,
        help="Target number of images per identity (default: 3)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if identity already has enough images",
    )
    parser.add_argument(
        "--only",
        type=str,
        help="Process only this specific identity",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=80,
        help="Max candidate images to consider per identity (default: 80)",
    )
    parser.add_argument(
        "--sleep-base",
        type=float,
        default=1.0,
        help="Base delay between API calls in seconds (default: 1.0)",
    )
    parser.add_argument(
        "--max-downloads-per-run",
        type=int,
        default=250,
        help="Safety cap on total downloads per run (default: 250)",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("Profile Image Cleaner")
    print("=" * 70)
    print(f"\nTarget: {args.target} images per identity")
    print(f"Max candidates: {args.max_candidates}")
    print(f"Base delay: {args.sleep_base}s")
    print(f"Max downloads: {args.max_downloads_per_run}")

    # Get identities
    if args.only:
        identities = [args.only]
    else:
        identities = sorted([
            d.name for d in PROFILES_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ])

    print(f"Identities to process: {len(identities)}")

    # Initialize components
    print("\nInitializing InsightFace...")
    face_app = get_face_analyzer()
    print("Model loaded.")

    cache = WikiCache(CACHE_FILE)
    rate_limiter = RateLimiter(base_delay=args.sleep_base)
    all_stats: dict[str, IdentityStats] = {}

    # Initialize stats for all identities
    for identity in identities:
        identity_dir = PROFILES_DIR / identity
        stats = IdentityStats(name=identity)
        stats.existing_before = count_existing_images(identity_dir)
        stats.existing_after = stats.existing_before
        all_stats[identity] = stats

    # PASS 1: Coverage (ensure every identity has at least 1 image)
    run_pass(
        identities=identities,
        pass_name="PASS 1 (Coverage)",
        pass_target=1,
        target=args.target,
        face_app=face_app,
        cache=cache,
        rate_limiter=rate_limiter,
        max_candidates=args.max_candidates,
        max_downloads=args.max_downloads_per_run,
        force=args.force,
        all_stats=all_stats,
    )

    # PASS 2: Reliability (fill to target)
    if args.target > 1:
        run_pass(
            identities=identities,
            pass_name="PASS 2 (Reliability)",
            pass_target=args.target,
            target=args.target,
            face_app=face_app,
            cache=cache,
            rate_limiter=rate_limiter,
            max_candidates=args.max_candidates,
            max_downloads=args.max_downloads_per_run,
            force=False,  # Never force in pass 2
            all_stats=all_stats,
        )

    # Generate and save report
    global_stats = generate_report(all_stats, args.target)
    save_report(all_stats, global_stats, args.target)
    print_summary(global_stats, args.target)

    print("\nDone.")


if __name__ == "__main__":
    main()
