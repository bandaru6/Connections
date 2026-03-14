# Architecture Tradeoffs

Each significant design decision in this system involved a tradeoff.
This document records what was chosen, what was rejected, and why —
with concrete numbers where available.

---

## 1. Connection Pooling: ThreadedConnectionPool vs asyncpg

**Chosen:** `psycopg2.pool.ThreadedConnectionPool` (min=2, max=10)

**Rejected:** `asyncpg` with `async def` route handlers

**Why ThreadedConnectionPool:**
- Route handlers are `def` (synchronous), which is correct for CPU-bound
  operations that run in uvicorn's thread pool executor
- `asyncpg` requires fully async code through the entire call stack;
  retrofitting synchronous ML inference code (InsightFace) to be async
  adds complexity without benefit at this scale
- ThreadedConnectionPool is well-tested, simple, and eliminates the
  5-10ms per-request TCP handshake cost (measured at ~0.1ms checkout)

**The cost:** Synchronous DB calls block the OS thread they run on.
With uvicorn's default thread pool (`--workers` or thread pool executor),
this is fine at moderate concurrency. At very high concurrency (thousands
of simultaneous requests), asyncpg would allow the event loop to handle
other work while waiting for DB responses.

**At what scale would you switch:** When p99 DB query latency > 10ms AND
concurrent requests > thread pool size. Rule of thumb: asyncpg becomes
necessary above ~500 concurrent users.

---

## 2. Embedding Storage: BYTEA vs pgvector from the start

**Chosen:** BYTEA column with a pgvector migration path

**Rejected:** Start with `vector(512)` column directly

**Why BYTEA default:**
- pgvector requires a separate extension that isn't in the stock
  `postgres:16` Docker image. Using BYTEA means the system works
  out-of-the-box with standard PostgreSQL.
- At <1,000 profiles (typical demo/dev scale), the Python brute-force
  loop is imperceptibly fast (<1ms). Starting with pgvector would be
  premature optimization.
- The migration path is explicit and testable: `migrate_pgvector.sql`
  adds the column alongside BYTEA (not replacing it), so the old path
  continues working during migration.

**The cost:** At >10,000 profiles, the O(n) Python loop becomes the
bottleneck. The migration is a one-time operation and requires pgvector
to be installed on the Postgres server.

**Migration trigger:** `GET /admin/benchmark` shows brute-force latency
with actual profile count. Migrate when avg_ms > 20 OR profile_count > 10K.

---

## 3. Rate Limiting: Redis fixed-window vs slowapi (in-memory)

**Chosen:** Custom Redis fixed-window middleware

**Rejected:** `slowapi` (limits library, in-memory by default)

**Why Redis:**
- The K8s Deployment runs min=2 replicas. In-memory rate limits are per-pod:
  a client could hit both pods and get 2× the intended limit.
- Redis is already a required dependency (job state, query cache).
  Using it for rate limiting adds no new infrastructure dependency.
- Redis INCR is atomic — no race conditions between concurrent requests.
- Fails open: if Redis goes down, rate limiting disables rather than
  blocking all traffic (K8s probes would fail otherwise).

**The cost:** Redis is now on the critical path for every non-exempt request.
Adding one more network round-trip per request (~0.5ms locally).
Mitigated by the fail-open design.

**Sliding window vs fixed window:** Fixed window is simpler (INCR + EXPIRE)
and sufficient for burst protection. Sliding window (via Redis sorted sets)
is more accurate but adds complexity. At this scale, fixed window is correct.

---

## 4. Auth: Router-level dependency vs per-route decorator

**Chosen:** `dependencies=[Depends(require_api_key)]` on `include_router()`

**Rejected:** `@router.post("/upload", dependencies=[Depends(require_api_key)])`
on every individual route

**Why router-level:**
- All routes under `/admin` and `/ingest` need the same auth policy.
  Per-route decorators require every new route author to remember to add it.
- Router-level dependency is applied once in `main.py` — the auth policy
  is visible from a single location without reading every route file.
- FastAPI's dependency injection is idiomatic for this pattern.

