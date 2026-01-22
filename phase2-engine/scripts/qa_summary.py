import os
import pickle
import json
import networkx as nx

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS_DIR = os.path.join(BASE_DIR, 'artifacts')
INGEST_DIR = os.path.join(BASE_DIR, 'data', 'ingest')

INDEX_PATH = os.path.join(ARTIFACTS_DIR, 'profile_index.pkl')
GRAPH_PATH = os.path.join(ARTIFACTS_DIR, 'celeb_graph_phase2.gpickle')
LOG_PATH = os.path.join(ARTIFACTS_DIR, 'ingest_log.jsonl')
UNKNOWN_REGISTRY_PATH = os.path.join(ARTIFACTS_DIR, 'unknown_registry.pkl')

def load_pickle(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'rb') as f:
            return pickle.load(f)
    except Exception:
        return default

def main():
    print("=== QA Summary ===")

    # 1. Profile Stats
    profile_index = load_pickle(INDEX_PATH)
    if profile_index:
        total_identities = len(profile_index)
        active_count = sum(1 for d in profile_index.values() if d.get('counts', {}).get('accepted', 0) > 0)
        total_embeddings = sum(len(d.get('embeddings', [])) for d in profile_index.values())
        print(f"Profiles:             {total_identities} identities ({active_count} active)")
        print(f"Profile Embeddings:   {total_embeddings}")
    else:
        print("Profiles:             Not found or empty")

    # 2. Ingest Folder Stats
    if os.path.exists(INGEST_DIR):
        ingest_files = [f for f in os.listdir(INGEST_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        print(f"Ingest Folder Images: {len(ingest_files)}")
    else:
        print("Ingest Folder:        Not found")

    # 3. Log Stats
    processed_count = 0
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, 'r') as f:
                for line in f:
                    if line.strip():
                        processed_count += 1
        except:
            pass
    print(f"Processed in Log:     {processed_count}")

    # 4. Graph Stats
    graph = load_pickle(GRAPH_PATH)
    if graph:
        print(f"Graph Nodes:          {graph.number_of_nodes()}")
        print(f"Graph Edges:          {graph.number_of_edges()}")
    else:
        print("Graph:                Not found")

    # 5. Unknown Stats
    registry = load_pickle(UNKNOWN_REGISTRY_PATH)
    if registry:
        unknown_count = len(registry.get('identities', {}))
        print(f"Unknowns in Registry: {unknown_count}")
    else:
        print("Unknown Registry:     Not found")
    
    print("==================")

if __name__ == "__main__":
    main()
