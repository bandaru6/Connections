"""Connections Social FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth import require_api_key
from app.config import UPLOADS_DIR
from app.db import check_db_connection, close_pool, get_pool_status

# Import observability components
from app.observability import (
    ObservabilityMiddleware,
    configure_logging,
    metrics_router,
)
from app.observability.tracing import init_tracing
from app.rate_limit import RateLimitMiddleware
from app.routes import admin, graph, ingest, jobs, profiles, search
from app.ws import manager as ws_manager

# Configure structured logging
configure_logging()
logger = logging.getLogger(__name__)

# Initialize OpenTelemetry tracing (if enabled)
init_tracing()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: warm pool on startup, close on shutdown."""
    logger.info("Application starting up — warming database connection pool")
    # Trigger pool initialization by running a connectivity check
    check_db_connection()
    yield
    logger.info("Application shutting down — closing database connection pool")
    close_pool()


app = FastAPI(
    title="Connections Social API",
    description=(
        "Event-driven ingestion and enrichment pipeline: "
        "ingest observations, extract features, classify against a reference corpus, "
        "persist events with full data lineage, and expose a queryable relationship graph."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# GZip compression — compresses responses > 1KB (graph queries return large JSON)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Observability middleware (must be added before CORS)
app.add_middleware(ObservabilityMiddleware)

# Rate limiting middleware — Redis-backed, fails open if Redis unavailable
app.add_middleware(RateLimitMiddleware)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://frontend:3000",  # Docker network
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers (including metrics)
app.include_router(metrics_router)  # /metrics endpoint for Prometheus
# Auth dependency applied at router level — all /admin and /ingest routes inherit it
app.include_router(admin.router, prefix="/admin", tags=["admin"], dependencies=[Depends(require_api_key)])
app.include_router(ingest.router, prefix="/ingest", tags=["ingest"], dependencies=[Depends(require_api_key)])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(graph.router, prefix="/graph", tags=["graph"])
app.include_router(profiles.router, prefix="/profiles", tags=["profiles"])
app.include_router(search.router, prefix="/search", tags=["search"])

# Serve uploaded images statically for evidence viewing
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=str(UPLOADS_DIR)), name="images")


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """Real-time ObservationEvent stream.

    Connect to receive a JSON message for every image processed by the
    ingestion pipeline.  Messages are ObservationEvent payloads — the same
    structure returned by POST /ingest/upload.

    Usage:
        wscat -c ws://localhost:8000/ws/events
        # Then POST /ingest/upload to see events appear in real time.

    Tesla relevance: equivalent to a live telemetry dashboard receiving
    processed events from the fleet pipeline as they complete — zero polling.
    """
    from app.observability.metrics import websocket_connections
    await ws_manager.connect(websocket)
    websocket_connections.set(ws_manager.connection_count)
    try:
        while True:
            # Keep the connection alive; broadcasting is done by ingest routes
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        websocket_connections.set(ws_manager.connection_count)


@app.get("/")
def root():
    """API information and endpoint directory."""
    return {
        "name": "Connections — Event Ingestion & Graph Pipeline",
        "description": (
            "Ingests raw observations (images), extracts 512-dim face embeddings, "
            "classifies against a reference corpus, persists co-occurrence events with "
            "full data lineage (model version, confidence, timestamp), and exposes a "
            "queryable weighted graph. Designed around telemetry pipeline principles: "
            "idempotent ingestion, replay capability, circuit-breaker isolation, "
            "structured observability."
        ),
        "version": "1.0.0",
        "endpoints": {
            "/health": "GET - Health check (PostgreSQL + Redis)",
            "/ready": "GET - Readiness probe (all dependencies + model loaded)",
            "/metrics": "GET - Prometheus metrics endpoint",
            "/system/info": "GET - System resource usage and pool stats",
            "/admin/rebuild-profile-index": "POST - Rebuild reference corpus embeddings",
            "/admin/reset-demo": "POST - Reset graph state (keeps reference corpus)",
            "/admin/clear-processed": "POST - Clear ingestion ledger (processed_images)",
            "/admin/replay": "POST - Reprocess all events with current model version",
            "/admin/report": "GET - Operational pipeline summary report",
            "/admin/benchmark": "GET - Brute-force vs pgvector ANN timing comparison",
            "/admin/retry-failed": "POST - Retry dead-letter queue items (?limit=N)",
            "/search/events": "GET - Full-text search over indexed ObservationEvents",
            "/search/stats": "GET - Elasticsearch index statistics",
            "/ingest/upload": "POST - Submit a single observation event for processing",
            "/ingest/folder": "POST - Batch-process all pending observations (blocking)",
            "/ingest/batch": "POST - Async batch ingestion (returns job ID for polling)",
            "/ingest/circuit-breaker/status": "GET - ML inference isolation state",
            "/ingest/circuit-breaker/reset": "POST - Manually reset circuit breaker",
            "/jobs/{job_id}": "GET - Poll async job status and progress",
            "/graph/summary": "GET - Graph statistics and top co-occurrence edges",
            "/graph/neighbors": "GET - Direct connections for a person (?person=Name)",
            "/graph/ego": "GET - Ego network BFS (?person=Name&depth=2)",
            "/graph/path": "GET - Shortest path between two persons",
            "/profiles/list": "GET - List all reference corpus profiles",
            "/profiles/create": "POST - Add new profile to reference corpus",
            "/profiles/check-match": "POST - Test face against reference corpus",
            "/images/{filename}": "GET - Serve raw observation images (evidence)",
        },
    }