**The cost:** Router-level auth applies to ALL routes under that prefix,
including any you might want to be public (e.g., `/ingest/circuit-breaker/status`).
Workaround: move public routes to a different router or override with `dependencies=[]`.

---

## 5. Async Jobs: Thread pool vs Celery/RQ

**Chosen:** Custom `JobManager` with `threading.Thread` + Redis state

**Rejected:** Celery with Redis broker, or RQ

**Why custom:**
- Celery is a substantial dependency (celery, kombu, billiard, vine) that
  requires a separate worker process. For a demo/interview project, the
  additional deployment complexity isn't justified.
- The thread pool approach works correctly for the use case (batch ingest
  is the only background workload) and is fully inspectable in the code.
- Job state is stored in Redis with an in-memory fallback, so it survives
  pod restarts if Redis is available.

**The cost:** No retries, no dead-letter queue, no task routing.
A failed job stays FAILED with an error message — there's no automatic
retry with exponential backoff.

**At what scale would you switch:** When you need retry semantics,
cross-service task distribution, or more than one type of background
workload. Celery (or Temporal for complex workflows) at that point.

---

## 6. Cache Invalidation: Proactive + TTL vs TTL-only

**Chosen:** TTL (60s summary, 30s neighbors) + proactive SCAN-based invalidation
when edges are created

**Rejected:** TTL-only

**Why proactive invalidation:**
- TTL-only means a user who uploads an image and immediately queries
  `/graph/summary` might see stale data for up to 60 seconds.
- Proactive invalidation on write (`invalidate_graph_cache()`) ensures
  the cache reflects the latest state within one TTL window.

**Why SCAN instead of KEYS:**
- `KEYS graph:*` blocks the Redis event loop while it scans all keys.
  In a large keyspace (millions of keys), this can cause 100ms+ latency
  spikes affecting all Redis users. SCAN is cursor-based and non-blocking.

**The cost:** SCAN-based invalidation makes multiple Redis round-trips
(one per cursor batch). In practice, with <1,000 graph cache keys,
this is a single SCAN call. At very large keyspaces, consider a separate
Redis keyspace for graph cache keys to make invalidation O(1) with DEL.

---

## 7. HPA CPU Target: 70% vs 90%

**Chosen:** 70% CPU utilization target

**Rejected:** 90% (common default)

**Why 70%:**
- InsightFace inference is CPU-bound. Kubernetes HPA takes 30-60 seconds
  to provision and start a new pod. During that window, traffic arrives
  at an already-saturated pod.
- At 90% target, the remaining 10% headroom is consumed before the new
  pod is ready, causing latency spikes.
- At 70% target, there's 30% headroom — enough to absorb ~2-3 minutes
  of moderate traffic growth before p99 latency degrades.

**The cost:** Slightly higher average resource cost (pods stay up at 70%
rather than scaling down to 50%). Acceptable tradeoff for latency stability.

**Tuning guidance:** Profile the actual inference time first. If buffalo_l
inference takes 500ms, and requests arrive at 2 req/s per core, 70%
leaves ~0.3 cores of headroom. Adjust the target based on your p99
latency SLA and expected traffic burst patterns.

---

## 8. Liveness vs Readiness Probe Design

**Chosen:**
- Liveness (`/health`): always 200, reports `status: degraded` in body
- Readiness (`/ready`): returns 503 if any dependency is down

**Rejected:** Using the same endpoint for both

**Why separate:**
- The liveness probe determines whether Kubernetes should restart the pod.
  If `/health` returned 503 during a Redis outage, Kubernetes would restart
  all pods — making the outage worse by losing warm DB connections and
  cached ML models.
- The readiness probe determines whether the pod should receive traffic.
  If `/ready` returns 503 during a Redis outage, the pod is removed from
  the load balancer rotation, protecting users from errors.
- Result: Redis outage → pods go unready but not restarted → traffic routes
  to any remaining healthy pods → Redis recovers → pods come back into rotation.

**The cost:** Slightly more complex probe configuration in the Deployment YAML.
Worth it for every production service.
