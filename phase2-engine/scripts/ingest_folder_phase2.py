import os
import sys
import pickle
import json
import numpy as np
import cv2
import networkx as nx
import itertools
import argparse
from datetime import datetime
from insightface.app import FaceAnalysis

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INGEST_DIR = os.path.join(BASE_DIR, 'data', 'ingest')
ARTIFACTS_DIR = os.path.join(BASE_DIR, 'artifacts')

INDEX_PATH = os.path.join(ARTIFACTS_DIR, 'profile_index.pkl')
UNKNOWN_REGISTRY_PATH = os.path.join(ARTIFACTS_DIR, 'unknown_registry.pkl')
GRAPH_PATH = os.path.join(ARTIFACTS_DIR, 'celeb_graph_phase2.gpickle')
LOG_PATH = os.path.join(ARTIFACTS_DIR, 'ingest_log.jsonl')

MODEL_NAME = 'buffalo_l'
DET_SIZE = (640, 640)

def normalize_embedding(emb):
    norm = np.linalg.norm(emb)
    if norm == 0:
        return emb
    return emb / norm

def load_pickle(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        print(f"Warning: Failed to load {path}, using default. Error: {e}")
        return default

def save_pickle(data, path):
    with open(path, 'wb') as f:
        pickle.dump(data, f)

def main():
    parser = argparse.ArgumentParser(description="Ingest images from data/ingest folder.")
    parser.add_argument("--rebuild", action="store_true", help="Clear all previous ingest artifacts (graph, log, registry) and rebuild from scratch.")
    args = parser.parse_args()

    # 1. Load Resources
    print("Loading resources...")
    profile_index = load_pickle(INDEX_PATH, default={})
    if not profile_index:
        print("Error: Profile index empty or missing.")
        return

    # Normalize profile embeddings for speed
    normalized_profiles = {}
    for identity, data in profile_index.items():
        embeddings = data.get('embeddings', [])
        if embeddings:
            norm_embeddings = [normalize_embedding(np.array(e)) for e in embeddings]
            normalized_profiles[identity] = norm_embeddings

    processed_files = set()
    unknown_registry = {'next_id': 1, 'identities': {}}
    celeb_graph = nx.Graph()

    if args.rebuild:
        print("!!! REBUILD MODE: Clearing artifacts !!!")
        if os.path.exists(GRAPH_PATH):
            os.remove(GRAPH_PATH)
        if os.path.exists(LOG_PATH):
            os.remove(LOG_PATH)
        if os.path.exists(UNKNOWN_REGISTRY_PATH):
            os.remove(UNKNOWN_REGISTRY_PATH)
        # processed_files, unknown_registry, celeb_graph remain empty/default
    else:
        # Load Unknown Registry
        unknown_registry = load_pickle(UNKNOWN_REGISTRY_PATH, default={'next_id': 1, 'identities': {}})
        
        # Load Graph
        celeb_graph = load_pickle(GRAPH_PATH, default=nx.Graph())

        # Load Processed Files from Log
        if os.path.exists(LOG_PATH):
            try:
                with open(LOG_PATH, 'r') as f:
                    for line in f:
                        try:
                            record = json.loads(line)
                            processed_files.add(record['image'])
                        except:
                            pass
            except Exception as e:
                print(f"Warning: Failed to read log file {LOG_PATH}: {e}")

    # Initialize InsightFace
    
    # 2. Scan Ingest Folder
    if not os.path.exists(INGEST_DIR):
        print(f"Error: Ingest directory {INGEST_DIR} not found.")
        return

    image_files = sorted([f for f in os.listdir(INGEST_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
    
    total_images = len(image_files)
    print(f"Found {total_images} images in folder.")

    processed_count = 0
    skipped_count = 0
    already_processed_count = 0
    total_faces_detected = 0
    total_known_matches = 0
    total_unknown_assigned = 0

    # 3. Process Images
    with open(LOG_PATH, 'a') as log_file:
        for img_file in image_files:
            if img_file in processed_files:
                already_processed_count += 1
                continue

            img_path = os.path.join(INGEST_DIR, img_file)
            
            try:
                img = cv2.imread(img_path)
                if img is None:
                    print(f"Error: Failed to load {img_file}")
                    skipped_count += 1
                    continue
                
                faces = app.get(img)
                # Sort faces by bbox x1
                faces.sort(key=lambda x: (x.bbox[0], x.bbox[1]))
                
                num_faces = len(faces)
                total_faces_detected += num_faces
                
                face_assignments = []
                image_identities = set() # For graph update (unique IDs)

                for i, face in enumerate(faces):
                    if not hasattr(face, 'embedding'):
                        continue
                    
                    face_emb = normalize_embedding(face.embedding)
                    
                    # Match against KNOWN profiles
                    scores = []
                    for identity, ref_embeddings in normalized_profiles.items():
                        refs_matrix = np.array(ref_embeddings)
                        sims = np.dot(refs_matrix, face_emb)
                        max_score = np.max(sims)
                        scores.append((identity, max_score))
                    
                    scores.sort(key=lambda x: x[1], reverse=True)
                    
                    best_id = scores[0][0] if scores else "None"
                    best_score = scores[0][1] if scores else 0.0
                    second_id = scores[1][0] if len(scores) > 1 else "None"
                    second_score = scores[1][1] if len(scores) > 1 else 0.0

                    # Decision Policy
                    decision = "UNKNOWN"
                    is_known = False
                    if best_score >= 0.45 and (best_score - second_score) >= 0.05:
                        decision = best_id
                        is_known = True
                        total_known_matches += 1
                    else:
                        # Assign NEW UNKNOWN ID
                        # "Stable" means we mint a new ID and persist it in registry.
                        # We do NOT cluster unknowns in this step (conservative).
                        current_unknown_num = unknown_registry['next_id']
                        unknown_id = f"UNKNOWN_{current_unknown_num:04d}"
                        unknown_registry['next_id'] += 1
                        
                        # Store in registry
                        unknown_registry['identities'][unknown_id] = {
                            'embeddings': [face.embedding], # Store original embedding (not normalized? usually raw is better for storage)
                            'evidence': [img_file]
                        }
                        
                        decision = unknown_id
                        total_unknown_assigned += 1
                    
                    image_identities.add(decision)
                    
                    # Log data
                    face_assignments.append({
                        "face_index": i,
                        "bbox": [int(b) for b in face.bbox],
                        "best": {"id": best_id, "score": float(best_score)},
                        "second": {"id": second_id, "score": float(second_score)},
                        "decision": decision
                    })

                # Update Graph
                edges_added = 0
                sorted_ids = sorted(list(image_identities))
                # Add nodes
                for node in sorted_ids:
                    if not celeb_graph.has_node(node):
                        celeb_graph.add_node(node)

                # Add edges (clique)
                for u, v in itertools.combinations(sorted_ids, 2):
                    if celeb_graph.has_edge(u, v):
                        celeb_graph[u][v]['weight'] += 1
                        celeb_graph[u][v]['images'].append(img_file)
                    else:
                        celeb_graph.add_edge(u, v, weight=1, images=[img_file])
                    edges_added += 1

                # Log Record
                log_record = {
                    "image": img_file,
                    "faces_detected": num_faces,
                    "assignments": face_assignments,
                    "unique_ids_for_graph": sorted_ids,
                    "edges_added_or_updated": edges_added,
                    "timestamp": datetime.now().isoformat()
                }
                log_file.write(json.dumps(log_record) + "\n")
                
                processed_count += 1
                # Checkpoint artifacts periodically or just at end?
                # For safety, one could save every N images, but dataset is small (~30 images).
                # Save at end is fine.

            except Exception as e:
                print(f"Error processing {img_file}: {e}")
                skipped_count += 1

    # 4. Save Artifacts
    print("Saving artifacts...")
    save_pickle(unknown_registry, UNKNOWN_REGISTRY_PATH)
    save_pickle(celeb_graph, GRAPH_PATH)

    # 5. Summary
    num_nodes = celeb_graph.number_of_nodes()
    num_edges = celeb_graph.number_of_edges()
    num_components = nx.number_connected_components(celeb_graph)

    print("\n=== Ingest Summary ===")
    print(f"Images Processed:       {processed_count}")
    print(f"Images Skipped:         {skipped_count}")
    print(f"Total Faces Detected:   {total_faces_detected}")
    print(f"Total Known Matches:    {total_known_matches}")
    print(f"Total Unknown Assigned: {total_unknown_assigned}")
    print(f"Graph Nodes:            {num_nodes}")
    print(f"Graph Edges:            {num_edges}")
    print(f"Connected Components:   {num_components}")
    print("======================")

if __name__ == "__main__":
    main()
