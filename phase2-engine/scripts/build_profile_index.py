import os
import cv2
import numpy as np
import pickle
import json
import insightface
from insightface.app import FaceAnalysis
from typing import Dict, List, Any
import sys

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_DIR = os.path.join(BASE_DIR, 'data', 'profiles')
ARTIFACTS_DIR = os.path.join(BASE_DIR, 'artifacts')
INDEX_PATH = os.path.join(ARTIFACTS_DIR, 'profile_index.pkl')
REPORT_PATH = os.path.join(ARTIFACTS_DIR, 'profile_index_report.json')

MODEL_NAME = 'buffalo_l'
DET_SIZE = (640, 640)

def main():
    print(f"Initializing FaceAnalysis with model: {MODEL_NAME}")
    # Initialize InsightFace
    app = FaceAnalysis(name=MODEL_NAME, providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=DET_SIZE)

    # Data structures
    profile_index: Dict[str, Dict[str, Any]] = {}
    report_data = {
        'active_identities': [],
        'inactive_identities': [],
        'per_identity_stats': {},
        'summary': {}
    }

    # Counters
    total_identities = 0
    total_accepted_embeddings = 0
    total_rejected_no_face = 0
    total_rejected_multi_face = 0
    total_rejected_load_error = 0

    # Verify directories
    if not os.path.exists(PROFILES_DIR):
        print(f"Error: Profiles directory not found at {PROFILES_DIR}")
        return

    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    # 1. Scan Identities (Deterministic Sort)
    identities = sorted([d for d in os.listdir(PROFILES_DIR) if os.path.isdir(os.path.join(PROFILES_DIR, d))])
    total_identities = len(identities)

    print(f"Found {total_identities} identities. Starting scan...")

    for identity_name in identities:
        identity_path = os.path.join(PROFILES_DIR, identity_name)
        
        # Identity specific storage
        id_embeddings = []
        id_source_images = []
        id_counts = {
            'accepted': 0,
            'rejected_no_face': 0,
            'rejected_multi_face': 0,
            'rejected_load_error': 0
        }

        # 2. Scan Images (Deterministic Sort)
        image_files = sorted([f for f in os.listdir(identity_path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
        
        for img_file in image_files:
            img_path = os.path.join(identity_path, img_file)
            
            try:
                img = cv2.imread(img_path)
                if img is None:
                    id_counts['rejected_load_error'] += 1
                    total_rejected_load_error += 1
                    continue

                faces = app.get(img)

                if len(faces) == 0:
                    id_counts['rejected_no_face'] += 1
                    total_rejected_no_face += 1
                elif len(faces) > 1:
                    id_counts['rejected_multi_face'] += 1
                    total_rejected_multi_face += 1
                else:
                    # Exactly 1 face
                    face = faces[0]
                    # Ensure embedding exists and is correct shape
                    if hasattr(face, 'embedding') and face.embedding.shape == (512,):
                        id_embeddings.append(face.embedding)
                        id_source_images.append(img_file)
                        id_counts['accepted'] += 1
                        total_accepted_embeddings += 1
                    else:
                         # Should not happen with buffalo_l but good to be safe
                         id_counts['rejected_load_error'] += 1 # categorization fallback
                         total_rejected_load_error += 1

            except Exception as e:
                print(f"Error processing {img_path}: {e}")
                id_counts['rejected_load_error'] += 1
                total_rejected_load_error += 1

        # Store in index if we have relevant data or just to track the identity exists?
        # Requirement: "A dict keyed by identity (folder name)..."
        # Requirement: "ACTIVE identity... has >=1 accepted embedding"
        # We will store the entry regardless, but classify as inactive if empty.
        
        profile_index[identity_name] = {
            'embeddings': id_embeddings,
            'source_images': id_source_images,
            'counts': id_counts,
            'metadata': {
                'model_pack_name': MODEL_NAME,
                'embedding_dim': 512,
                'det_size': DET_SIZE
            }
        }

        # Update report stats
        report_data['per_identity_stats'][identity_name] = id_counts
        if id_counts['accepted'] > 0:
            report_data['active_identities'].append(identity_name)
        else:
            report_data['inactive_identities'].append(identity_name)

        # Optional: Print progress every now and then
        # print(f"Processed {identity_name}: {id_counts['accepted']} accepted.")

    # Save Pickle
    print(f"Saving profile index to {INDEX_PATH}...")
    with open(INDEX_PATH, 'wb') as f:
        pickle.dump(profile_index, f)

    # Save Report
    report_data['summary'] = {
        'total_identities_scanned': total_identities,
        'active_identities_count': len(report_data['active_identities']),
        'inactive_identities_count': len(report_data['inactive_identities']),
        'total_accepted_embeddings': total_accepted_embeddings,
        'total_rejected_no_face': total_rejected_no_face,
        'total_rejected_multi_face': total_rejected_multi_face,
        'total_rejected_load_error': total_rejected_load_error
    }

    print(f"Saving report to {REPORT_PATH}...")
    with open(REPORT_PATH, 'w') as f:
        json.dump(report_data, f, indent=2)

    # Print Summary
    print("\n=== Build Profile Index Summary ===")
    print(f"Total Identities Scanned: {report_data['summary']['total_identities_scanned']}")
    print(f"Active Identities:        {report_data['summary']['active_identities_count']}")
    print(f"Inactive Identities:      {report_data['summary']['inactive_identities_count']}")
    print(f"Total Accepted Embeddings:{report_data['summary']['total_accepted_embeddings']}")
    print(f"Rejected (No Face):       {report_data['summary']['total_rejected_no_face']}")
    print(f"Rejected (Multi Face):    {report_data['summary']['total_rejected_multi_face']}")
    print(f"Rejected (Load Error):    {report_data['summary']['total_rejected_load_error']}")
    print("===================================")

if __name__ == "__main__":
    main()
