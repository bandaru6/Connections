# Architecture

## System Purpose

Connections is an **event-driven ingestion and enrichment pipeline** that processes raw image observations, extracts 512-dimensional face embeddings, classifies detections against a reference identity corpus, and persists co-occurrence events with full data lineage into a queryable weighted relationship graph.

The architecture is designed around telemetry pipeline principles:
- **Idempotent ingestion**: duplicate observations are detected and skipped
- **Typed event lifecycle**: every observation moves through explicit pipeline stages
- **Data lineage**: every graph edge records model version, confidence scores, and timestamp
- **Replay capability**: historical events can be reprocessed with updated models
- **Fault isolation**: ML inference failures are contained by a circuit breaker

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Layer                             │
│  Next.js frontend (vis-network graph, dashboard, upload UI)     │
└────────────────────────────────┬────────────────────────────────┘
                                 │ HTTP
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Ingress / Edge Layer                         │
│  nginx ingress controller                                       │
│  • TLS termination           • Rate limit: 10 rps/IP           │
│  • /api/* path rewrite       • 300s proxy timeout (ML waits)   │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                            │
│                                                                 │
│  Middleware stack (ordered):                                    │
│  1. ObservabilityMiddleware — request ID, latency, Prometheus   │
│  2. RateLimitMiddleware     — Redis fixed-window per IP         │
│  3. CORSMiddleware          — frontend origin allowlist         │
│                                                                 │
│  Routers:                                                       │
│  ├── /metrics    — Prometheus scrape target                     │
│  ├── /admin/*    — Auth required: profile index, replay, bench  │
│  ├── /ingest/*   — Auth required: upload, batch, circuit-breaker│
│  ├── /jobs/*     — Job status polling                           │
│  ├── /graph/*    — Cached: summary, neighbors, ego, path        │
│  └── /profiles/* — Reference corpus management                  │
│                                                                 │
│  Core components:                                               │
│  ├── ThreadedConnectionPool  — min=2 max=10 DB connections      │
│  ├── Redis cache             — SCAN-based invalidation          │
│  ├── CircuitBreaker          — CLOSED/OPEN/HALF_OPEN            │
│  ├── JobManager              — Thread pool + Redis state        │
│  └── InsightFace (buffalo_l) — Lazy-loaded, ~350MB              │
└──────┬─────────────────┬─────────────────────────────┬──────────┘
       │                 │                             │
       ▼                 ▼                             ▼
┌────────────┐   ┌──────────────┐          ┌──────────────────────┐
│ PostgreSQL │   │    Redis     │          │   File Storage       │
│            │   │              │          │   (PVC / S3)         │
│ persons    │   │ Query cache  │          │   Uploaded images    │
│ embeddings │   │ Job state    │          │   (evidence photos)  │
│ edges      │   │ Rate limits  │          └──────────────────────┘
│ evidence   │   └──────────────┘
│ + pgvector │
└────────────┘
```

---

## Ingestion Pipeline Detail

```
POST /ingest/upload
         │
         ▼
  [1] Save to disk (UPLOADS_DIR)
         │
         ▼
  [2] Idempotency check
  ┌──── processed_images WHERE filename = ?
  │
  ├── EXISTS (no force): return ObservationEvent(stage=SKIPPED)
  │
  └── MISSING: continue
         │
         ▼
  [3] Load profile embeddings
  SELECT p.id, p.name, pp.embedding FROM person_profiles JOIN persons
  → list of (person_id, name, 512-dim float32 array)
         │
         ▼
  [4] Face detection [CircuitBreaker wraps this]
  InsightFace.get(img) → list of {bbox, normed_embedding}
  Sorted left-to-right by x-center
         │
  [CircuitBreaker: 5 failures in 60s → OPEN → 503]
         │
         ▼
  [5] For each detected face:
  cosine_similarity(face_emb, profile_emb) for all profiles
  → best_name, best_score, second_best_score
  → if score >= 0.45 AND margin >= 0.05: known person
  → else: create UNKNOWN_XXXX person
         │
         ▼
  [6] For each pair of known persons:
  upsert_edge(person_a_id, person_b_id)  ← UPDATE then INSERT
  store_edge_evidence(...)               ← model_version, confidence_a/b
         │
         ▼
  [7] Mark as processed
  INSERT INTO processed_images (filename)
         │
         ▼
  [8] Invalidate graph cache (if edges_created > 0)
  Redis SCAN graph:* → DEL
         │
         ▼
  return ObservationEvent(
    stage=PERSISTED,
    faces_detected=N,
    known_matches=K,
    edges_created=E,
    edge_provenance=[...],
    latency_ms={receive, pipeline, total}
  )
```

---

## Database Schema

### Tables

| Table | Purpose | Key Columns |
|---|---|---|
| `persons` | Identity registry | `id UUID`, `name TEXT UNIQUE` |
| `person_profiles` | Face embeddings per person | `person_id`, `embedding BYTEA`, `embedding_vec vector(512)` (pgvector, optional) |
| `uploads` | Processed image records | `image_path`, `status`, `created_at` |
| `faces` | Detected faces per upload | `upload_id`, `bbox JSONB`, `embedding BYTEA`, `matched_person_id`, `score` |
| `edges` | Co-occurrence graph (ordered pair) | `person_a_id < person_b_id`, `weight INT`, `updated_at` |
| `edge_evidence` | Lineage: one row per observation supporting an edge | `model_version TEXT`, `confidence_a/b FLOAT`, `processed_at` |
| `processed_images` | Idempotency ledger | `filename TEXT UNIQUE`, `processed_at` |

### Key Constraints

```sql
-- Edges are ordered pairs (prevents duplicate (A,B) and (B,A))
CONSTRAINT edges_ordered_pair CHECK (person_a_id < person_b_id)

-- Edge evidence references the edges composite PK (cascades on delete)
FOREIGN KEY (person_a_id, person_b_id) REFERENCES edges(person_a_id, person_b_id)
```

### Indexes

All foreign keys, timestamp columns, and the `model_version` column in
`edge_evidence` are indexed.  The `processed_images.filename` index makes
the idempotency check O(1).

---

## Observability Stack

### Prometheus Metrics

Collected at `/metrics`, scraped every 10s by `infra/monitoring/prometheus.yml`.

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total` | Counter | method, path (normalized), status_code |
| `http_request_duration_seconds` | Histogram | method, path |
| `in_flight_requests` | Gauge | — |
| `faces_detected_total` | Counter | — |
| `faces_matched_total` | Counter | — |
| `db_pool_checked_out` | Gauge | — |
| `db_pool_available` | Gauge | — |
| `cache_hits_total` | Counter | endpoint |
| `cache_misses_total` | Counter | endpoint |

**Path normalization:** UUIDs → `{uuid}`, numeric IDs → `{id}`, image filenames → `{filename}`.
Without this, every unique job ID would become a separate label value,
causing unbounded Prometheus cardinality.

### Alerting Rules (10 rules in `infra/monitoring/alerts.yml`)

Grouped by concern: availability, latency, ML inference, database, jobs, throughput.
Each alert has a `runbook` annotation with numbered investigation steps.

### Structured Logging

All log lines are JSON with `timestamp`, `level`, `request_id`, `method`, `path`,
`status_code`, `latency_ms`.  Compatible with Loki, CloudWatch, Datadog.

---

## Kubernetes Resources

| Resource | Config |
|---|---|
| `Namespace` | `connections` |
| `ConfigMap` | Non-sensitive config (log level, pool sizes, model name) |
| `Secret` (template) | `DATABASE_URL`, `REDIS_URL`, `API_KEY` |
| `Deployment` | 2 replicas, RollingUpdate (maxSurge=1, maxUnavailable=0), non-root UID 1000 |
| `Service` | ClusterIP, port 80→8000 |
| `HPA` | min=2 max=10, CPU 70%, memory 80%, scaleDown stabilization 300s |
| `Ingress` | nginx, /api/* rewrite, 300s timeout, 10 rps limit, TLS |
| `PVC` | ReadWriteMany, 10Gi (uploads; replace with S3 at scale) |

### Probe Design

```yaml
livenessProbe:  /health   # Always 200; degraded state in body. Never restarts pod on outage.
readinessProbe: /ready    # Returns 503 if Postgres/Redis down. Removes pod from rotation.
startupProbe:   /health   # 30 failures × 5s = 150s startup window for model download.
```

---

## Security

| Layer | Implementation |
|---|---|
| API authentication | `X-API-Key` header, FastAPI `APIKeyHeader` dependency on `/admin` and `/ingest` routers |
| Rate limiting | Redis fixed-window: 10/min ingest, 20/min admin, 100/min default |
| Container | Non-root user UID 1000, no capabilities, readOnlyRootFilesystem (planned) |
| SQL injection | Parameterized queries via psycopg2 (`%s` placeholders) throughout |
| Secrets | K8s Secrets (not ConfigMap); template at `infra/k8s/secrets-template.yaml` |
| TLS | Terminated at ingress; internal cluster traffic is HTTP |

---

## Technology Stack

| Component | Technology | Version |
|---|---|---|
| Backend API | FastAPI + uvicorn | 0.109+ |
| ML Model | InsightFace buffalo_l (ONNX Runtime) | 0.7.3+ |
| Database | PostgreSQL | 16 |
| Vector search | pgvector (optional migration) | 0.7+ |
| Cache / jobs | Redis | 7 |
| Frontend | Next.js + vis-network | 14 |
| Container | Docker + Compose | v2 |
| Orchestration | Kubernetes | 1.28+ |
| Metrics | Prometheus + Grafana | — |
| CI | GitHub Actions | — |
| Linting | ruff | 0.3+ |
