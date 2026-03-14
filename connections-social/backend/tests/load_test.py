"""Locust load test for the Connections Social API.

Simulates realistic traffic patterns against the pipeline's read and write
endpoints.  Three user classes with different behavior profiles:

  ReadUser   — graph query traffic (summary, neighbors, ego, path)
               High frequency, cache-friendly, should be fast after warmup.

  IngestUser — image upload traffic (the ML-heavy path)
               Low frequency, bounded by InsightFace inference time (~200ms).
               Rate-limited to 10 req/min in production (see rate_limit.py).

  AdminUser  — admin/monitoring traffic (benchmark, system/info)
               Very low frequency, authenticated in production.

Run:
    locust -f tests/load_test.py --host http://localhost:8000
    # Then open http://localhost:8089 in a browser

Or headless:
    locust -f tests/load_test.py --host http://localhost:8000 \\
           --users 20 --spawn-rate 2 --run-time 60s --headless

Tesla relevance:
    Load testing validates the HPA thresholds in hpa.yaml — specifically that
    the 70% CPU target is reached before latency degrades.  The ingest task
    weight (1) vs read weight (10) approximates the real traffic ratio for a
    system where uploads are rare but graph queries are frequent.
"""

import os
import random
from io import BytesIO

from locust import HttpUser, between, task
from locust.exception import RescheduleTask

# ── Configuration ────────────────────────────────────────────────────────────

# If API_KEY is set, include it in protected requests
API_KEY = os.getenv("API_KEY", "")
AUTH_HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

# Known person names to use for neighbor/path queries.
# Falls back to a generic list; override via LOCUST_PERSON_NAMES env var.
_DEFAULT_PERSONS = [
    "Musa",
    "Aashrith",
    "Elan",
    "Marcus",
    "Priya",
]
PERSON_NAMES = os.getenv("LOCUST_PERSON_NAMES", ",".join(_DEFAULT_PERSONS)).split(",")


# ── Minimal synthetic JPEG (1×1 pixel) for upload tests ─────────────────────

def _make_minimal_jpeg() -> bytes:
    """Return a minimal valid 1×1 red JPEG (~600 bytes).

    Using a real JPEG (even tiny) ensures the server parses it correctly.
    No face will be detected, but the pipeline still exercises:
      - file save, idempotency check, InsightFace detection, PERSISTED write.
    """
    # 1×1 red pixel JPEG (base64-decoded inline to avoid external dependency)
    import base64
    _TINY_RED_JPEG = (
        "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
        "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
        "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
        "MjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAA"
        "AAAAAAAAAAAAAAAAAP/EABQBAQAAAAAAAAAAAAAAAAAAAAD/xAAUEQEAAAAAAAAAAAAAAAAA"
        "AAAA/9oADAMBAAIRAxEAPwCwABmX/9k="
    )
    return base64.b64decode(_TINY_RED_JPEG)


_JPEG_BYTES = _make_minimal_jpeg()


# ── User classes ─────────────────────────────────────────────────────────────

class ReadUser(HttpUser):
    """Simulates a client polling the graph read endpoints.

    These are the cheap, cache-friendly endpoints that should sustain high
    throughput.  After the first request warms the Redis cache, subsequent
    requests for the same data should complete in < 5ms.

    Weight 10 means 10× more ReadUsers are spawned vs IngestUsers.
    """

    wait_time = between(0.5, 2.0)   # 0.5–2s between requests per user
    weight = 10

    def on_start(self):
        """Verify the service is reachable before starting."""
        resp = self.client.get("/health", name="/health [warmup]")
        if resp.status_code != 200:
            raise RescheduleTask()

    @task(5)
    def graph_summary(self):
        """GET /graph/summary — top edges, graph stats."""
        self.client.get("/graph/summary", name="/graph/summary")

    @task(4)
    def graph_neighbors(self):
        """GET /graph/neighbors — direct connections for a person."""
        person = random.choice(PERSON_NAMES)
        self.client.get(
            f"/graph/neighbors?person={person}&limit=10",
            name="/graph/neighbors",
        )

    @task(2)
    def graph_ego(self):
        """GET /graph/ego — BFS ego network."""
        person = random.choice(PERSON_NAMES)
        self.client.get(
            f"/graph/ego?person={person}&depth=2",
            name="/graph/ego",
        )

    @task(1)
    def graph_path(self):
        """GET /graph/path — shortest path between two random people."""
        if len(PERSON_NAMES) < 2:
            return
        a, b = random.sample(PERSON_NAMES, 2)
        self.client.get(
            f"/graph/path?source={a}&target={b}",
            name="/graph/path",
        )

    @task(3)
    def health_check(self):
        """GET /health — liveness probe (should always be fast)."""
        self.client.get("/health", name="/health")

    @task(1)
    def profiles_list(self):
        """GET /profiles/list — reference corpus listing."""
        self.client.get("/profiles/list", name="/profiles/list")


class IngestUser(HttpUser):
    """Simulates image upload traffic — the expensive ML inference path.

    These users hit /ingest/upload which runs InsightFace detection.
    Weight 1 means far fewer IngestUsers are spawned — this matches real
    usage where uploads are rare but queries are constant.

    In production the rate limiter caps this at 10 req/min per IP anyway;
    this load test validates the behavior under that constraint.
    """

    wait_time = between(5.0, 15.0)  # Slow — ML inference is expensive
    weight = 1

    @task
    def ingest_upload(self):
        """POST /ingest/upload — synthetic image (no face → fast path)."""
        # Use a unique filename each time to bypass the idempotency ledger
        filename = f"load_test_{random.randint(0, 999999)}.jpg"
        self.client.post(
            "/ingest/upload",
            files={"image": (filename, BytesIO(_JPEG_BYTES), "image/jpeg")},
            headers=AUTH_HEADERS,
            name="/ingest/upload",
        )


class AdminUser(HttpUser):
    """Simulates infrequent admin/monitoring traffic."""

    wait_time = between(10.0, 30.0)  # Very slow — admin is low-frequency
    weight = 1

    @task(3)
    def system_info(self):
        """GET /system/info — resource metrics (memory, pool, embeddings)."""
        self.client.get("/system/info", name="/system/info")

    @task(2)
    def ready_check(self):
        """GET /ready — readiness probe."""
        self.client.get("/ready", name="/ready")

    @task(1)
    def benchmark(self):
        """GET /admin/benchmark — brute-force vs pgvector timing."""
        self.client.get(
            "/admin/benchmark?top_k=5&iterations=3",
            headers=AUTH_HEADERS,
            name="/admin/benchmark",
        )

    @task(1)
    def circuit_breaker_status(self):
        """GET /ingest/circuit-breaker/status — ML isolation state."""
        self.client.get(
            "/ingest/circuit-breaker/status",
            headers=AUTH_HEADERS,
            name="/ingest/circuit-breaker/status",
        )
