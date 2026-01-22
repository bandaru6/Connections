# demo_celeb.py
# Phase 4: CLI to query connections between two celebrities

#!/usr/bin/env python3
"""
query_celeb.py

CLI query tool for the celebrity co-appearance graph.

Loads:
  - celebs/celeb_graph.gpickle (pickled NetworkX Graph)

Supports:
  python src/celeb/query_celeb.py "Person A" "Person B" [--mode hops|strongest]

Outputs:
  - path length (hops)
  - chain of names
  - hop-by-hop evidence:
      * edge weight (# supporting photos)
      * list of image filenames (evidence)

Modes:
  - hops (default): fewest hops via shortest path (unweighted BFS)
  - strongest: prefers stronger edges by minimizing sum(1/weight) via Dijkstra

Error handling:
  - Missing graph file
  - Missing names with close-match suggestions
  - Disconnected nodes (no path)
"""

from __future__ import annotations

import argparse
import difflib
import pickle
import sys
from typing import List, Tuple

import networkx as nx


GRAPH_PATH = "celebs/celeb_graph.gpickle"


def _load_graph(path: str) -> nx.Graph:
    try:
        with open(path, "rb") as f:
            G = pickle.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Graph file not found: {path}. Run build_graph_celeb.py first."
        )
    if not isinstance(G, nx.Graph):
        raise TypeError(f"Loaded object is not a NetworkX Graph: {type(G)}")
    return G


def _suggest_names(G: nx.Graph, name: str, k: int = 5) -> List[str]:
    # NetworkX nodes can be any hashable; in our case they are strings.
    nodes = [n for n in G.nodes if isinstance(n, str)]
    return difflib.get_close_matches(name, nodes, n=k, cutoff=0.6)


def _require_node(G: nx.Graph, name: str) -> str:
    if name in G:
        return name
    suggestions = _suggest_names(G, name)
    msg = f'Name "{name}" not found in graph.'
    if suggestions:
        msg += " Did you mean: " + ", ".join(f'"{s}"' for s in suggestions) + " ?"
    raise ValueError(msg)


def _edge_evidence(G: nx.Graph, u: str, v: str) -> Tuple[int, List[str]]:
    data = G.get_edge_data(u, v) or {}
    weight = int(data.get("weight", 0))
    images = data.get("images", [])
    if not isinstance(images, list):
        images = [str(images)]
    images = [str(x) for x in images]
    return weight, images


def _strongest_path(G: nx.Graph, src: str, dst: str) -> List[str]:
    # Cost is inverse of evidence strength. Stronger edges (higher weight) = lower cost.
    def cost(u: str, v: str, data: dict) -> float:
        w = data.get("weight", 0)
        try:
            w = int(w)
        except Exception:
            w = 0
        return 1.0 / max(w, 1)

    return nx.dijkstra_path(G, src, dst, weight=cost)


def _print_path(G: nx.Graph, path: List[str]) -> None:
    print("\n=== Connection Path ===")
    print(f"Hops: {len(path) - 1}")
    print("Chain:", " -> ".join(path))

    print("\n=== Evidence per Hop ===")
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        w, imgs = _edge_evidence(G, u, v)
        print(f"\n{i+1}. {u}  <->  {v}")
        print(f"   weight (#photos): {w}")
        if imgs:
            # keep it readable
            for img in imgs:
                print(f"   - {img}")
        else:
            print("   - (no images stored)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("person_a", type=str, help="Source person name (exact)")
    parser.add_argument("person_b", type=str, help="Target person name (exact)")
    parser.add_argument(
        "--mode",
        type=str,
        default="hops",
        choices=["hops", "strongest"],
        help="Path selection: fewest hops (BFS) or strongest evidence (Dijkstra over 1/weight).",
    )
    args = parser.parse_args()

    G = _load_graph(GRAPH_PATH)

    src = _require_node(G, args.person_a)
    dst = _require_node(G, args.person_b)

    # Fast fail if disconnected
    if not nx.has_path(G, src, dst):
        src_comp = nx.node_connected_component(G, src)
        dst_comp = nx.node_connected_component(G, dst)
        print("\nNo path found (disconnected components).")
        print(f'Component size for "{src}": {len(src_comp)}')
        print(f'Component size for "{dst}": {len(dst_comp)}')
        return 2

    if args.mode == "hops":
        path = nx.shortest_path(G, src, dst)
    else:
        path = _strongest_path(G, src, dst)

    _print_path(G, path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
