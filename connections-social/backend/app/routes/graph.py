"""Graph read API endpoints for querying the social graph.

Caching strategy
────────────────
/graph/summary and /graph/neighbors are cached in Redis for 60s and 30s
respectively.  These are the highest-frequency read endpoints and each
requires multiple JOINs across the edges + persons + edge_evidence tables.

Cache is invalidated on any successful ingest operation so that the graph
reflects the latest data within one TTL window at worst.  If Redis is
unavailable, all requests fall through to PostgreSQL transparently.
"""

import logging
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, HTTPException, Query

from app.db import get_cursor
from app.cache import (
    get_cached,
    set_cached,
    cache_key_summary,
    cache_key_neighbors,
    SUMMARY_TTL,
    NEIGHBORS_TTL,
)
from app.observability.metrics import track_cache_hit, track_cache_miss

logger = logging.getLogger(__name__)
router = APIRouter()


def get_evidence_filenames(cur, person_a_id: str, person_b_id: str, limit: int = 3) -> List[str]:
    """Get up to `limit` evidence filenames for an edge."""
    cur.execute(
        """
        SELECT u.image_path
        FROM edge_evidence ee
        JOIN uploads u ON ee.upload_id = u.id
        WHERE ee.person_a_id = %s AND ee.person_b_id = %s
        ORDER BY ee.created_at DESC
        LIMIT %s
        """,
        (person_a_id, person_b_id, limit)
    )
    return [row['image_path'] for row in cur.fetchall()]


@router.get("/summary")
def graph_summary(include_unknown: bool = Query(False, description="Include UNKNOWN persons in counts and top_edges")):
    """
    Get a summary of the social graph.

    Returns:
    - persons_total: total persons (respects include_unknown filter for display)
    - known_persons_total: count of known (non-UNKNOWN) persons
    - unknown_persons_total: count of UNKNOWN_* persons
    - edges_total: total edges (respects include_unknown filter)
    - edges_known_only_total: edges between known persons only
    - top_edges: top 10 edges by weight (respects include_unknown filter)
    - recent_uploads: 10 most recent processed images
    """
    cache_key = cache_key_summary(include_unknown)
    cached = get_cached(cache_key)
    if cached is not None:
        track_cache_hit("graph_summary")
        return cached

    track_cache_miss("graph_summary")

    try:
        with get_cursor() as cur:
            # Known persons count
            cur.execute("SELECT COUNT(*) as cnt FROM persons WHERE name NOT LIKE 'UNKNOWN_%'")
            known_persons_total = cur.fetchone()['cnt']

            # Unknown persons count
            cur.execute("SELECT COUNT(*) as cnt FROM persons WHERE name LIKE 'UNKNOWN_%'")
            unknown_persons_total = cur.fetchone()['cnt']

            # Total persons (respects filter for display purposes)
            persons_total = known_persons_total + (unknown_persons_total if include_unknown else 0)

            # Edges between known persons only (always computed)
            cur.execute("""
                SELECT COUNT(*) as cnt
                FROM edges e
                JOIN persons pa ON e.person_a_id = pa.id
                JOIN persons pb ON e.person_b_id = pb.id
                WHERE pa.name NOT LIKE 'UNKNOWN_%'
                  AND pb.name NOT LIKE 'UNKNOWN_%'
            """)
            edges_known_only_total = cur.fetchone()['cnt']

            # Total edges (all edges)
            cur.execute("SELECT COUNT(*) as cnt FROM edges")
            edges_all_total = cur.fetchone()['cnt']

            # edges_total respects include_unknown filter
            edges_total = edges_all_total if include_unknown else edges_known_only_total

            # Top edges (respects include_unknown)
            if include_unknown:
                cur.execute("""
                    SELECT e.person_a_id, e.person_b_id, pa.name as person_a, pb.name as person_b, e.weight
                    FROM edges e
                    JOIN persons pa ON e.person_a_id = pa.id
                    JOIN persons pb ON e.person_b_id = pb.id
                    ORDER BY e.weight DESC, pa.name, pb.name
                    LIMIT 10
                """)
            else:
                cur.execute("""
                    SELECT e.person_a_id, e.person_b_id, pa.name as person_a, pb.name as person_b, e.weight
                    FROM edges e
                    JOIN persons pa ON e.person_a_id = pa.id
                    JOIN persons pb ON e.person_b_id = pb.id
                    WHERE pa.name NOT LIKE 'UNKNOWN_%'
                      AND pb.name NOT LIKE 'UNKNOWN_%'
                    ORDER BY e.weight DESC, pa.name, pb.name
                    LIMIT 10
                """)

            top_edges = []
            for row in cur.fetchall():
                evidence = get_evidence_filenames(cur, str(row['person_a_id']), str(row['person_b_id']))
                top_edges.append({
                    'person_a': row['person_a'],
                    'person_b': row['person_b'],
                    'weight': row['weight'],
                    'evidence': evidence
                })

            # Recent uploads (from processed_images)
            cur.execute("""
                SELECT filename, processed_at
                FROM processed_images
                ORDER BY processed_at DESC
                LIMIT 10
            """)
            recent_uploads = [
                {
                    'filename': row['filename'],
                    'processed_at': row['processed_at'].isoformat() if row['processed_at'] else None
                }
                for row in cur.fetchall()
            ]

            result = {
                'persons_total': persons_total,
                'known_persons_total': known_persons_total,
                'unknown_persons_total': unknown_persons_total,
                'edges_total': edges_total,
                'edges_known_only_total': edges_known_only_total,
                'top_edges': top_edges,
                'recent_uploads': recent_uploads,
                '_cached': False,
            }
            set_cached(cache_key, {**result, '_cached': True}, SUMMARY_TTL)
            return result

    except Exception as e:
        logger.error(f"Graph summary failed: {e}")
        raise HTTPException(status_code=500, detail=f"Graph summary failed: {e}")


