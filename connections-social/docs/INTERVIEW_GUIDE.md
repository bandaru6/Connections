# Interview Guide — Connections Pipeline

**Target:** Tesla Autonomy Telemetry internship, Rasika Bhave (AP Engineer)
**Format:** 45-minute technical: live coding + project deep-dive

---

## The Pitch (three versions)

### 30-Second Version (recruiter screen)

> "I built an event-driven data pipeline that ingests raw images as observation events, runs ML inference to extract 512-dimensional face embeddings, classifies detections against a reference corpus, and persists co-occurrence events with full data lineage — model version, confidence scores, processing timestamp. It's deployable on Kubernetes with autoscaling, circuit-breaker isolation for the ML path, Redis-backed caching, and a full Prometheus alerting stack. The design maps directly to how a telemetry pipeline processes sensor observations: receive, extract, classify, persist."

### 2-Minute Version (phone screen intro)

> "The project is a face-recognition-based relationship graph builder, but I architected it as a telemetry pipeline because that framing is more honest about what it actually does.
>
> Each uploaded image is an observation event. The pipeline has typed stages: RECEIVED, FEATURE_EXTRACTION, CLASSIFICATION, PERSISTED, SKIPPED, or FAILED. Each stage has measured latency. The final output isn't just a graph edge — it's a structured event record with the model version that produced it, confidence scores for each identity match, and a timestamp. That's data lineage, which is what makes replay and model versioning possible.
>
> On the infrastructure side: PostgreSQL with a connection pool (I measured the difference — 5-10ms per connection vs 0.1ms checkout from pool), Redis for query caching and distributed rate limiting across replicas, Kubernetes manifests with an HPA that scales on CPU (70% target because InsightFace inference is CPU-bound), and a circuit breaker that isolates ML failures so graph reads keep working during inference outages.
>
> The current bottleneck I'd fix at scale is the O(n) Python cosine similarity loop over all profile embeddings per request. I wrote the pgvector migration SQL and a benchmark endpoint that measures the difference with live data."

### 10-Minute Version (technical deep-dive)

Use this structure for the project walkthrough:

1. **Start with the problem statement** (1 min): "The naive approach — and what I had originally — was a simple upload-and-process API with per-request database connections and no observability. I'll walk through each thing I changed and why."

2. **Connection pooling** (1 min): Show `db.py`. "Before: `psycopg2.connect()` on every request — 5-10ms TCP handshake. After: `ThreadedConnectionPool` with lazy init and double-checked locking. The pool caps at 10 because `max_connections=100` divided by 10 replicas leaves headroom. You can see the utilization in real-time at `/system/info` or on the Grafana dashboard."

3. **The pipeline lifecycle** (2 min): Show `schemas/events.py` and the `ObservationEvent` return from `/ingest/upload`. "Every call returns a structured event with per-stage timing. This is what makes debugging production issues tractable — you can see whether latency is in the receive phase, the ML inference phase, or the DB write phase."

4. **Observability** (1 min): Hit `/metrics`. "Prometheus metrics with path normalization — I replace UUIDs and numeric IDs in metric labels so Prometheus doesn't accumulate unbounded cardinality. Ten alerting rules with runbooks. The pool exhaustion alert fires at 80% checked-out/max — that's the threshold where queue latency starts compounding."

5. **Circuit breaker** (1 min): Show circuit breaker code or hit `/ingest/circuit-breaker/status`. "CLOSED→OPEN→HALF_OPEN. When InsightFace fails 5 times in 60 seconds, the breaker opens and subsequent requests get 503 immediately — no 30-second hang while the request tries and fails. After 30 seconds, one test request goes through. If it succeeds, circuit closes."

6. **Scaling bottleneck + pgvector** (2 min): Hit `/admin/benchmark`. "Right now every ingest request loads all 512-float32 embeddings into Python RAM and runs cosine similarity in a loop. At 100 profiles this is ~0.2ms. At 10,000 it becomes ~20ms and starts dominating p99 latency. The fix is pgvector — I wrote the migration SQL and a Python migration script. The benchmark endpoint runs both methods against live data so you can see the actual speedup."

7. **K8s + HPA** (1 min): Show `infra/k8s/`. "The HPA targets 70% CPU, not 90%, because InsightFace is CPU-bound and scaling takes 30-60 seconds to provision new pods. At 90% you'd have latency spikes during that window. MaxUnavailable=0 in the rolling update strategy guarantees zero downtime deploys across both replicas."

8. **What I'd do next** (1 min): "Kafka for guaranteed delivery and natural replay, separate GPU-accelerated inference workers so I can scale API and ML independently, pgvector IVFFlat for ANN search. See `docs/FUTURE_WORK.md`."

---

## Anticipated Q&A

### Architecture

**Q: Why PostgreSQL instead of a time-series database for the events?**
> "For the current scale — hundreds to thousands of ingest events — PostgreSQL is fine and has the relational joins I need for graph queries. At Tesla's data volume, I'd separate the concerns: time-series events go to InfluxDB or TimescaleDB, the identity graph goes to a dedicated graph database or stays in Postgres with proper partitioning, and the raw embeddings go to a vector store like pgvector or Pinecone."

**Q: Why Redis for rate limiting instead of a library like slowapi?**
> "slowapi uses in-memory counters, which means each pod has its own count. With two replicas, a client could effectively get 2× the rate limit. Redis is shared across replicas so the limit is enforced correctly. The tradeoff is that if Redis goes down, I fail open — the rate limiter disables itself — because blocking all traffic due to a cache outage would be worse than temporarily allowing extra requests."