@app.get("/health")
def health_check():
    """Liveness probe: verify PostgreSQL and Redis are reachable.

    Returns 200 even if degraded so that Kubernetes does not restart the pod
    on a transient dependency outage — use /ready for traffic gating instead.
    """
    import redis as redis_lib

    from app.config import REDIS_URL

    db_ok = check_db_connection()

    redis_ok = False
    try:
        r = redis_lib.from_url(REDIS_URL, socket_timeout=2)
        redis_ok = r.ping()
    except Exception:
        pass

    pool = get_pool_status()

    return {
        "status": "healthy" if (db_ok and redis_ok) else "degraded",
        "database": "ok" if db_ok else "unavailable",
        "redis": "ok" if redis_ok else "unavailable",
        "db_pool": pool,
    }


@app.get("/ready")
def readiness_check():
    """Readiness probe: gates traffic until all dependencies are verified.

    Kubernetes / load balancers should use this endpoint.  Returns 503 if
    any required dependency is unavailable so the pod is removed from rotation.
    """
    import redis as redis_lib
    from fastapi import HTTPException

    from app.config import REDIS_URL
    from app.routes.ingest import _face_app  # ML model singleton

    checks = {}

    # PostgreSQL
    checks["database"] = "ok" if check_db_connection() else "unavailable"

    # Redis
    try:
        r = redis_lib.from_url(REDIS_URL, socket_timeout=2)
        checks["redis"] = "ok" if r.ping() else "unavailable"
    except Exception:
        checks["redis"] = "unavailable"

    # ML model (may not be loaded yet if no inference has occurred)
    checks["ml_model"] = "loaded" if _face_app is not None else "not_loaded"

    all_critical_ok = checks["database"] == "ok" and checks["redis"] == "ok"

    if not all_critical_ok:
        raise HTTPException(status_code=503, detail={"ready": False, "checks": checks})

    return {"ready": True, "checks": checks}


@app.get("/system/info")
def system_info():
    """System resource usage and pipeline capacity metrics.

    Returns real-time resource consumption data that is directly relevant
    to production capacity planning and interview discussions about memory
    and performance tradeoffs.

    Key metrics for interview discussion:
      - memory_rss_mb: actual RAM usage of this process (model + pool + working set)
      - embeddings.memory_estimate_mb: O(n_profiles * 2048 bytes) per inference request
        — this is the scaling bottleneck that motivates a pgvector migration at >10K profiles
      - db_pool: shows pool utilization — alert triggers at 80% (see alerts.yml)
      - redis.used_memory_mb: shows cache + job state memory usage

    Tesla relevance: in a real telemetry pipeline, resource metrics like these
    feed directly into autoscaling decisions (HPA CPU targets, memory limits in
    K8s Deployment manifests) and cost optimization (right-sizing instances).
    """
    import os
    import time as time_lib

    import psutil
    import redis as redis_lib

    from app.config import REDIS_URL
    from app.db import get_cursor, get_pool_status
    from app.routes.ingest import _face_app

    proc = psutil.Process(os.getpid())
    mem = proc.memory_info()
    uptime_s = time_lib.time() - proc.create_time()

    # DB pool utilization
    pool = get_pool_status()

    # Redis memory
    redis_info: dict = {"connected": False, "used_memory_mb": None}
    try:
        r = redis_lib.from_url(REDIS_URL, socket_timeout=2)
        info = r.info("memory")
        redis_info = {
            "connected": True,
            "used_memory_mb": round(info.get("used_memory", 0) / 1e6, 2),
            "used_memory_peak_mb": round(info.get("used_memory_peak", 0) / 1e6, 2),
        }
    except Exception:
        pass

    # Profile embedding count + memory model
    # Each embedding = 512 float32 = 2048 bytes
    # All profiles are loaded into Python RAM per inference request (O(n) matching)
    profile_count = 0
    try:
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM person_profiles")
            profile_count = cur.fetchone()["cnt"]
    except Exception:
        pass

    bytes_per_embedding = 512 * 4  # 512 float32 values
    embedding_memory_mb = round(profile_count * bytes_per_embedding / 1e6, 3)

    return {
        "process": {
            "pid": os.getpid(),
            "cpu_percent": proc.cpu_percent(interval=0.1),
            "memory_rss_mb": round(mem.rss / 1e6, 2),
            "memory_vms_mb": round(mem.vms / 1e6, 2),
            "uptime_seconds": round(uptime_s, 1),
            "threads": proc.num_threads(),
        },
        "model": {
            "name": "buffalo_l",
            "loaded": _face_app is not None,
            "embedding_dim": 512,
            "note": (
                "Model is lazy-loaded on first inference request. "
                "~500MB additional RSS expected after first load."
            ),
        },
        "database": {
            **pool,
            "note": (
                "Alert fires at 80% pool utilization. "
                f"Current max={pool.get('max', 10)} connections."
            ),
        },
        "redis": redis_info,
        "embeddings": {
            "profile_count": profile_count,
            "bytes_per_embedding": bytes_per_embedding,
            "memory_estimate_mb": embedding_memory_mb,
            "per_request_load_mb": embedding_memory_mb,
            "matching_complexity": "O(n_profiles) cosine ops per detected face",
            "scaling_note": (
                f"At {profile_count} profiles: {embedding_memory_mb}MB loaded per request. "
                "Migrate to pgvector IVFFlat at >10K profiles for O(log n) ANN search."
            ),
        },
    }
