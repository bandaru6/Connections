#!/usr/bin/env python3
"""
build_graph_celeb.py

Builds a weighted evidence graph from an edge evidence CSV.

Input:
  - celebs/edges.csv
    Columns: person_a, person_b, image

Output:
  - celebs/celeb_graph.gpickle

Graph model:
  - Undirected graph
  - Node: person name (string)
  - Edge attributes:
      * weight: int (number of photos supporting this relationship)
      * images: list[str] (filenames of supporting images)

Integrity checks:
  - For every edge: weight == len(images)
  - Prints basic graph stats:
      * #nodes
      * #edges
      * #connected components
      * size of largest component
"""

from __future__ import annotations

import csv
import os
import sys
from typing import Dict, List, Tuple
import pickle


import networkx as nx


EDGES_CSV = os.path.join("celebs", "edges.csv")
OUT_GRAPH = os.path.join("celebs", "celeb_graph.gpickle")


def _read_edges(path: str) -> List[Tuple[str, str, str]]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"edges.csv not found: {path}")

    rows: List[Tuple[str, str, str]] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        expected = {"person_a", "person_b", "image"}
        if reader.fieldnames is None or set(reader.fieldnames) != expected:
            raise ValueError(
                f"edges.csv must have columns {sorted(expected)}, got: {reader.fieldnames}"
            )

        for i, row in enumerate(reader, start=2):  # header is line 1
            a = (row.get("person_a") or "").strip()
            b = (row.get("person_b") or "").strip()
            img = (row.get("image") or "").strip()

            if not a or not b or not img:
                raise ValueError(f"Invalid row at line {i}: {row}")

            rows.append((a, b, img))

    return rows


def build_graph() -> int:
    edges = _read_edges(EDGES_CSV)

    G = nx.Graph()

    for a, b, img in edges:
        if G.has_edge(a, b):
            G[a][b]["weight"] += 1
            G[a][b]["images"].append(img)
        else:
            G.add_edge(a, b, weight=1, images=[img])

    # Integrity checks
    for u, v, data in G.edges(data=True):
        w = data.get("weight")
        imgs = data.get("images")
        if not isinstance(w, int) or w < 1:
            raise ValueError(f"Bad weight on edge ({u}, {v}): {w}")
        if not isinstance(imgs, list):
            raise ValueError(f"Bad images list on edge ({u}, {v}): {imgs}")
        if w != len(imgs):
            raise ValueError(
                f"Integrity check failed for ({u}, {v}): weight={w} but len(images)={len(imgs)}"
            )

    # Stats
    num_nodes = G.number_of_nodes()
    num_edges = G.number_of_edges()
    components = list(nx.connected_components(G))
    num_components = len(components)
    largest_component_size = max((len(c) for c in components), default=0)

    print("=== Graph Build Summary ===")
    print(f"Input edges: {EDGES_CSV}")
    print(f"Output graph: {OUT_GRAPH}")
    print(f"Nodes: {num_nodes}")
    print(f"Edges: {num_edges}")
    print(f"Connected components: {num_components}")
    print(f"Largest component size: {largest_component_size}")

    os.makedirs(os.path.dirname(OUT_GRAPH), exist_ok=True)
    with open(OUT_GRAPH, "wb") as f:
        pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)


    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(build_graph())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
