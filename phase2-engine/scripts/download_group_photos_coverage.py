import os
import sys
import json
import argparse
import time
import requests
import hashlib
import cv2
import numpy as np
import shutil
import random
from datetime import datetime
from insightface.app import FaceAnalysis

# --- Configuration ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_DIR = os.path.join(BASE_DIR, 'data', 'profiles')
INGEST_DIR = os.path.join(BASE_DIR, 'data', 'ingest')
REJECTED_DIR = os.path.join(INGEST_DIR, 'rejected')
ARTIFACTS_DIR = os.path.join(BASE_DIR, 'artifacts')
REPORT_PATH = os.path.join(ARTIFACTS_DIR, 'group_download_report.json')

MODEL_NAME = 'buffalo_l'
DET_SIZE = (640, 640)
USER_AGENT = "GeminiCLI/1.0 (bot)"

# --- Data Definitions ---
ALL_IDENTITIES = [
    "Alexandria Ocasio-Cortez", "Allen Iverson", "Andre Iguodala", "Angelina Jolie", "Anthony Edwards", 
    "Ariana Grande", "Barack Obama", "Barack Obama Sr", "Benedict Cumberbatch", "Beyonce", "Bill Clinton", 
    "Billie Eilish", "Brad Pitt", "Brie Larson", "Cardi B", "Chadwick Boseman", "Chris Evans", 
    "Chris Hemsworth", "Chris Rock", "Cristiano Ronaldo", "Donald Trump", "Drake", "Draymond Green", 
    "Dua Lipa", "Dwayne Johnson", "Dwyane Wade", "Elon Musk", "Emma Stone", "Gavin Newsom", 
    "Giannis Antetokounmpo", "Hailee Steinfeld", "Hillary Clinton", "J Cole", "JD Vance", "Jay-Z", 
    "Jaylen Brown", "Jayson Tatum", "Jeff Bezos", "Jennifer Lawrence", "Jill Biden", "Joe Biden", 
    "Joel Embiid", "Justin Bieber", "Kamala Harris", "Kanye West", "Kendrick Lamar", "Kevin Durant", 
    "Kevin Hart", "Klay Thompson", "Kobe Bryant", "Larry Bird", "LeBron James", "Leonardo DiCaprio", 
    "Lionel Messi", "Luka Doncic", "Magic Johnson", "Margot Robbie", "Mark Ruffalo", "Mark Zuckerberg", 
    "Michael B Jordan", "Michael Jackson", "Michael Jordan", "Michelle Obama", "Mike Pence", 
    "Mitch McConnell", "Nancy Pelosi", "Natalie Portman", "Nicki Minaj", "Nikola Jokic", "Oprah Winfrey", 
    "Paul Rudd", "Post Malone", "Rihanna", "Robert Downey Jr", "Roger Federer", "Ron DeSantis", 
    "Ryan Gosling", "Sam Altman", "Scarlett Johansson", "Serena Williams", "Shaquille O'Neal", 
    "Stephen Curry", "Sundar Pichai", "Sydney Sweeney", "Taylor Swift", "The Weeknd", "Tiger Woods", 
    "Tim Cook", "Tim Duncan", "Timothee Chalamet", "Tom Brady", "Tom Hiddleston", "Tom Holland", 
    "Travis Scott", "Will Smith", "Zendaya"
]