@router.get("/neighbors")
def graph_neighbors(
    person: str = Query(..., description="Person name to find neighbors for"),
    limit: int = Query(25, ge=1, le=100, description="Max neighbors to return"),
    include_unknown: bool = Query(False, description="Include UNKNOWN neighbors (unmatched faces)")
):
    """
    Get neighbors of a person in the social graph.

    Returns neighbors sorted by weight descending, then by neighbor name.
    Each neighbor includes up to 3 evidence filenames.
    """
    cache_key = cache_key_neighbors(person, include_unknown, limit)
    cached = get_cached(cache_key)
    if cached is not None:
        track_cache_hit("graph_neighbors")
        return cached

    track_cache_miss("graph_neighbors")

    try:
        with get_cursor() as cur:
            # Check if person exists
            cur.execute("SELECT id, name FROM persons WHERE name = %s", (person,))
            person_row = cur.fetchone()

            if not person_row:
                raise HTTPException(status_code=404, detail=f"Person '{person}' not found")

            person_id = str(person_row['id'])
            person_name = person_row['name']

            # If person is UNKNOWN and include_unknown=false, return error
            if not include_unknown and person_name.startswith('UNKNOWN_'):
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot query UNKNOWN person '{person_name}' with include_unknown=false"
                )

            # Find neighbors (person can be in either person_a_id or person_b_id)
            if include_unknown:
                cur.execute("""
                    SELECT
                        CASE
                            WHEN e.person_a_id = %s THEN pb.name
                            ELSE pa.name
                        END as neighbor_name,
                        CASE
                            WHEN e.person_a_id = %s THEN e.person_b_id
                            ELSE e.person_a_id
                        END as neighbor_id,
                        e.person_a_id,
                        e.person_b_id,
                        e.weight
                    FROM edges e
                    JOIN persons pa ON e.person_a_id = pa.id
                    JOIN persons pb ON e.person_b_id = pb.id
                    WHERE e.person_a_id = %s OR e.person_b_id = %s
                    ORDER BY e.weight DESC, neighbor_name
                    LIMIT %s
                """, (person_id, person_id, person_id, person_id, limit))
            else:
                cur.execute("""
                    SELECT
                        CASE
                            WHEN e.person_a_id = %s THEN pb.name
                            ELSE pa.name
                        END as neighbor_name,
                        CASE
                            WHEN e.person_a_id = %s THEN e.person_b_id
                            ELSE e.person_a_id
                        END as neighbor_id,
                        e.person_a_id,
                        e.person_b_id,
                        e.weight
                    FROM edges e
                    JOIN persons pa ON e.person_a_id = pa.id
                    JOIN persons pb ON e.person_b_id = pb.id
                    WHERE (e.person_a_id = %s OR e.person_b_id = %s)
                      AND pa.name NOT LIKE 'UNKNOWN_%%'
                      AND pb.name NOT LIKE 'UNKNOWN_%%'
                    ORDER BY e.weight DESC, neighbor_name
                    LIMIT %s
                """, (person_id, person_id, person_id, person_id, limit))

            neighbors = []
            for row in cur.fetchall():
                evidence = get_evidence_filenames(
                    cur,
                    str(row['person_a_id']),
                    str(row['person_b_id'])
                )
                neighbors.append({
                    'neighbor': row['neighbor_name'],
                    'weight': row['weight'],
                    'evidence': evidence
                })

            result = {
                'person': person_name,
                'neighbors': neighbors,
                '_cached': False,
            }
            set_cached(cache_key, {**result, '_cached': True}, NEIGHBORS_TTL)
            return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Graph neighbors failed: {e}")
        raise HTTPException(status_code=500, detail=f"Graph neighbors failed: {e}")


