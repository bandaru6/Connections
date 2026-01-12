#!/usr/bin/env bash
set -euo pipefail

echo "=== Running Celebrity Graph Demo ==="
echo

echo "[1/4] Extract edges (manifest -> edges.csv)"
python src/celeb/extract_edges_celeb.py
echo

echo "[2/4] Build graph (edges.csv -> celeb_graph.gpickle)"
python src/celeb/build_graph_celeb.py
echo

echo "[3/4] Graph stats"
python src/celeb/stats_celeb.py
echo

echo "[4/4] Sample queries"
echo
echo ">>> Query 1 (direct): Barack Obama -> LeBron James"
python src/celeb/query_celeb.py "Barack Obama" "LeBron James"
echo

echo ">>> Query 2 (multi-hop): Barack Obama -> Taylor Swift"
python src/celeb/query_celeb.py "Barack Obama" "Taylor Swift"
echo

echo ">>> Query 3 (expected failure): Scarlett Johansson -> Joe Biden"
python src/celeb/query_celeb.py "Scarlett Johansson" "Joe Biden" || true
echo

echo "=== Demo complete ==="
