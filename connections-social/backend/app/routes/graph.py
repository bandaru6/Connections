"""Graph read API endpoints for querying the social graph."""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.db import get_cursor

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
def graph_summary(include_unknown: bool = Query(True, description="Include UNKNOWN persons in counts and top_edges")):
    """
    Get a summary of the social graph.

    Returns:
    - persons_total: total persons (including UNKNOWNs)
    - unknown_persons_total: count of UNKNOWN_* persons (always reported)
    - edges_total: total edges (respects include_unknown filter)
    - top_edges: top 10 edges by weight (respects include_unknown filter)
    - recent_uploads: 10 most recent processed images
    """
    try:
        with get_cursor() as cur:
            # Total persons (always includes unknowns)
            cur.execute("SELECT COUNT(*) as cnt FROM persons")
            persons_total = cur.fetchone()['cnt']

            # Unknown persons count (always reported)
            cur.execute("SELECT COUNT(*) as cnt FROM persons WHERE name LIKE 'UNKNOWN_%'")
            unknown_persons_total = cur.fetchone()['cnt']

            # Edges total (respects include_unknown)
            if include_unknown:
                cur.execute("SELECT COUNT(*) as cnt FROM edges")
            else:
                cur.execute("""
                    SELECT COUNT(*) as cnt
                    FROM edges e
                    JOIN persons pa ON e.person_a_id = pa.id
                    JOIN persons pb ON e.person_b_id = pb.id
                    WHERE pa.name NOT LIKE 'UNKNOWN_%'
                      AND pb.name NOT LIKE 'UNKNOWN_%'
                """)
            edges_total = cur.fetchone()['cnt']

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

            return {
                'persons_total': persons_total,
                'unknown_persons_total': unknown_persons_total,
                'edges_total': edges_total,
                'top_edges': top_edges,
                'recent_uploads': recent_uploads
            }

    except Exception as e:
        logger.error(f"Graph summary failed: {e}")
        raise HTTPException(status_code=500, detail=f"Graph summary failed: {e}")


@router.get("/neighbors")
def graph_neighbors(
    person: str = Query(..., description="Person name to find neighbors for"),
    limit: int = Query(25, ge=1, le=100, description="Max neighbors to return"),
    include_unknown: bool = Query(True, description="Include UNKNOWN neighbors")
):
    """
    Get neighbors of a person in the social graph.

    Returns neighbors sorted by weight descending, then by neighbor name.
    Each neighbor includes up to 3 evidence filenames.
    """
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

            return {
                'person': person_name,
                'neighbors': neighbors
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Graph neighbors failed: {e}")
        raise HTTPException(status_code=500, detail=f"Graph neighbors failed: {e}")
