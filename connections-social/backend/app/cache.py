"""Redis-backed response cache for hot graph query endpoints.

Design rationale
────────────────
Graph summary and neighbor queries are read-heavy, computationally cheap to
cache, and tolerate short staleness (graph changes only on ingest, not in
real time).  Caching these responses with a short TTL (30–60 seconds)
removes several JOIN queries per request under load.

Cache key structure:
  graph:{endpoint}:{param_hash}
  e.g. graph:summary:include_unknown=false
       graph:neighbors:person=Barack+Obama:include_unknown=false:limit=25

Failure semantics
─────────────────
If Redis is unavailable, every call falls through to the database.
The cache is a performance optimization, never a correctness requirement.
This is the same design principle used in CDN edge caches: origin is always
authoritative; the cache is a best-effort acceleration layer.

Invalidation
────────────
On successful ingest the ingestion route calls `invalidate_graph_cache()`,
which deletes all keys under the `graph:*` prefix.  This is safe because
the graph is small enough that a full prefix scan (via SCAN + DEL) is O(k)
where k is the number of cached endpoints (typically < 20 keys).
"""

import json
import logging
from typing import Any, Optional

import redis as redis_lib

from app.config import REDIS_URL

logger = logging.getLogger(__name__)

# Cache TTLs (in seconds)
SUMMARY_TTL = 60    # graph summary is expensive; 60s freshness is acceptable
NEIGHBORS_TTL = 30  # neighbor lists change more frequently after ingest
CACHE_KEY_PREFIX = "graph:"


def _get_redis() -> Optional[redis_lib.Redis]:
    """Return a Redis client, or None if unavailable."""
    try:
        r = redis_lib.from_url(REDIS_URL, socket_timeout=1, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def get_cached(key: str) -> Optional[Any]:
    """Return deserialized cached value, or None on miss/error."""
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.debug(f"Cache get failed for key={key}: {exc}")
        return None


def set_cached(key: str, value: Any, ttl: int) -> None:
    """Serialize and store value with TTL. Silently drops on error."""
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception as exc:
        logger.debug(f"Cache set failed for key={key}: {exc}")


def invalidate_graph_cache() -> int:
    """Delete all graph:* cache keys. Called after successful ingest.

    Returns the number of keys deleted (for logging/metrics).
    Uses SCAN to avoid blocking Redis with a KEYS command on large keyspaces.
    """
    r = _get_redis()
    if r is None:
        return 0
    deleted = 0
    try:
        cursor = 0
        pattern = f"{CACHE_KEY_PREFIX}*"
        while True:
            cursor, keys = r.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                deleted += r.delete(*keys)
            if cursor == 0:
                break
        if deleted:
            logger.info(f"Graph cache invalidated: {deleted} key(s) deleted")
    except Exception as exc:
        logger.warning(f"Cache invalidation failed: {exc}")
    return deleted


def cache_key_summary(include_unknown: bool) -> str:
    return f"{CACHE_KEY_PREFIX}summary:include_unknown={include_unknown}"


def cache_key_neighbors(person: str, include_unknown: bool, limit: int) -> str:
    safe_person = person.replace(" ", "+")
    return f"{CACHE_KEY_PREFIX}neighbors:person={safe_person}:unknown={include_unknown}:limit={limit}"
