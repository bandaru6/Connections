"""Elasticsearch integration for ObservationEvent indexing and search.

Every image processed by the ingestion pipeline is indexed as a document
in Elasticsearch so that operators can:
  - Search events by filename, person name, or pipeline stage
  - Inspect failure patterns across time
  - Filter by match confidence or edge counts

Tesla relevance:
  In a vehicle telemetry pipeline, a search layer over processed events lets
  you answer operational questions like "show me all frames where detection
  confidence was below 0.5 in the last hour" without running a DB query.
  Elasticsearch handles the full-text and range queries that PostgreSQL
  would struggle with at scale (e.g. free-text error messages, nested JSON).

Architecture:
  - Fails open: if ES is unavailable, indexing is skipped silently (no impact
    on the ingestion path). The ingest route must never fail because search is down.
  - Index: `ingest_events` (one document per ObservationEvent)
  - Mapping: dynamically inferred, with explicit types for key date/numeric fields.
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
INDEX_NAME = "ingest_events"

# Lazy-initialized client
_es_client = None


def _get_client():
    """Get or create Elasticsearch client. Returns None if ES unavailable."""
    global _es_client
    if _es_client is not None:
        return _es_client

    try:
        from elasticsearch import Elasticsearch

        client = Elasticsearch(
            ELASTICSEARCH_URL,
            request_timeout=3,
            retry_on_timeout=False,
            max_retries=0,
        )
        # Probe — raises if unreachable
        if client.ping():
            _es_client = client
            _ensure_index(client)
            logger.info("Elasticsearch connected at %s", ELASTICSEARCH_URL)
        else:
            logger.warning("Elasticsearch ping failed — search indexing disabled")
    except ImportError:
        logger.info("elasticsearch-py not installed — search indexing disabled")
    except Exception as e:
        logger.warning("Elasticsearch unavailable (%s) — search indexing disabled", e)

    return _es_client


def _ensure_index(client) -> None:
    """Create index with explicit mapping if it doesn't exist."""
    if client.indices.exists(index=INDEX_NAME):
        return

    mapping = {
        "mappings": {
            "properties": {
                "event_id":        {"type": "keyword"},
                "source_filename": {"type": "keyword"},
                "received_at":     {"type": "date"},
                "stage":           {"type": "keyword"},
                "faces_detected":  {"type": "integer"},
                "known_matches":   {"type": "integer"},
                "unknown_faces":   {"type": "integer"},
                "edges_created":   {"type": "integer"},
                "schema_version":  {"type": "keyword"},
                "skipped_reason":  {"type": "keyword"},
                "latency_total_ms": {"type": "float"},
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,  # Single-node dev setup
        },
    }
    client.indices.create(index=INDEX_NAME, body=mapping)
    logger.info("Created Elasticsearch index: %s", INDEX_NAME)


def index_event(event: Dict[str, Any]) -> None:
    """Index an ObservationEvent document.

    Called from the ingest route after every upload (success or skip).
    Fails silently — ES outage must never block ingestion.

    Args:
        event: ObservationEvent serialized to dict (from .dict() or .model_dump())
    """
    client = _get_client()
    if client is None:
        return

    try:
        # Flatten latency_ms for easier range queries
        doc = {**event}
        if isinstance(doc.get("latency_ms"), dict):
            doc["latency_total_ms"] = doc["latency_ms"].get("total")

        client.index(
            index=INDEX_NAME,
            id=doc.get("event_id"),  # Idempotent: same event_id = upsert
            document=doc,
        )
    except Exception as e:
        logger.warning("ES index_event failed: %s", e)


def search_events(
    q: Optional[str] = None,
    stage: Optional[str] = None,
    min_faces: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """Search indexed ObservationEvents.

    Args:
        q:         Full-text query (matches source_filename, stage, skipped_reason)
        stage:     Filter by pipeline stage (e.g. PERSISTED, FAILED, SKIPPED)
        min_faces: Filter events with at least N faces detected
        limit:     Max results (default 20, max 200)
        offset:    Pagination offset

    Returns:
        dict with total, hits list, and took_ms
    """
    client = _get_client()
    if client is None:
        return {"total": 0, "hits": [], "took_ms": None, "note": "Elasticsearch unavailable"}

    limit = min(limit, 200)
    must: List[Dict] = []
    filter_: List[Dict] = []

    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": ["source_filename", "stage", "skipped_reason"],
            }
        })

    if stage:
        filter_.append({"term": {"stage": stage.upper()}})

    if min_faces is not None:
        filter_.append({"range": {"faces_detected": {"gte": min_faces}}})

    query: Dict = {"bool": {}}
    if must:
        query["bool"]["must"] = must
    if filter_:
        query["bool"]["filter"] = filter_
    if not must and not filter_:
        query = {"match_all": {}}

    try:
        resp = client.search(
            index=INDEX_NAME,
            body={
                "query": query,
                "sort": [{"received_at": {"order": "desc"}}],
                "from": offset,
                "size": limit,
            },
        )
        hits = [h["_source"] for h in resp["hits"]["hits"]]
        total = resp["hits"]["total"]["value"]
        took_ms = resp.get("took")

        return {"total": total, "hits": hits, "took_ms": took_ms}

    except Exception as e:
        logger.warning("ES search failed: %s", e)
        return {"total": 0, "hits": [], "took_ms": None, "error": str(e)}


def get_index_stats() -> Dict[str, Any]:
    """Return document count and index size for the ingest_events index."""
    client = _get_client()
    if client is None:
        return {"available": False}

    try:
        stats = client.indices.stats(index=INDEX_NAME)
        idx = stats["indices"].get(INDEX_NAME, {})
        total = idx.get("total", {})
        return {
            "available": True,
            "index": INDEX_NAME,
            "doc_count": total.get("docs", {}).get("count", 0),
            "size_bytes": total.get("store", {}).get("size_in_bytes", 0),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}
