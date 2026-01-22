import argparse
import os
import pickle
import sys
import numpy as np
import cv2
from insightface.app import FaceAnalysis

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS_DIR = os.path.join(BASE_DIR, 'artifacts')
INDEX_PATH = os.path.join(ARTIFACTS_DIR, 'profile_index.pkl')

MODEL_NAME = 'buffalo_l'
DET_SIZE = (640, 640)

def load_index(path):
    if not os.path.exists(path):
        print(f"Error: Profile index not found at {path}")
        sys.exit(1)
    with open(path, 'rb') as f:
        return pickle.load(f)

def normalize_embedding(emb):
    norm = np.linalg.norm(emb)
    if norm == 0:
        return emb
    return emb / norm

def compute_cosine_similarity(feat1, feat2):
    # Assumes feat1 and feat2 are already normalized
    return np.dot(feat1, feat2)

def main():
    parser = argparse.ArgumentParser(description="Match faces in a single photo against profile index.")
    parser.add_argument("--image", required=True, help="Path to the image file")
    args = parser.parse_args()

    image_path = args.image

    # 1. Load Profile Index
    try:
        profile_index = load_index(INDEX_PATH)
    except Exception as e:
        print(f"Error loading index: {e}")
        sys.exit(1)

    # Pre-process index: flatten structure for simpler iteration if needed, 
    # or just keep as dict. We need to compute max score per identity.
    # Let's verify we have embeddings.
    
    # We will iterate through identities. To speed up, we can normalize all reference embeddings once.
    normalized_index = {}
    for identity, data in profile_index.items():
        embeddings = data.get('embeddings', [])
        if embeddings:
            norm_embeddings = [normalize_embedding(np.array(e)) for e in embeddings]
            normalized_index[identity] = norm_embeddings

    if not normalized_index:
        print("Error: No active identities found in index.")
        sys.exit(1)

    # 2. Initialize InsightFace
    try:
        app = FaceAnalysis(name=MODEL_NAME, providers=['CPUExecutionProvider'])
        app.prepare(ctx_id=0, det_size=DET_SIZE)
    except Exception as e:
        print(f"Error initializing FaceAnalysis: {e}")
        sys.exit(1)

    # 3. Load Image
    if not os.path.exists(image_path):
        print(f"Error: Image file not found at {image_path}")
        sys.exit(1)

    img = cv2.imread(image_path)
    if img is None:
        print(f"Error: Failed to load image {image_path}")
        sys.exit(1)

    # 4. Detect Faces
    faces = app.get(img)
    
    total_faces = len(faces)
    assigned_identities = set()
    unknown_count = 0

    print(f"Processing {image_path}")
    print(f"Detected {total_faces} faces.")
    print("-" * 60)

    # 5. Match Each Face
    for i, face in enumerate(faces):
        if not hasattr(face, 'embedding'):
            print(f"Face {i}: No embedding found. Skipping.")
            continue
        
        face_emb = normalize_embedding(face.embedding)

        # Compute max score for each identity
        scores = []
        for identity, ref_embeddings in normalized_index.items():
            # similarity between face_emb and all ref_embeddings for this identity
            # dot product of face_emb (1, 512) and ref_embeddings (N, 512).T -> (1, N)
            # Since vectors are 1D arrays, we can do list comp or matrix mul.
            # Matrix mul is faster.
            refs_matrix = np.array(ref_embeddings) # (N, 512)
            sims = np.dot(refs_matrix, face_emb)   # (N,)
            max_score = np.max(sims)
            scores.append((identity, max_score))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)

        best_identity = scores[0][0]
        best_score = scores[0][1]
        
        second_best_identity = "None"
        second_best_score = 0.0
        
        if len(scores) > 1:
            second_best_identity = scores[1][0]
            second_best_score = scores[1][1]

        # Decision Policy
        # Accept top1 only if:
        # top1_score >= 0.45 AND (top1_score - top2_score) >= 0.05
        
        decision = "UNKNOWN"
        is_match = False
        
        if best_score >= 0.45:
            if (best_score - second_best_score) >= 0.05:
                decision = best_identity
                is_match = True
        
        if is_match:
            assigned_identities.add(decision)
        else:
            unknown_count += 1

        print(f"Face {i}:")
        print(f"  Best Match:    {best_identity} ({best_score:.4f})")
        print(f"  Second Best:   {second_best_identity} ({second_best_score:.4f})")
        print(f"  Decision:      {decision}")
        print("-" * 60)

    # 6. Summary
    print("Summary:")
    print(f"Total Faces Detected:       {total_faces}")
    print(f"Unique Identities Assigned: {len(assigned_identities)}")
    print(f"Unknown Faces Count:        {unknown_count}")

if __name__ == "__main__":
    main()
