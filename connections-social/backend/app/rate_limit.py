"""Redis-backed fixed-window rate limiting middleware.

Uses Redis INCR + EXPIRE for atomic, distributed counting — unlike in-memory
limiters, this works correctly across multiple replicas (the K8s Deployment
runs min=2 pods).

Key design decisions:
  - Fixed-window (not sliding-window): simpler, sufficient for burst protection
  - Fail-open: if Redis is unavailable, requests are NOT blocked — this ensures
    K8s liveness/readiness probes always succeed and avoids cascading failures
  - Exempt paths: /health, /ready, /metrics are never rate-limited so that
    Kubernetes probes cannot be accidentally throttled
  - X-Forwarded-For awareness: respects the client IP from a reverse proxy
    (nginx ingress) rather than always seeing the pod's cluster IP

Rate limits:
  /ingest/*  →  10 req/min  (ML inference is CPU-bound and expensive)
  /admin/*   →  20 req/min  (administrative operations, low-frequency by design)
  all others → 100 req/min  (graph queries, profile reads)

Redis key format: rl:{path_prefix}:{client_ip}:{window_bucket}
Window bucket:    int(epoch_seconds / 60) — resets every full minute.
"""

import logging
import time

import redis as redis_lib
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import REDIS_URL

logger = logging.getLogger(__name__)

# Requests per minute per client IP, by first path segment
_RATE_LIMITS: dict[str, int] = {
    "/ingest": 10,
    "/admin": 20,
}
_DEFAULT_LIMIT = 100
_WINDOW_SECONDS = 60

# Paths never subject to rate limiting
_EXEMPT_PATHS = frozenset({"/health", "/ready", "/metrics", "/"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces per-IP rate limits via Redis."""

    def __init__(self, app):
        super().__init__(app)
        try:
            self._redis = redis_lib.from_url(
                REDIS_URL, socket_timeout=1, decode_responses=True
            )
            self._redis.ping()
            logger.info("Rate limiter: Redis connected at %s", REDIS_URL)
        except Exception as exc:
            self._redis = None
            logger.warning("Rate limiter: Redis unavailable (%s) — limiting disabled", exc)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Never rate-limit K8s probes or Prometheus scrapes
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        # Determine limit for this path prefix
        path_prefix = "/" + path.lstrip("/").split("/")[0]
        limit = _RATE_LIMITS.get(path_prefix, _DEFAULT_LIMIT)

        # Fail-open if Redis is unavailable
        if self._redis is None:
            return await call_next(request)

        # Resolve client IP — trust X-Forwarded-For set by the nginx ingress
        client_ip = "unknown"
        if request.client:
            client_ip = request.client.host
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        # Fixed-window counter
        window_bucket = int(time.time() / _WINDOW_SECONDS)
        key = f"rl:{path_prefix.lstrip('/')}:{client_ip}:{window_bucket}"

        try:
            count = self._redis.incr(key)
            if count == 1:
                # First request in this window — set expiry (extra 5s for clock skew)
                self._redis.expire(key, _WINDOW_SECONDS + 5)

            if count > limit:
                retry_after = _WINDOW_SECONDS - (int(time.time()) % _WINDOW_SECONDS)
                logger.info(
                    "Rate limit exceeded: ip=%s path=%s count=%d limit=%d",
                    client_ip, path, count, limit,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "detail": f"Too many requests. Limit: {limit} req/min.",
                        "retry_after_seconds": retry_after,
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )
        except Exception as exc:
            # Fail open — never block traffic due to a Redis error
            logger.warning("Rate limit check error: %s — failing open", exc)

        return await call_next(request)
