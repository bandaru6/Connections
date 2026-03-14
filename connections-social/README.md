# Connections — Event Ingestion & Graph Pipeline

[![CI](https://github.com/bandaru6/Connections/actions/workflows/ci.yml/badge.svg)](https://github.com/bandaru6/Connections/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An **event-driven ingestion and enrichment pipeline** that processes raw image observations, extracts 512-dimensional face embeddings using InsightFace, classifies detections against a reference corpus, persists co-occurrence events with full data lineage, and exposes a queryable weighted relationship graph.

Built around telemetry pipeline principles: **idempotent ingestion**, **replay capability**, **circuit-breaker isolation**, **structured observability**, and **Kubernetes-ready deployment**.

<p align="center">
  <img src="assets/demo-screenshot.png" alt="Demo Screenshot" width="800">
</p>

---

## Pipeline Overview

Each uploaded image is an **observation event** that moves through a typed lifecycle:

```
Image Upload  →  Feature Extraction  →  Classification  →  Persistence
(observation)    (512-dim embedding)    (cosine match)     (graph edge + lineage)
```

| Pipeline Stage | This System | Tesla Autonomy Analog |
|---|---|---|
| **Observation received** | `POST /ingest/upload` — image saved, idempotency checked | Camera frame received from vehicle |
| **Feature extraction** | InsightFace detection → 512-dim `normed_embedding` | Perception model → bounding boxes + features |
| **Classification** | Cosine similarity against reference corpus (O(n) → pgvector O(log n)) | Object classifier → class label + confidence |
| **Event persisted** | Edge upsert + `edge_evidence` row with model version, confidence, timestamp | Telemetry event written to time-series store |
| **Replay** | `POST /admin/replay` — reprocess with new model, backfill lineage | Reprocess historical frames with updated model weights |
| **Idempotency** | `processed_images` ledger — duplicate upload returns SKIPPED | Deduplication key prevents duplicate telemetry records |

Every ingest call returns a structured `ObservationEvent`:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "stage": "PERSISTED",
  "faces_detected": 3,
  "known_matches": 2,
  "edges_created": 1,
  "edge_provenance": [{"person_a": "Alice", "person_b": "Bob", "model_version": "buffalo_l", "confidence_a": 0.82}],
  "latency_ms": {"receive": 12.1, "pipeline": 843.5, "total": 855.6}
}
```

---

## Quick Start

### Prerequisites

- [Docker Desktop](https://docs.docker.com/get-docker/) with Compose v2 (enable Kubernetes for K8s demo)
- 8GB+ RAM (InsightFace buffalo_l model: ~350MB)

### One-Command Demo

```bash
git clone https://github.com/bandaru6/Connections.git
cd Connections/connections-social
cp .env.example .env
docker compose up --build -d
make seed          # Loads reference profiles + demo images
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API + docs | http://localhost:8000 / http://localhost:8000/docs |
| Prometheus metrics | http://localhost:8000/metrics |

```bash
docker compose down      # Stop (keeps data)
docker compose down -v   # Stop + wipe
```

### Local Development (databases only)

```bash
make dev                        # Starts Postgres + Redis in Docker

cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://localhost:8000
```

---

## Key Endpoints

### Ingestion Pipeline

| Endpoint | Description |
|---|---|
| `POST /ingest/upload` | Submit one observation event; returns `ObservationEvent` with stage + latency |
| `POST /ingest/batch` | Async batch — returns job ID for polling |
| `POST /ingest/folder` | Blocking batch of all images in uploads/ |
| `GET /ingest/circuit-breaker/status` | ML inference isolation state |
| `POST /ingest/circuit-breaker/reset` | Manually close circuit breaker |

### Graph Queries

| Endpoint | Description |
|---|---|
| `GET /graph/summary` | Top edges + graph stats (Redis-cached, TTL 60s) |
| `GET /graph/neighbors?person=Name` | Direct connections (Redis-cached, TTL 30s) |
| `GET /graph/ego?person=Name&depth=2` | BFS ego network |
| `GET /graph/path?source=A&target=B` | Shortest path |

### Observability & Admin

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness probe (always 200, reports degraded state) |
| `GET /ready` | Readiness probe (503 if any dependency down) |
| `GET /metrics` | Prometheus metrics |
| `GET /system/info` | Process memory, pool utilization, embedding memory model |
| `GET /admin/benchmark` | Brute-force vs pgvector ANN timing comparison |
| `POST /admin/replay` | Reprocess historical events with current model |
| `POST /admin/rebuild-profile-index` | Rebuild reference corpus embeddings |

---

## Architecture

```
                     ┌──────────────────────────────────────────┐
                     │            Observability Stack            │
                     │  Prometheus metrics · JSON logs · OTel   │
                     │  Grafana dashboard · Alerting rules       │
                     └─────────────────┬────────────────────────┘
                                       │
  ┌──────────────┐   ┌─────────────────▼──────────────────────┐
  │  Next.js     │──▶│              FastAPI Backend            │
  │  Frontend    │   │                                         │
  └──────────────┘   │  Rate Limit ──▶ Auth ──▶ Routes        │
                     │                                         │
                     │  /ingest  →  CircuitBreaker             │
                     │             │                           │
                     │             ▼                           │
                     │          InsightFace (buffalo_l)        │
                     │          512-dim embedding              │
                     │             │                           │
                     │             ▼                           │
                     │          Cosine match → ObservationEvent│
                     └───────────────────────┬────────────────┘
                                             │
               ┌─────────────────────────────┼─────────────────────┐
               ▼                             ▼                     ▼
      ┌────────────────┐           ┌──────────────────┐   ┌──────────────┐
      │   PostgreSQL   │           │     Redis         │   │    K8s       │
      │  persons       │           │  Query cache      │   │  Deployment  │
      │  embeddings    │           │  Job state        │   │  HPA (2-10)  │
      │  edges         │           │  Rate limits      │   │  Ingress     │
      │  edge_evidence │           └──────────────────┘   └──────────────┘
      │  + pgvector    │
      └────────────────┘
```

### Key Design Decisions

| Decision | Choice | Why |
|---|---|---|
| Embedding storage | BYTEA (+ pgvector migration path) | Zero-dep default; migrate to ANN at >10K profiles |
| Connection pooling | `ThreadedConnectionPool` min=2 max=10 | 5-10ms → 0.1ms checkout; bounded by `max_connections/replicas` |
| Redis caching | SCAN-based prefix invalidation | Non-blocking at large keyspaces; graph changes visible within 1 TTL |
| Rate limiting | Redis fixed-window per IP | Distributed — works correctly across min=2 replicas |
| Auth | FastAPI `APIKeyHeader` dependency | Applied at router level; zero per-route boilerplate; disabled in dev |
| Circuit breaker | CLOSED→OPEN→HALF_OPEN | Isolates ML failures from graph read endpoints |
| Async jobs | Thread pool + Redis state | Avoids blocking the ASGI event loop for 1-2s inference workloads |

---

## Observability

### Prometheus Metrics (10 alerting rules)

```bash
curl localhost:8000/metrics
```

Key metrics: `http_request_duration_seconds` (p50/p95/p99), `db_pool_checked_out`, `cache_hits_total`, `faces_detected_total`, `faces_matched_total`

### Alerting Rules (`infra/monitoring/alerts.yml`)

| Alert | Severity | Condition |
|---|---|---|
| BackendDown | critical | service unreachable for 1m |
| HighErrorRate | critical | >5% 5xx over 5m |
| HighP99Latency | warning | p99 > 5s over 5m |
| DBPoolNearExhaustion | warning | checked_out/max > 80% |
| CircuitBreakerOpen | critical | state=OPEN for 1m |
| IngestStalled | info | ingest rate=0 while service is up for 30m |

### Grafana Dashboard

```bash
docker compose -f infra/monitoring/docker-compose.monitoring.yml up -d
# Grafana: http://localhost:3001 (admin/admin)
# Import infra/monitoring/grafana-dashboard.json
```

---

## Kubernetes Deployment

```bash
# Prerequisites: kubectl + Docker Desktop K8s enabled
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/configmap.yaml
# Fill in infra/k8s/secrets-template.yaml with real values, then:
kubectl apply -f infra/k8s/secrets.yaml
kubectl apply -f infra/k8s/backend-deployment.yaml
kubectl apply -f infra/k8s/backend-service.yaml
kubectl apply -f infra/k8s/hpa.yaml
kubectl apply -f infra/k8s/ingress.yaml
kubectl apply -f infra/k8s/pvc.yaml
```

| K8s Resource | Configuration |
|---|---|
| Deployment | 2 replicas, RollingUpdate (maxUnavailable=0), non-root UID 1000 |
| HPA | min=2 max=10, CPU 70% + memory 80% triggers |
| Probes | liveness→`/health`, readiness→`/ready`, startupProbe (150s for model download) |
| Ingress | nginx, `/api/*` rewrite, 300s timeout (ML inference), 10 rps rate limit |

---

## Testing

```bash
cd backend

# Unit tests — no services needed (56 tests)
pytest tests/test_unit.py -v

# Integration tests — requires running Postgres + Redis
pytest tests/test_integration.py -v

# Load test (requires locust)
pip install locust
locust -f tests/load_test.py --host http://localhost:8000
# Web UI: http://localhost:8089
```

### Test Coverage

| Test Class | What it covers |
|---|---|
| `TestCosineSimilarity` | Embedding math: identical=1.0, opposite=-1.0, scale invariance |
| `TestMatchingThresholds` | Classification boundaries including float64 precision edge cases |
| `TestEmbeddingStorage` | BYTEA pack/unpack round-trip, 2048-byte size |
| `TestCircuitBreaker` | CLOSED→OPEN→HALF_OPEN transitions, reject-without-call |
| `TestJobStateMachine` | PENDING→RUNNING→COMPLETED/FAILED transitions |
| `TestMetricsPathNormalization` | UUID/numeric ID path cardinality prevention |
| `TestApiKeyAuth` | Dev-mode bypass, correct key, wrong key → 401 |
| `TestRateLimitConfig` | Ingest < default limit, probe paths exempt |

---

## pgvector Migration (scaling path)

The current matching path is O(n_profiles) Python cosine similarity. At >10K profiles, migrate to pgvector ANN:

```bash
# 1. Apply schema migration (adds embedding_vec vector(512) column + IVFFlat index)
psql $DATABASE_URL -f infra/docker/migrate_pgvector.sql

# 2. Populate from existing BYTEA column
python backend/scripts/migrate_embeddings.py

# 3. Verify the performance difference
curl localhost:8000/admin/benchmark
```

The `/admin/benchmark` endpoint runs both methods against live data and returns timing + scaling projections.

---

## Project Structure

```
connections-social/
├── backend/
│   ├── app/
│   │   ├── main.py              # Lifespan, middleware, router registration
│   │   ├── config.py            # All env-var config (DB, Redis, API_KEY, pool)
│   │   ├── auth.py              # X-API-Key dependency (router-level injection)
│   │   ├── rate_limit.py        # Redis fixed-window rate limiting middleware
│   │   ├── db.py                # ThreadedConnectionPool, get_cursor()
│   │   ├── cache.py             # Redis query cache with SCAN invalidation
│   │   ├── circuit_breaker.py   # CLOSED/OPEN/HALF_OPEN state machine
│   │   ├── jobs.py              # Async job manager (Redis-backed)
│   │   ├── schemas/events.py    # ObservationEvent Pydantic schema
│   │   ├── routes/
│   │   │   ├── ingest.py        # Pipeline: detect → match → persist
│   │   │   ├── graph.py         # Graph queries (cached)
│   │   │   ├── admin.py         # Admin ops + /benchmark endpoint
│   │   │   ├── profiles.py      # Reference corpus management
│   │   │   └── jobs.py          # Job status polling
│   │   └── observability/       # Prometheus metrics, structured logging, OTel
│   ├── scripts/
│   │   └── migrate_embeddings.py  # Populate pgvector column from BYTEA
│   ├── tests/
│   │   ├── test_unit.py         # 56 unit tests (no services)
│   │   ├── test_integration.py  # 7 integration tests (Postgres + Redis)
│   │   └── load_test.py         # Locust: ReadUser × 10, IngestUser × 1
│   ├── Dockerfile               # Non-root UID 1000, multi-stage ready
│   ├── requirements.txt
│   └── requirements-dev.txt
├── infra/
│   ├── docker/
│   │   ├── init.sql             # Full schema (uuid-ossp, all indexes)
│   │   └── migrate_pgvector.sql # pgvector extension + IVFFlat index
│   ├── k8s/                     # 8 manifests: Namespace, ConfigMap, Secrets,
│   │   │                        # Deployment, Service, HPA, Ingress, PVC
│   └── monitoring/
│       ├── alerts.yml           # 10 Prometheus alerting rules with runbooks
│       ├── grafana-dashboard.json
│       ├── prometheus.yml
│       └── docker-compose.monitoring.yml
├── docs/
│   ├── INTERVIEW_GUIDE.md       # 30s/2min/10min pitches, Q&A
│   ├── TELEMETRY_ALIGNMENT.md   # Tesla concept → this system mapping
│   ├── TRADEOFFS.md             # Architecture decisions with numbers
│   ├── FUTURE_WORK.md           # Kafka, GPU workers, DynamoDB, ES
│   └── ARCHITECTURE.md          # Detailed system design
├── docker-compose.yml
├── Makefile
└── .env.example
```

---

## Configuration

```bash
# Database
DATABASE_URL=postgresql://connections:connections@postgres:5432/connections
DB_POOL_MIN_CONN=2        # Warm connections at idle
DB_POOL_MAX_CONN=10       # Cap: max_connections(100) / replicas(10) = 10

# Redis
REDIS_URL=redis://redis:6379/0

# Auth (empty = disabled in dev; always set in production via K8s Secret)
API_KEY=

# ML
INSIGHTFACE_MODEL=buffalo_l

# Observability
LOG_LEVEL=INFO
LOG_JSON=true
METRICS_ENABLED=true
OTEL_ENABLED=false
```

---

## License

MIT — see [LICENSE](LICENSE)

## Acknowledgments

- [InsightFace](https://github.com/deepinsight/insightface) — face detection and recognition
- [vis-network](https://visjs.github.io/vis-network/docs/network/) — graph visualization
- [pgvector](https://github.com/pgvector/pgvector) — ANN search in PostgreSQL
