"""Search routes — full-text event search backed by Elasticsearch."""

import logging

from fastapi import APIRouter, Query

from app.search import get_index_stats, search_events

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/events")
def search_ingest_events(
    q: str | None = Query(None, description="Full-text query (filename, stage, error)"),
    stage: str | None = Query(None, description="Filter by stage: PERSISTED, FAILED, SKIPPED"),
    min_faces: int | None = Query(None, ge=0, description="Min faces detected"),
    limit: int = Query(20, ge=1, le=200, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """Search processed ObservationEvents indexed in Elasticsearch.

    Supports full-text search across filenames and pipeline stages, plus
    structured filters on numeric fields.  Returns results sorted newest-first.

    When Elasticsearch is unavailable, returns empty results with a note —
    the endpoint never errors out.

    Examples:
        GET /search/events?q=group_photo
        GET /search/events?stage=FAILED
        GET /search/events?min_faces=3&limit=5
        GET /search/events?q=lebron&stage=PERSISTED
    """
    return search_events(q=q, stage=stage, min_faces=min_faces, limit=limit, offset=offset)


@router.get("/stats")
def search_index_stats():
    """Return Elasticsearch index statistics for the ingest_events index.

    Shows document count, index size, and availability status.
    Useful for confirming that events are being indexed correctly.
    """
    return get_index_stats()
