#!/usr/bin/env python3
"""
stats_celeb.py

Prints basic statistics about the celebrity co-appearance graph.

Loads:
  - celebs/celeb_graph.gpickle (pickled NetworkX Graph)

Outputs:
  - Nodes, edges
  - Connected components count and sizes
  - Largest component size
  - Top nodes by degree
  - Top edges by weight (#photos)
  - Optional: average shortest path length within largest component
"""

from __future__ import annotations

import pickle
from typing import List, Tuple

import networkx as nx


GRAPH_PATH = "celebs/celeb_graph.gpickle"
TOP_K = 10


def _load_graph(path: str) -> nx.Graph:
    with open(path, "rb") as f:
        G = pickle.load(f)
    if not isinstance(G, nx.Graph):
        raise TypeError(f"Loaded object is not a NetworkX Graph: {type(G)}")
    return G


def main() -> int:
    G = _load_graph(GRAPH_PATH)

    num_nodes = G.number_of_nodes()
    num_edges = G.number_of_edges()

    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    comp_sizes = [len(c) for c in comps]
    largest_comp = comps[0] if comps else set()

    print("=== Celebrity Graph Stats ===")
    print(f"Graph file: {GRAPH_PATH}")
    print(f"Nodes: {num_nodes}")
    print(f"Edges: {num_edges}")
    print(f"Connected components: {len(comps)}")
    print(f"Component sizes (desc): {comp_sizes}")
    print(f"Largest component size: {len(largest_comp)}")

    # Top nodes by degree
    degrees: List[Tuple[str, int]] = sorted(G.degree, key=lambda x: x[1], reverse=True)
    print(f"\n=== Top {TOP_K} Nodes by Degree ===")
    for name, deg in degrees[:TOP_K]:
        print(f"{name}: {deg}")

    # Top edges by weight
    weighted_edges: List[Tuple[str, str, int]] = []
    for u, v, data in G.edges(data=True):
        w = data.get("weight", 0)
        try:
            w = int(w)
        except Exception:
            w = 0
        weighted_edges.append((u, v, w))

    weighted_edges.sort(key=lambda x: x[2], reverse=True)
    print(f"\n=== Top {TOP_K} Edges by Weight (#photos) ===")
    for u, v, w in weighted_edges[:TOP_K]:
        print(f"{u} <-> {v}: {w}")

    # Optional: average shortest path length inside largest component
    if len(largest_comp) >= 2:
        H = G.subgraph(largest_comp).copy()
        try:
            asp = nx.average_shortest_path_length(H)
            print("\n=== Largest Component Connectivity ===")
            print(f"Average shortest path length (largest component): {asp:.3f}")
        except Exception as e:
            print("\n=== Largest Component Connectivity ===")
            print(f"Average shortest path length: (skipped) {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