CLUSTERS = {
    "NBA-A": ["Stephen Curry", "Klay Thompson", "Draymond Green", "Andre Iguodala", "Kevin Durant"],
    "NBA-B": ["LeBron James", "Kevin Durant", "Stephen Curry", "Giannis Antetokounmpo", "Luka Doncic", "Nikola Jokic", "Joel Embiid", "Jayson Tatum", "Jaylen Brown", "Anthony Edwards"],
    "NBA-C": ["Michael Jordan", "Magic Johnson", "Larry Bird", "Kobe Bryant", "Shaquille O'Neal", "Tim Duncan", "Dwyane Wade"],
    "Sports-other": ["Lionel Messi", "Cristiano Ronaldo", "Serena Williams", "Roger Federer", "Tiger Woods"],
    "Marvel": ["Robert Downey Jr", "Chris Evans", "Scarlett Johansson", "Chris Hemsworth", "Mark Ruffalo", "Brie Larson", "Chadwick Boseman", "Natalie Portman", "Tom Holland", "Zendaya", "Tom Hiddleston", "Benedict Cumberbatch", "Paul Rudd"],
    "Hollywood": ["Leonardo DiCaprio", "Brad Pitt", "Angelina Jolie", "Emma Stone", "Jennifer Lawrence", "Ryan Gosling", "Margot Robbie", "Will Smith", "Kevin Hart", "Oprah Winfrey", "Sydney Sweeney", "Hailee Steinfeld", "Dwayne Johnson"],
    "Music": ["Taylor Swift", "Ariana Grande", "Justin Bieber", "Billie Eilish", "Dua Lipa", "Rihanna", "Beyonce", "Jay-Z", "Drake", "The Weeknd", "Nicki Minaj", "Cardi B", "Post Malone", "Travis Scott", "Kanye West", "Kendrick Lamar", "J Cole", "Michael Jackson"],
    "US Politics-Dem": ["Barack Obama", "Michelle Obama", "Joe Biden", "Jill Biden", "Kamala Harris", "Hillary Clinton", "Bill Clinton", "Nancy Pelosi", "Mitch McConnell", "Alexandria Ocasio-Cortez", "Gavin Newsom"],
    "US Politics-GOP": ["Donald Trump", "Mike Pence", "JD Vance", "Ron DeSantis", "Mitch McConnell"],
    "Tech": ["Elon Musk", "Jeff Bezos", "Mark Zuckerberg", "Tim Cook", "Sundar Pichai", "Sam Altman"]
}

# --- Utilities ---

def ensure_dirs():
    os.makedirs(INGEST_DIR, exist_ok=True)
    os.makedirs(REJECTED_DIR, exist_ok=True)
    for reason in ['low_res', 'aspect_ratio', 'split_screen', 'text_heavy', 'too_few_faces', 'faces_too_far', 'download_fail']:
        os.makedirs(os.path.join(REJECTED_DIR, reason), exist_ok=True)

def get_file_hash(content):
    return hashlib.md5(content).hexdigest()

# --- Search Providers ---