**Q: How does your circuit breaker differ from a retry loop?**
> "A retry loop is client-side and keeps sending requests to a failing service, which makes the overload worse. The circuit breaker is server-side state: after N failures it stops attempting the operation entirely and rejects requests fast. This gives the ML model time to recover (or gives ops time to investigate) without hammering a resource that's already failing. The HALF_OPEN state is the key — after the recovery timeout, exactly one probe request goes through. If it succeeds, we close. If it fails, we reset the timer."

**Q: Your HPA max is 10 — why not higher?**
> "It's bounded by `max_connections/pool_max`. PostgreSQL defaults to 100 max connections. With `pool_max=10` per pod, 10 pods × 10 connections = 100 — exactly at the limit. Going to 11 pods would exhaust the DB connection pool and start throwing connection errors. The fix at higher scale is PgBouncer as a connection pooler, which multiplexes many app connections onto fewer DB connections. With PgBouncer you could run 50 pods with pool_max=10 while Postgres sees only 20 connections."

### Implementation

**Q: Why ThreadedConnectionPool instead of asyncpg?**
> "The FastAPI endpoints that touch the DB are synchronous (they use `def`, not `async def`) because psycopg2 is synchronous. asyncpg requires fully async code throughout. ThreadedConnectionPool is the correct choice here — it handles concurrent access from multiple threads (uvicorn workers) safely. If I were rewriting, I'd use asyncpg with `async def` endpoints for true non-blocking DB access."

**Q: How does your cache invalidation work?**
> "TTL-based expiry as the primary mechanism — graph summary cached 60s, neighbors 30s. When an ingest creates new edges, I also do proactive invalidation: SCAN for keys matching `graph:*` and delete them. I use SCAN instead of KEYS because KEYS blocks Redis while it runs, which is a problem at large keyspaces. SCAN is cursor-based and non-blocking."

**Q: What happens if two requests try to create the same edge simultaneously?**
> "The `upsert_edge` function does UPDATE first, then INSERT only if the UPDATE found zero rows. Both operations happen inside a single DB transaction via `get_cursor()` (which commits on exit). PostgreSQL's row-level locking prevents the race — one transaction will block on the UPDATE while the other holds the lock, then see the updated weight and skip the INSERT."

**Q: Walk me through what happens when /ingest/upload receives a file.**
> "1. Save file to disk (UPLOADS_DIR). 2. Check `processed_images` table — if filename exists and force=False, return SKIPPED with a latency record. 3. Load all profile embeddings from DB (the O(n) path). 4. Run InsightFace detection via the circuit breaker. 5. For each detected face: cosine similarity against all profiles, apply MIN_MATCH_SCORE=0.45 + MIN_SCORE_MARGIN=0.05 thresholds. 6. For each pair of matched persons: upsert edge, write edge_evidence row with model version + confidences. 7. Mark filename in processed_images. 8. If edges were created, invalidate Redis graph cache. 9. Return ObservationEvent with stage=PERSISTED and per-stage latency_ms."

### Telemetry / Tesla Alignment

**Q: How does this relate to what Tesla actually does?**
> "The structural analogy is: camera frame = uploaded image, perception model output = InsightFace embedding, object classification = face-to-identity matching, telemetry event = ObservationEvent with full provenance. The engineering patterns are identical: idempotent ingestion with a deduplication key, structured event records with model version tracking, replay capability for reprocessing historical data with updated models, circuit-breaker isolation so one failing subsystem doesn't cascade, and an async job system for batch operations that would block the API thread."

**Q: What would you change to handle Tesla-scale data volumes?**
> "See docs/FUTURE_WORK.md for the full roadmap. Short version: Kafka for guaranteed delivery and natural event replay (replace the ad-hoc replay endpoint with a proper consumer group), separate GPU inference workers (current code mixes API handling and ML inference in the same process — at scale these have very different cost and scaling profiles), pgvector IVFFlat for ANN search at >10K profiles, and object storage (S3/GCS) for the raw images instead of a PVC."

---

## Numbers to Know

| Metric | Value | Source |
|---|---|---|
| Embedding size | 512 × float32 = 2048 bytes | `struct.pack("512f", ...)` |
| Profiles before memory becomes a concern | ~10,000 | 10K × 2048B ≈ 20MB per request |
| Brute-force matching complexity | O(n_profiles) per detected face | `match_face_to_person()` |
| pgvector IVFFlat complexity | O(sqrt(n) × probes) | See `migrate_pgvector.sql` |
| Pool checkout time | ~0.1ms (vs 5-10ms cold connect) | ThreadedConnectionPool |
| Redis cache TTL | summary=60s, neighbors=30s | `cache.py` |
| Circuit breaker threshold | 5 failures in 60s | `circuit_breaker.py` |
| HPA CPU target | 70% (not 90% — 30% headroom for scale-up lag) | `infra/k8s/hpa.yaml` |
| HPA max replicas | 10 (bounded by max_connections/pool_max = 100/10) | `infra/k8s/hpa.yaml` |
| Rate limit: ingest | 10 req/min (ML is CPU-bound) | `rate_limit.py` |
| Rate limit: default | 100 req/min | `rate_limit.py` |
| Unit tests | 56 (no services required) | `tests/test_unit.py` |
