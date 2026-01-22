import os
import cv2
import pickle
import json
import numpy as np
from insightface.app import FaceAnalysis

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INGEST_DIR = os.path.join(BASE_DIR, 'data', 'ingest')
ARTIFACTS_DIR = os.path.join(BASE_DIR, 'artifacts')
UNKNOWN_REGISTRY_PATH = os.path.join(ARTIFACTS_DIR, 'unknown_registry.pkl')
OUTPUT_DIR = os.path.join(ARTIFACTS_DIR, 'unknown_crops')
INDEX_OUTPUT_PATH = os.path.join(OUTPUT_DIR, 'index.json')

MODEL_NAME = 'buffalo_l'
DET_SIZE = (640, 640)

def load_pickle(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return None

def normalize_embedding(emb):
    norm = np.linalg.norm(emb)
    if norm == 0:
        return emb
    return emb / norm

def main():
    print("=== Exporting Unknown Crops ===")
    
    # 1. Load Registry
    registry = load_pickle(UNKNOWN_REGISTRY_PATH)
    if not registry:
        print(f"No registry found at {UNKNOWN_REGISTRY_PATH}")
        return

    identities = registry.get('identities', {})
    if not identities:
        print("No unknown identities found in registry.")
        return

    print(f"Found {len(identities)} unknown records.")

    # 2. Setup Output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 3. Initialize InsightFace (for re-detection)
    app = FaceAnalysis(name=MODEL_NAME, providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=DET_SIZE)

    crop_index = {}
    
    count_exported = 0
    count_failed = 0

    # 4. Process Each Unknown
    for unknown_id, data in identities.items():
        evidence_files = data.get('evidence', [])
        target_embeddings = data.get('embeddings', [])
        
        if not evidence_files or not target_embeddings:
            print(f"Skipping {unknown_id}: missing evidence or embedding.")
            count_failed += 1
            continue

        # Since currently we only have 1 evidence per ID (no clustering yet)
        img_filename = evidence_files[0]
        target_emb = target_embeddings[0] # The raw embedding stored in registry
        
        img_path = os.path.join(INGEST_DIR, img_filename)
        if not os.path.exists(img_path):
            print(f"Skipping {unknown_id}: image {img_filename} not found.")
            count_failed += 1
            continue

        # Load and Detect
        img = cv2.imread(img_path)
        if img is None:
            count_failed += 1
            continue
            
        faces = app.get(img)
        if not faces:
            print(f"Warning: No faces found in {img_filename} during re-detection for {unknown_id}.")
            count_failed += 1
            continue

        # Find the matching face
        # Compare embeddings
        best_sim = -1.0
        best_face = None
        best_idx = -1

        target_emb_norm = normalize_embedding(np.array(target_emb))

        for i, face in enumerate(faces):
            if hasattr(face, 'embedding'):
                curr_emb_norm = normalize_embedding(face.embedding)
                sim = np.dot(target_emb_norm, curr_emb_norm)
                if sim > best_sim:
                    best_sim = sim
                    best_face = face
                    best_idx = i

        # Threshold check? Usually re-detection on same image is near 1.0
        # If < 0.8 something is weird (different model params?), but we take the best one.
        if best_face is None:
            count_failed += 1
            continue

        # Crop
        bbox = best_face.bbox.astype(int)
        x1, y1, x2, y2 = bbox
        
        # Pad slightly? Or exact crop? Exact crop is safer for inspection.
        # Ensure bounds
        h, w, _ = img.shape
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)

        if x2 <= x1 or y2 <= y1:
            count_failed += 1
            continue

        crop = img[y1:y2, x1:x2]
        
        # Save
        out_filename = f"{unknown_id}_{img_filename}_face{best_idx}.jpg"
        out_path = os.path.join(OUTPUT_DIR, out_filename)
        cv2.imwrite(out_path, crop)

        crop_index[out_filename] = {
            'unknown_id': unknown_id,
            'source_image': img_filename,
            'bbox': [int(b) for b in bbox],
            're_detection_score': float(best_sim)
        }
        count_exported += 1

    # 5. Save Index
    with open(INDEX_OUTPUT_PATH, 'w') as f:
        json.dump(crop_index, f, indent=2)

    print(f"Exported {count_exported} crops to {OUTPUT_DIR}")
    print(f"Failed: {count_failed}")

if __name__ == "__main__":
    main()