def search_serpapi(query, api_key, num=10):
    print(f"  [SerpAPI] Searching: {query}")
    params = {
        "engine": "google_images",
        "q": query,
        "api_key": api_key,
        "num": num,
        "safe": "active"
    }
    try:
        resp = requests.get("https://serpapi.com/search", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        results = []
        if "images_results" in data:
            for item in data["images_results"]:
                if "original" in item:
                    results.append(item["original"])
        return results
    except Exception as e:
        print(f"  [SerpAPI] Error: {e}")
        return []

def search_bing(query, api_key, endpoint, num=10):
    print(f"  [Bing] Searching: {query}")
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {"q": query, "count": num, "safeSearch": "Strict"}
    try:
        resp = requests.get(endpoint, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        results = []
        if "value" in data:
            for item in data["value"]:
                if "contentUrl" in item:
                    results.append(item["contentUrl"])
        return results
    except Exception as e:
        print(f"  [Bing] Error: {e}")
        return []

def search_brave(query, api_key, num=10):
    print(f"  [Brave] Searching: {query}")
    headers = {"X-Subscription-Token": api_key, "Accept": "application/json"}
    params = {"q": query, "count": num, "safesearch": "strict"}
    try:
        url = "https://api.search.brave.com/res/v1/images/search"
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        results = []
        if "results" in data:
            for item in data["results"]:
                # Brave response structure can vary, checking standard props
                if "properties" in item and "url" in item["properties"]:
                    results.append(item["properties"]["url"])
                elif "url" in item:
                    results.append(item["url"])
        return results
    except Exception as e:
        print(f"  [Brave] Error: {e}")
        return []

# --- Validations ---

def is_split_screen(img):
    # Detect strong vertical seam near center
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    
    # Analyze center 20%
    start_col = int(w * 0.4)
    end_col = int(w * 0.6)
    center_roi = gray[:, start_col:end_col]
    
    # Compute horizontal gradients (vertical edges)
    sobelx = cv2.Sobel(center_roi, cv2.CV_64F, 1, 0, ksize=3)
    abs_sobelx = np.abs(sobelx)
    
    # Sum absolute gradients down each column
    col_sums = np.sum(abs_sobelx, axis=0)
    
    # If the max gradient sum is significantly higher than median, it's a seam
    if len(col_sums) == 0: return False
    
    max_val = np.max(col_sums)
    median_val = np.median(col_sums)
    
    # Threshold heuristic: seam is usually very distinct
    if median_val == 0: median_val = 1
    ratio = max_val / median_val
    
    return ratio > 3.5  # Heuristic threshold

def is_text_heavy(img):
    # Check top 20% and bottom 20% for high edge density
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    
    top_band = gray[0:int(h*0.2), :]
    bottom_band = gray[int(h*0.8):h, :]
    
    def get_edge_density(roi):
        edges = cv2.Canny(roi, 100, 200)
        non_zero = cv2.countNonZero(edges)
        area = roi.shape[0] * roi.shape[1]
        if area == 0: return 0
        return non_zero / area

    top_density = get_edge_density(top_band)
    bottom_density = get_edge_density(bottom_band)
    
    # Threshold: text creates lots of edges
    return top_density > 0.15 or bottom_density > 0.15

def check_faces(app, img, min_faces):
    faces = app.get(img)
    if len(faces) < min_faces:
        return False, "too_few_faces", faces
    
    # Check proximity
    h, w, _ = img.shape
    centers = []
    for f in faces:
        cx = (f.bbox[0] + f.bbox[2]) / 2
        cy = (f.bbox[1] + f.bbox[3]) / 2
        centers.append((cx, cy))
    
    # Find minimum distance between any pair
    min_dist = float('inf')
    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            c1 = centers[i]
            c2 = centers[j]
            dist = np.sqrt((c1[0]-c2[0])**2 + (c1[1]-c2[1])**2)
            if dist < min_dist:
                min_dist = dist
    
    if min_dist > (0.45 * w):
        return False, "faces_too_far", faces
        
    return True, "ok", faces

# --- Main Logic ---

def main():
    parser = argparse.ArgumentParser(description="Coverage-first group photo downloader")
    parser.add_argument("--max-downloads", type=int, default=80)
    parser.add_argument("--per-cluster", type=int, default=12)
    parser.add_argument("--min-faces", type=int, default=2)
    parser.add_argument("--provider", choices=['serpapi', 'bing', 'brave', 'manual', 'auto'], default='auto')
    parser.add_argument("--manual-url-file", type=str)
    parser.add_argument("--dry-run", action='store_true')
    args = parser.parse_args()

    ensure_dirs()
    
    # 1. Setup Provider
    provider = args.provider
    api_key = None
    bing_endpoint = os.environ.get("BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/images/search")

    if provider == 'auto':
        if os.environ.get("SERPAPI_KEY"):
            provider = 'serpapi'
            api_key = os.environ.get("SERPAPI_KEY")
        elif os.environ.get("BING_SEARCH_KEY"):
            provider = 'bing'
            api_key = os.environ.get("BING_SEARCH_KEY")
        elif os.environ.get("BRAVE_SEARCH_KEY"):
            provider = 'brave'
            api_key = os.environ.get("BRAVE_SEARCH_KEY")
        else:
            if args.manual_url_file and os.path.exists(args.manual_url_file):
                provider = 'manual'
            else:
                print("Error: No API keys found and no manual URL file.")
                sys.exit(1)
    else:
        if provider == 'serpapi': api_key = os.environ.get("SERPAPI_KEY")
        elif provider == 'bing': api_key = os.environ.get("BING_SEARCH_KEY")
        elif provider == 'brave': api_key = os.environ.get("BRAVE_SEARCH_KEY")
        
        if provider != 'manual' and not api_key:
            print(f"Error: Missing API key for {provider}")
            sys.exit(1)

    print(f"Provider: {provider.upper()}")

    # 2. Init InsightFace
    print("Initializing InsightFace...")
    app = FaceAnalysis(name=MODEL_NAME, providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=DET_SIZE)

    # 3. Valid Identities (folders exist)
    valid_identities = [id for id in ALL_IDENTITIES if os.path.isdir(os.path.join(PROFILES_DIR, id))]
    print(f"Valid Identities: {len(valid_identities)}")

    # 4. State Tracking
    covered_identities = set()
    accepted_images = [] # List of {filename, claimed_ids}
    rejection_stats = {}
    
    # Helper to check coverage
    def get_uncovered():
        return [id for id in valid_identities if id not in covered_identities]

    total_downloads = 0

    # 5. Manual Mode
    manual_urls = []
    if provider == 'manual':
        print("Running Manual Mode from file...")
        if args.manual_url_file and os.path.exists(args.manual_url_file):
            with open(args.manual_url_file, 'r') as f:
                manual_urls = json.load(f)
        else:
            print("Error: Provider manual selected but file missing or empty.")
            sys.exit(1)

    # 6. Cluster Loop
    cluster_names = list(CLUSTERS.keys())
    random.shuffle(cluster_names)

    for cluster_name in cluster_names:
        if total_downloads >= args.max_downloads: break
        
        members = [m for m in CLUSTERS[cluster_name] if m in valid_identities]
        if len(members) < 2: continue

        # Prioritize queries that target UNCOVERED members
        uncovered_members = [m for m in members if m not in covered_identities]
        
        print(f"\nProcessing Cluster: {cluster_name}")
        print(f"  Uncovered members: {len(uncovered_members)} / {len(members)}")

        # Generate Queries
        queries = []
        
        # 1. Group queries (good for covering many)
        label = cluster_name.split('-')[0] # NBA-A -> NBA
        queries.append((f"{label} group photo", members[:5])) # Claim top 5
        
        # 2. Pair queries focusing on uncovered
        # If we have uncovered members, pair them with a popular (covered) member or another uncovered one
        target_list = uncovered_members if uncovered_members else members
        # Shuffle to avoid same pairs every time
        random.shuffle(target_list)
        
        pairs_attempted = 0
        for m1 in target_list:
            if pairs_attempted > 3: break
            # Pick m2
            possible_m2 = [m for m in members if m != m1]
            if not possible_m2: continue
            m2 = random.choice(possible_m2)
            
            # Templates
            if "Politics" in cluster_name:
                q_str = f"{m1} {m2} debate stage"
            elif "NBA" in cluster_name or "Sports" in cluster_name:
                q_str = f"{m1} {m2} team photo"
            elif "Marvel" in cluster_name or "Hollywood" in cluster_name:
                q_str = f"{m1} {m2} red carpet photo"
            else:
                q_str = f"{m1} {m2} photo event"
            
            queries.append((q_str, [m1, m2]))
            pairs_attempted += 1

        # Execute Queries for this cluster
        images_in_cluster = 0
        for q_str, claimed_ids in queries:
            if images_in_cluster >= args.per_cluster: break
            if total_downloads >= args.max_downloads: break
            
            # Search
            urls = []
            if provider == 'serpapi':
                urls = search_serpapi(q_str, api_key)
            elif provider == 'bing':
                urls = search_bing(q_str, api_key, bing_endpoint)
            elif provider == 'brave':
                urls = search_brave(q_str, api_key)
            elif provider == 'manual':
                # naive pop from list
                pass 
            
            if not urls:
                time.sleep(0.5)
                continue

            for url in urls:
                if images_in_cluster >= args.per_cluster: break
                if total_downloads >= args.max_downloads: break
                
                # Download
                try:
                    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=5)
                    if resp.status_code != 200:
                        continue
                    
                    content = resp.content
                    img_hash = get_file_hash(content)
                    
                    # 1. Decode
                    arr = np.frombuffer(content, np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if img is None: # Corrupt
                        continue 
                        
                    h, w, _ = img.shape
                    
                    # 2. Reject: Low Res
                    if min(h, w) < 600:
                        reason = "low_res"
                        if not args.dry_run:
                            with open(os.path.join(REJECTED_DIR, reason, f"{img_hash}.jpg"), 'wb') as f: f.write(content)
                        rejection_stats[reason] = rejection_stats.get(reason, 0) + 1
                        continue

                    # 3. Reject: Aspect Ratio
                    ratio = w / h
                    if ratio > 1.9 or ratio < 0.55:
                        reason = "aspect_ratio"
                        if not args.dry_run:
                            with open(os.path.join(REJECTED_DIR, reason, f"{img_hash}.jpg"), 'wb') as f: f.write(content)
                        rejection_stats[reason] = rejection_stats.get(reason, 0) + 1
                        continue

                    # 4. Reject: Split Screen
                    if is_split_screen(img):
                        reason = "split_screen"
                        if not args.dry_run:
                            with open(os.path.join(REJECTED_DIR, reason, f"{img_hash}.jpg"), 'wb') as f: f.write(content)
                        rejection_stats[reason] = rejection_stats.get(reason, 0) + 1
                        continue

                    # 5. Reject: Text Heavy
                    if is_text_heavy(img):
                        reason = "text_heavy"
                        if not args.dry_run:
                            with open(os.path.join(REJECTED_DIR, reason, f"{img_hash}.jpg"), 'wb') as f: f.write(content)
                        rejection_stats[reason] = rejection_stats.get(reason, 0) + 1
                        continue

                    # 6. InsightFace Check
                    passed_faces, reason, faces = check_faces(app, img, args.min_faces)
                    if not passed_faces:
                        if not args.dry_run:
                            with open(os.path.join(REJECTED_DIR, reason, f"{img_hash}.jpg"), 'wb') as f: f.write(content)
                        rejection_stats[reason] = rejection_stats.get(reason, 0) + 1
                        continue

                    # ACCEPTED
                    # Filename: group_<cluster>_<slug>_<hash>.jpg
                    slug = cluster_name.replace(" ", "")
                    filename = f"group_{slug}_{img_hash[:10]}.jpg"
                    save_path = os.path.join(INGEST_DIR, filename)
                    
                    if not args.dry_run:
                        with open(save_path, 'wb') as f: f.write(content)
                        print(f"    [ACCEPTED] {filename} (Claimed: {claimed_ids})")
                    else:
                        print(f"    [DRY RUN] {filename} (Claimed: {claimed_ids})")

                    total_downloads += 1
                    images_in_cluster += 1
                    
                    # Update Coverage
                    for cid in claimed_ids:
                        if cid in valid_identities:
                            covered_identities.add(cid)
                    
                    accepted_images.append({
                        "filename": filename,
                        "claimed_ids": claimed_ids,
                        "timestamp": datetime.now().isoformat()
                    })

                except Exception as e:
                    # print(f"    Download error: {e}")
                    pass

    # 7. Write Report
    report = {
        "identities_total": len(valid_identities),
        "identities_covered_claimed": list(covered_identities),
        "identities_uncovered_claimed": get_uncovered(),
        "accepted_count": len(accepted_images),
        "rejected_count": sum(rejection_stats.values()),
        "rejection_reason_histogram": rejection_stats,
        "accepted_images": accepted_images
    }
    
    with open(REPORT_PATH, 'w') as f:
        json.dump(report, f, indent=2)

    print("\n=== Download Complete ===")
    print(f"Accepted: {report['accepted_count']}")
    print(f"Rejected: {report['rejected_count']}")
    print(f"Covered (Claimed): {len(covered_identities)} / {len(valid_identities)}")
    print(f"Report saved to: {REPORT_PATH}")

if __name__ == "__main__":
    main()