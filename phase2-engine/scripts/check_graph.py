import pickle
import networkx as nx
import os

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS_DIR = os.path.join(BASE_DIR, 'artifacts')
GRAPH_PATH = os.path.join(ARTIFACTS_DIR, 'celeb_graph_phase2.gpickle')

def main():
    if not os.path.exists(GRAPH_PATH):
        print(f"Error: Graph not found at {GRAPH_PATH}")
        return

    with open(GRAPH_PATH, 'rb') as f:
        G = pickle.load(f)

    print(f"Loaded graph with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")
    
    # Get all edges with data
    edges = []
    for u, v, data in G.edges(data=True):
        edges.append((u, v, data['weight'], data['images']))

    # Sort by weight descending
    edges.sort(key=lambda x: x[2], reverse=True)

    print("\nTop 10 Strongest Edges:")
    print("-" * 60)
    for i, (u, v, weight, images) in enumerate(edges[:10]):
        print(f"{i+1}. {u} -- {v} (Weight: {weight})")
        print(f"   Evidence: {images[:2]} ...") # Show first 2 images
    print("-" * 60)

    # Show some Unknown nodes if any
    unknowns = [n for n in G.nodes() if "UNKNOWN" in n]
    print(f"\nTotal Unknown Nodes in Graph: {len(unknowns)}")
    if unknowns:
        print(f"Example Unknowns: {unknowns[:5]}")

if __name__ == "__main__":
    main()