@router.get("/ego")
def graph_ego(
    person: str = Query(..., description="Center person name for ego network"),
    depth: int = Query(2, ge=1, le=3, description="Depth of neighborhood (1-3 hops)"),
    limit: int = Query(50, ge=1, le=200, description="Max nodes to return"),
    include_unknown: bool = Query(False, description="Include UNKNOWN persons (unmatched faces)")
):
    """
    Get the ego network centered on a person.

    Returns nodes and edges within `depth` hops of the center person.
    The limit applies to total nodes returned (center + neighbors).
    Results are sorted deterministically by name.
    """
    try:
        with get_cursor() as cur:
            # Check if person exists
            cur.execute("SELECT id, name FROM persons WHERE name = %s", (person,))
            person_row = cur.fetchone()

            if not person_row:
                raise HTTPException(status_code=404, detail=f"Person '{person}' not found")

            center_id = str(person_row['id'])
            center_name = person_row['name']

            # If person is UNKNOWN and include_unknown=false, return error
            if not include_unknown and center_name.startswith('UNKNOWN_'):
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot query UNKNOWN person '{center_name}' with include_unknown=false"
                )

            # Load all persons for lookup
            cur.execute("SELECT id, name FROM persons")
            person_lookup: Dict[str, str] = {}  # id -> name
            for row in cur.fetchall():
                person_lookup[str(row['id'])] = row['name']

            # Load all edges
            cur.execute("""
                SELECT person_a_id, person_b_id, weight
                FROM edges
            """)

            # Build adjacency list
            adjacency: Dict[str, List[Tuple[str, int]]] = {}  # person_id -> [(neighbor_id, weight), ...]
            all_edges: List[Tuple[str, str, int]] = []

            for row in cur.fetchall():
                a_id = str(row['person_a_id'])
                b_id = str(row['person_b_id'])
                weight = row['weight']

                a_name = person_lookup.get(a_id, '')
                b_name = person_lookup.get(b_id, '')

                # Skip UNKNOWN edges if not included
                if not include_unknown:
                    if a_name.startswith('UNKNOWN_') or b_name.startswith('UNKNOWN_'):
                        continue

                if a_id not in adjacency:
                    adjacency[a_id] = []
                if b_id not in adjacency:
                    adjacency[b_id] = []

                adjacency[a_id].append((b_id, weight))
                adjacency[b_id].append((a_id, weight))
                all_edges.append((a_id, b_id, weight))

            # BFS to find nodes within depth
            visited: Set[str] = set()
            queue: deque = deque()
            queue.append((center_id, 0))
            visited.add(center_id)

            nodes_in_ego: List[str] = []

            while queue and len(nodes_in_ego) < limit:
                current_id, current_depth = queue.popleft()
                nodes_in_ego.append(current_id)

                if current_depth < depth:
                    neighbors = adjacency.get(current_id, [])
                    # Sort neighbors by name for determinism
                    neighbors_sorted = sorted(
                        neighbors,
                        key=lambda x: person_lookup.get(x[0], '')
                    )
                    for neighbor_id, _ in neighbors_sorted:
                        if neighbor_id not in visited:
                            visited.add(neighbor_id)
                            queue.append((neighbor_id, current_depth + 1))

            # Collect nodes
            ego_node_ids = set(nodes_in_ego[:limit])
            nodes_output = []
            for node_id in sorted(ego_node_ids, key=lambda x: person_lookup.get(x, '')):
                name = person_lookup.get(node_id, 'Unknown')
                nodes_output.append({
                    'name': name,
                    'is_unknown': name.startswith('UNKNOWN_')
                })

            # Collect edges between ego nodes
            edges_output = []
            seen_edges: Set[Tuple[str, str]] = set()

            for a_id, b_id, weight in all_edges:
                if a_id in ego_node_ids and b_id in ego_node_ids:
                    # Ensure consistent ordering
                    edge_key = (min(a_id, b_id), max(a_id, b_id))
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        a_name = person_lookup.get(a_id, 'Unknown')
                        b_name = person_lookup.get(b_id, 'Unknown')
                        # Sort names for consistent output
                        if a_name > b_name:
                            a_name, b_name = b_name, a_name
                        edges_output.append({
                            'source': a_name,
                            'target': b_name,
                            'weight': weight
                        })

            # Sort edges for determinism
            edges_output.sort(key=lambda e: (e['source'], e['target']))

            return {
                'center': center_name,
                'depth': depth,
                'nodes': nodes_output,
                'edges': edges_output
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Graph ego failed: {e}")
        raise HTTPException(status_code=500, detail=f"Graph ego failed: {e}")


@router.get("/path")
def graph_path(
    source: str = Query(..., description="Source person name"),
    target: str = Query(..., description="Target person name"),
    include_unknown: bool = Query(False, description="Include UNKNOWN persons in path")
):
    """
    Find the shortest path between two people using BFS.

    Returns the path as a list of person names and the edges connecting them.
    """
    try:
        with get_cursor() as cur:
            # Check if source exists
            cur.execute("SELECT id, name FROM persons WHERE name = %s", (source,))
            source_row = cur.fetchone()
            if not source_row:
                raise HTTPException(status_code=404, detail=f"Source person '{source}' not found")

            # Check if target exists
            cur.execute("SELECT id, name FROM persons WHERE name = %s", (target,))
            target_row = cur.fetchone()
            if not target_row:
                raise HTTPException(status_code=404, detail=f"Target person '{target}' not found")

            source_id = str(source_row['id'])
            target_id = str(target_row['id'])
            source_name = source_row['name']
            target_name = target_row['name']

            # Check UNKNOWN constraints
            if not include_unknown:
                if source_name.startswith('UNKNOWN_'):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot query UNKNOWN person '{source_name}' with include_unknown=false"
                    )
                if target_name.startswith('UNKNOWN_'):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot query UNKNOWN person '{target_name}' with include_unknown=false"
                    )

            # Same source and target
            if source_id == target_id:
                return {
                    'source': source_name,
                    'target': target_name,
                    'found': True,
                    'path': [source_name],
                    'hops': 0,
                    'edges': []
                }

            # Load all persons for lookup
            cur.execute("SELECT id, name FROM persons")
            person_lookup: Dict[str, str] = {}  # id -> name
            for row in cur.fetchall():
                person_lookup[str(row['id'])] = row['name']

            # Load all edges
            cur.execute("""
                SELECT person_a_id, person_b_id, weight
                FROM edges
            """)

            # Build adjacency list
            adjacency: Dict[str, List[Tuple[str, int]]] = {}  # person_id -> [(neighbor_id, weight), ...]
            edge_weights: Dict[Tuple[str, str], int] = {}  # (a_id, b_id) -> weight

            for row in cur.fetchall():
                a_id = str(row['person_a_id'])
                b_id = str(row['person_b_id'])
                weight = row['weight']

                a_name = person_lookup.get(a_id, '')
                b_name = person_lookup.get(b_id, '')

                # Skip UNKNOWN edges if not included
                if not include_unknown:
                    if a_name.startswith('UNKNOWN_') or b_name.startswith('UNKNOWN_'):
                        continue

                if a_id not in adjacency:
                    adjacency[a_id] = []
                if b_id not in adjacency:
                    adjacency[b_id] = []

                adjacency[a_id].append((b_id, weight))
                adjacency[b_id].append((a_id, weight))

                # Store edge weight (both directions)
                edge_key = (min(a_id, b_id), max(a_id, b_id))
                edge_weights[edge_key] = weight

            # BFS to find shortest path
            visited: Set[str] = set()
            parent: Dict[str, str] = {}  # child_id -> parent_id
            queue: deque = deque()
            queue.append(source_id)
            visited.add(source_id)

            found = False
            while queue:
                current_id = queue.popleft()

                if current_id == target_id:
                    found = True
                    break

                for neighbor_id, _ in adjacency.get(current_id, []):
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        parent[neighbor_id] = current_id
                        queue.append(neighbor_id)

            if not found:
                return {
                    'source': source_name,
                    'target': target_name,
                    'found': False,
                    'path': [],
                    'hops': 0,
                    'edges': []
                }

            # Reconstruct path
            path_ids: List[str] = []
            current = target_id
            while current:
                path_ids.append(current)
                current = parent.get(current)
            path_ids.reverse()

            # Build path names and edges
            path_names = [person_lookup.get(pid, 'Unknown') for pid in path_ids]
            edges_output = []

            for i in range(len(path_ids) - 1):
                a_id = path_ids[i]
                b_id = path_ids[i + 1]
                edge_key = (min(a_id, b_id), max(a_id, b_id))
                weight = edge_weights.get(edge_key, 1)

                a_name = person_lookup.get(a_id, 'Unknown')
                b_name = person_lookup.get(b_id, 'Unknown')

                # Get evidence for this edge
                evidence = get_evidence_filenames(cur, a_id, b_id)
                if not evidence:
                    evidence = get_evidence_filenames(cur, b_id, a_id)

                edges_output.append({
                    'person_a': a_name,
                    'person_b': b_name,
                    'weight': weight,
                    'evidence': evidence
                })

            return {
                'source': source_name,
                'target': target_name,
                'found': True,
                'path': path_names,
                'hops': len(path_names) - 1,
                'edges': edges_output
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Graph path failed: {e}")
        raise HTTPException(status_code=500, detail=f"Graph path failed: {e}")


@router.get("/persons/list")
def list_persons(
    q: Optional[str] = Query(None, description="Search query filter (case-insensitive)"),
    include_unknown: bool = Query(False, description="Include UNKNOWN persons"),
    limit: int = Query(50, ge=1, le=500, description="Max persons to return")
):
    """
    List persons in the graph.
    """
    try:
        with get_cursor() as cur:
            # Base query
            query = "SELECT name FROM persons"
            params = []
            conditions = []

            # Filter unknown
            if not include_unknown:
                conditions.append("name NOT LIKE 'UNKNOWN_%%'")
            
            # Filter by search query
            if q:
                conditions.append("name ILIKE %s")
                params.append(f"%{q}%")
            
            # Assemble query
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY name LIMIT %s"
            params.append(limit)

            cur.execute(query, tuple(params))
            persons = [row['name'] for row in cur.fetchall()]

            return {
                'count': len(persons),
                'persons': persons
            }

    except Exception as e:
        logger.error(f"List persons failed: {e}")
        raise HTTPException(status_code=500, detail=f"List persons failed: {e}")
