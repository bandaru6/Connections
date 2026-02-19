"""
Athlete listing and search endpoints.
"""

from typing import Optional
from fastapi import APIRouter, Query, HTTPException

from ..db import get_cursor

router = APIRouter()


@router.get("/list")
async def list_athletes(
    league: Optional[str] = Query(None, description="Filter by league: nba or nfl"),
    team: Optional[str] = Query(None, description="Filter by team name"),
    search: Optional[str] = Query(None, description="Search by player name"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """List all athletes in the database with optional filters."""
    with get_cursor() as cursor:
        # Build query dynamically
        conditions = []
        params = []

        if league:
            conditions.append("league = %s")
            params.append(league.lower())

        if team:
            conditions.append("team ILIKE %s")
            params.append(f"%{team}%")

        if search:
            conditions.append("name ILIKE %s")
            params.append(f"%{search}%")

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # Get total count
        cursor.execute(f"SELECT COUNT(*) as count FROM athletes {where_clause}", params)
        total = cursor.fetchone()["count"]

        # Get athletes
        cursor.execute(f"""
            SELECT id, name, league, team, position, external_id, created_at
            FROM athletes
            {where_clause}
            ORDER BY name
            LIMIT %s OFFSET %s
        """, params + [limit, offset])

        athletes = cursor.fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "athletes": [
            {
                "id": str(row["id"]),
                "name": row["name"],
                "league": row["league"],
                "team": row["team"],
                "position": row["position"],
                "external_id": row["external_id"]
            }
            for row in athletes
        ]
    }


@router.get("/stats")
async def athlete_stats():
    """Get statistics about athletes in the database."""
    with get_cursor() as cursor:
        # Total counts
        cursor.execute("""
            SELECT
                COUNT(*) as total_athletes,
                COUNT(DISTINCT league) as leagues,
                COUNT(DISTINCT team) as teams
            FROM athletes
        """)
        totals = cursor.fetchone()

        # Count by league
        cursor.execute("""
            SELECT league, COUNT(*) as count
            FROM athletes
            GROUP BY league
            ORDER BY count DESC
        """)
        by_league = cursor.fetchall()

        # Count athletes with embeddings
        cursor.execute("""
            SELECT COUNT(DISTINCT athlete_id) as count
            FROM athlete_profiles
        """)
        with_embeddings = cursor.fetchone()["count"]

    return {
        "total_athletes": totals["total_athletes"],
        "leagues": totals["leagues"],
        "teams": totals["teams"],
        "athletes_with_embeddings": with_embeddings,
        "by_league": {row["league"]: row["count"] for row in by_league}
    }


@router.get("/{athlete_id}")
async def get_athlete(athlete_id: str):
    """Get details for a specific athlete."""
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT id, name, league, team, position, external_id, created_at
            FROM athletes
            WHERE id = %s
        """, (athlete_id,))

        athlete = cursor.fetchone()
        if not athlete:
            raise HTTPException(status_code=404, detail="Athlete not found")

        # Get profile info
        cursor.execute("""
            SELECT id, image_path, created_at
            FROM athlete_profiles
            WHERE athlete_id = %s
        """, (athlete_id,))
        profiles = cursor.fetchall()

    return {
        "id": str(athlete["id"]),
        "name": athlete["name"],
        "league": athlete["league"],
        "team": athlete["team"],
        "position": athlete["position"],
        "external_id": athlete["external_id"],
        "profiles": [
            {
                "id": str(p["id"]),
                "image_path": p["image_path"]
            }
            for p in profiles
        ]
    }
