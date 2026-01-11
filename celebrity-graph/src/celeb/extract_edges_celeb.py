# extract_celebs.py
# Phase 2: face detection + embedding extraction + edge list generation

#!/usr/bin/env python3
"""
extract_edges_celeb.py

Reads a hand-labeled manifest of which people appear in each image and produces an
edge evidence CSV.

Input:
  - celebs/manifest.json  (image filename -> list of person names)

Validations:
  - Each referenced image exists in celebs/raw/
  - Each image has >= 2 people
  - People names are non-empty strings

Output:
  - celebs/edges.csv  (overwritten each run)
    Columns: person_a,person_b,image
    Each row is one evidence event: (person_a, person_b) co-appeared in image.

Determinism:
  - Images processed in sorted filename order
  - For each image, people list is normalized (trimmed) and sorted
  - Pairs are generated in deterministic order and canonicalized (a < b)
"""

from __future__ import annotations

import csv
import json
import os
import sys
from itertools import combinations
from typing import Dict, List, Tuple


MANIFEST_PATH = os.path.join("celebs", "manifest.json")
RAW_DIR = os.path.join("celebs", "raw")
OUT_CSV = os.path.join("celebs", "edges.csv")


def _load_manifest(path: str) -> Dict[str, List[str]]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Manifest not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("manifest.json must be a JSON object mapping image -> [people]")
    return data


def _normalize_people(people: List[str]) -> List[str]:
    if not isinstance(people, list):
        raise ValueError("People entry must be a list of strings.")
    cleaned: List[str] = []
    for p in people:
        if not isinstance(p, str):
            raise ValueError(f"Person name must be a string, got: {type(p)}")
        name = p.strip()
        if not name:
            continue
        cleaned.append(name)

    # Remove duplicates while keeping determinism: sort + unique
    cleaned_sorted = sorted(cleaned)
    unique: List[str] = []
    prev = None
    for name in cleaned_sorted:
        if name != prev:
            unique.append(name)
        prev = name
    return unique


def _canonical_pair(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a < b else (b, a)


def extract_edges() -> int:
    manifest = _load_manifest(MANIFEST_PATH)

    images_processed = 0
    skipped: List[Tuple[str, str]] = []  # (image, reason)
    rows: List[Tuple[str, str, str]] = []

    for image_name in sorted(manifest.keys()):
        people_raw = manifest[image_name]

        image_path = os.path.join(RAW_DIR, image_name)
        if not os.path.exists(image_path):
            skipped.append((image_name, f"missing file at {image_path}"))
            continue

        try:
            people = _normalize_people(people_raw)
        except Exception as e:
            skipped.append((image_name, f"invalid people list: {e}"))
            continue

        if len(people) < 2:
            skipped.append((image_name, "needs at least 2 people"))
            continue

        images_processed += 1

        # Deterministic: people is already sorted, combinations yields deterministic order
        for a, b in combinations(people, 2):
            u, v = _canonical_pair(a, b)
            rows.append((u, v, image_name))

    # Deterministic write: rows are already deterministic because we iterate in sorted image order
    # and pairs are produced in sorted order from combinations(people,2).
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["person_a", "person_b", "image"])
        writer.writerows(rows)

    print("=== Edge Extraction Summary ===")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Raw dir:  {RAW_DIR}")
    print(f"Output:   {OUT_CSV}")
    print(f"Images processed: {images_processed}")
    print(f"Images skipped:   {len(skipped)}")
    if skipped:
        print("Skipped details:")
        for img, reason in skipped:
            print(f"  - {img}: {reason}")
    print(f"Edge rows written (excluding header): {len(rows)}")

    return 0 if not skipped else 0  # still succeed; skipped is expected during iteration


if __name__ == "__main__":
    try:
        raise SystemExit(extract_edges())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise

