import os
import requests
import json
import time
import argparse
import urllib.parse
import cv2
import numpy as np
import insightface
from insightface.app import FaceAnalysis

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INGEST_DIR = os.path.join(BASE_DIR, 'data', 'ingest')
REJECTED_DIR = os.path.join(BASE_DIR, 'artifacts', 'rejected_ingest')
CACHE_PATH = os.path.join(BASE_DIR, 'artifacts', 'wiki_group_cache.json')

MODEL_NAME = 'buffalo_l'
DET_SIZE = (640, 640)

DEFAULT_PAIRS = [
    # Politics
    ("Barack Obama", "Joe Biden"),
    ("Joe Biden", "Kamala Harris"),
    ("Donald Trump", "JD Vance"),
    ("Bill Clinton", "Hillary Clinton"),
    # Entertainment
    ("Taylor Swift", "Travis Kelce"),
    ("Beyonce", "Jay-Z"),
    # Sports
    ("Stephen Curry", "Klay Thompson"),
    ("Stephen Curry", "Draymond Green"),
    ("LeBron James", "Kevin Durant"),
    # Marvel
    ("Chris Evans", "Scarlett Johansson"),
    ("Chris Evans", "Robert Downey Jr"),
    ("Chris Hemsworth", "Mark Ruffalo")
]

USER_AGENT = "GeminiCLI/1.0 (bot)"

def get_wiki_search_url(query):
    base_url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "generator": "search",
        "gsrnamespace": "6", # File namespace
        "gsrsearch": query,
        "gsrlimit": "20",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "format": "json"
    }
    return base_url + "?" + urllib.parse.urlencode(params)

def download_image(url, save_path):
    try:
        response = requests.get(url, stream=True, headers={"User-Agent": USER_AGENT}, timeout=10)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            return True
    except Exception as e:
        print(f"Failed download {url}: {e}")
    return False

def main():
    parser = argparse.ArgumentParser(description="Download group photos from Wikimedia.")
    parser.add_argument("--per-pair", type=int, default=4, help="Target images per pair")
    parser.add_argument("--max-candidates", type=int, default=50, help="Max candidates to check per pair")
    parser.add_argument("--only", type=str, help="Comma-separated pair names e.g. 'Barack Obama,Joe Biden'")
    parser.add_argument("--dry-run", action='store_true', help="Do not download")
    args = parser.parse_args()

    # Setup directories
    os.makedirs(INGEST_DIR, exist_ok=True)
    os.makedirs(REJECTED_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)

    # Load Cache
    cache = {}
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, 'r') as f:
                cache = json.load(f)
        except:
            pass

    # Initialize FaceAnalysis
    print("Initializing InsightFace...")
    app = FaceAnalysis(name=MODEL_NAME, providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=DET_SIZE)

    # Determine Pairs
    target_pairs = DEFAULT_PAIRS
    if args.only:
        # crude parse
        parts = args.only.split(',')
        if len(parts) == 2:
            target_pairs = [(parts[0].strip(), parts[1].strip())]
        else:
            print("Invalid --only format. Use 'Person A,Person B'")
            return

    stats = {
        'pairs_attempted': 0,
        'images_accepted': 0,
        'images_rejected': 0,
        'pairs_zero_success': []
    }

    for p1, p2 in target_pairs:
        stats['pairs_attempted'] += 1
        pair_key = f"{p1}_{p2}"
        print(f"\nProcessing Pair: {p1} & {p2}")
        
        # Search Queries
        queries = [
            f"{p1} {p2}",
            f"{p1} with {p2}",
            f"{p1} and {p2}"
        ]
        
        candidates = []
        
        # Fetch Candidates (with caching)
        for q in queries:
            if q in cache:
                candidates.extend(cache[q])
            else:
                url = get_wiki_search_url(q)
                try:
                    time.sleep(1) # Rate limit
                    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        pages = data.get('query', {}).get('pages', {})
                        results = []
                        for pid, page in pages.items():
                            if 'imageinfo' in page:
                                info = page['imageinfo'][0]
                                if 'url' in info:
                                    results.append(info['url'])
                        
                        cache[q] = results
                        candidates.extend(results)
                    elif resp.status_code == 429:
                        print("Rate limit hit (429). Sleeping 10s...")
                        time.sleep(10)
                except Exception as e:
                    print(f"Search error for '{q}': {e}")
        
        # Deduplicate
        candidates = list(set(candidates))
        print(f"Found {len(candidates)} candidates.")
        
        accepted_count = 0
        
        for i, img_url in enumerate(candidates):
            if accepted_count >= args.per_pair:
                break
            if i >= args.max_candidates:
                break
                
            # Construct Filename
            # e.g. Barack_Obama_Joe_Biden_wiki1.jpg
            safe_p1 = p1.replace(" ", "_")
            safe_p2 = p2.replace(" ", "_")
            # Extract extension
            ext = img_url.split('.')[-1].lower()
            if ext not in ['jpg', 'jpeg', 'png']:
                continue
                
            filename = f"{safe_p1}_{safe_p2}_wiki{i}.{ext}"
            save_path = os.path.join(INGEST_DIR, filename)
            
            # Check if file exists (skip if so, counts as accepted? No, maybe we want to verify it)
            if os.path.exists(save_path):
                # Assume if it exists it was accepted before?
                # But maybe we want to run detection again?
                # Let's just load it.
                pass
            else:
                # Download
                if args.dry_run:
                    print(f"[Dry Run] Would download {img_url} to {filename}")
                    accepted_count += 1
                    continue
                
                success = download_image(img_url, save_path)
                if not success:
                    continue
            
            # Validate
            img = cv2.imread(save_path)
            if img is None:
                os.remove(save_path)
                continue
                
            faces = app.get(img)
            if len(faces) >= 2:
                print(f"  [ACCEPTED] {filename} ({len(faces)} faces)")
                accepted_count += 1
                stats['images_accepted'] += 1
            else:
                # Reject
                print(f"  [REJECTED] {filename} ({len(faces)} faces)")
                # Move to rejected
                rej_path = os.path.join(REJECTED_DIR, filename)
                os.rename(save_path, rej_path)
                stats['images_rejected'] += 1

        if accepted_count == 0:
            stats['pairs_zero_success'].append(pair_key)

    # Save Cache
    with open(CACHE_PATH, 'w') as f:
        json.dump(cache, f)

    # Summary
    print("\n=== Download Summary ===")
    print(f"Pairs Attempted:     {stats['pairs_attempted']}")
    print(f"Images Accepted:     {stats['images_accepted']}")
    print(f"Images Rejected:     {stats['images_rejected']}")
    print(f"Pairs with 0 added:  {stats['pairs_zero_success']}")
    print("========================")

if __name__ == "__main__":
    main()
