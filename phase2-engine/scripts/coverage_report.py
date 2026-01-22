import os
import json
import pickle
import collections
from typing import Dict, Any

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS_DIR = os.path.join(BASE_DIR, 'artifacts')

INDEX_PATH = os.path.join(ARTIFACTS_DIR, 'profile_index.pkl')
LOG_PATH = os.path.join(ARTIFACTS_DIR, 'ingest_log.jsonl')
REPORT_OUTPUT_PATH = os.path.join(ARTIFACTS_DIR, 'coverage_report.json')

def load_pickle(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return None

def main():
    print("=== Generating Coverage Report ===")

    # 1. Load Profile Index
    if not os.path.exists(INDEX_PATH):
        print(f"Error: Profile index not found at {INDEX_PATH}.")
        print("Please run scripts/build_profile_index.py first.")
        return

    profile_index = load_pickle(INDEX_PATH)
    if not profile_index:
        return

    # 2. Analyze Profiles
    all_identities = set(profile_index.keys())
    active_identities = set()
    inactive_identities = set()

    for identity, data in profile_index.items():
        if data.get('counts', {}).get('accepted', 0) > 0:
            active_identities.add(identity)
        else:
            inactive_identities.add(identity)

    print(f"Total Profiles: {len(all_identities)}")
    print(f"Active Profiles: {len(active_identities)}")

    # 3. Analyze Ingest Log
    seen_in_matches = collections.Counter()
    
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        assignments = record.get('assignments', [])
                        for assignment in assignments:
                            decision = assignment.get('decision')
                            # Check if decision is a known identity (not UNKNOWN_xxxx and not "UNKNOWN")
                            if decision and not decision.startswith("UNKNOWN"):
                                seen_in_matches[decision] += 1
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        # Defensive parsing
                        continue
        except Exception as e:
            print(f"Error reading log {LOG_PATH}: {e}")

    # 4. Compute Coverage Stats
    identities_seen = set(seen_in_matches.keys())
    identities_never_seen = active_identities - identities_seen

    # Only consider active identities for "never seen" (inactive ones can't be seen by definition of matching, usually)
    # But strictly speaking, "identities in profiles" includes all.
    # If an inactive identity was somehow matched (unlikely), it would show up in seen_in_matches.
    
    top_20 = seen_in_matches.most_common(20)

    # 5. Generate Report
    report = {
        'total_identities': len(all_identities),
        'active_identities_count': len(active_identities),
        'inactive_identities_count': len(inactive_identities),
        'identities_seen_count': len(identities_seen),
        'identities_never_seen_count': len(identities_never_seen),
        'identities_seen_list': sorted(list(identities_seen)),
        'identities_never_seen_list': sorted(list(identities_never_seen)),
        'top_20_frequent': {k: v for k, v in top_20}
    }

    # 6. Save and Print
    with open(REPORT_OUTPUT_PATH, 'w') as f:
        json.dump(report, f, indent=2)

    print("\n--- Coverage Summary ---")
    print(f"Total Identities:      {report['total_identities']}")
    print(f"Active (with images):  {report['active_identities_count']}")
    print(f"Inactive (no images):  {report['inactive_identities_count']}")
    print(f"Seen in Matches:       {report['identities_seen_count']}")
    print(f"Never Seen:            {report['identities_never_seen_count']}")
    print("\nTop 5 Most Frequent:")
    for name, count in top_20[:5]:
        print(f"  {name}: {count}")
    print(f"\nFull report saved to {REPORT_OUTPUT_PATH}")

if __name__ == "__main__":
    main()
