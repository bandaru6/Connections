# Future Work — Path to Production Scale

This document describes the engineering work required to take this system
from demo scale to production scale — with specific technology choices,
the problems they solve, and the order in which they'd be prioritized.

---

## Priority 1: Kafka for Guaranteed Delivery and Replay

**Current problem:**
- `/ingest/upload` is synchronous HTTP — if the client disconnects or the
  server restarts mid-processing, the event is lost.
- The `/admin/replay` endpoint is a manual workaround for what Kafka
  handles automatically via consumer group offsets.
- There's no backpressure mechanism — a traffic spike directly hits
  InsightFace inference without any buffering.

**Solution: Kafka-based ingestion pipeline**

```
HTTP Upload Handler  →  Kafka topic: raw-observations
                                │
                    ┌───────────▼────────────┐
                    │  Feature Extraction    │  (consumer group: extractors)
                    │  Service               │  GPU-accelerated, scalable
                    └───────────┬────────────┘
                                │
                    Kafka topic: embeddings
                                │
                    ┌───────────▼────────────┐
                    │  Classification        │  (consumer group: classifiers)
                    │  Service               │  pgvector ANN, low latency
                    └───────────┬────────────┘
                                │
                    Kafka topic: classified-events
                                │
                    ┌───────────▼────────────┐
                    │  Graph Writer          │  (consumer group: writers)
                    │  Service               │  Postgres upsert
                    └────────────────────────┘
```

**Why this is better:**
- At-least-once delivery with idempotent consumers (deduplication key already implemented)
- Replay = reset consumer group offset to any past offset
- Backpressure = Kafka consumer lag metrics → auto-scale consumers
- Independent scaling of each stage (GPU workers ≠ classifier replicas ≠ writers)

**Implementation complexity:** High. Requires Kafka cluster (managed via Confluent Cloud
or AWS MSK for production), schema registry (Avro or Protobuf for event schemas),
consumer group management, and monitoring for consumer lag.

---

## Priority 2: GPU-Accelerated Inference Workers

**Current problem:**
- InsightFace inference runs in the same process as the FastAPI API handlers.
  This couples the scaling of API capacity with the scaling of GPU/CPU capacity.
- If inference is slow (high CPU), the API thread pool is saturated and
  even fast endpoints (`/health`, `/graph/summary`) become slow.
- CPUs are the wrong hardware for neural network inference at scale.

**Solution: Separate GPU inference service**

```
FastAPI API pods (CPU, many replicas)
      │
      │ gRPC or HTTP call
      ▼
InsightFace Inference Service (GPU-accelerated, separate Deployment)
      │ returns: [embedding1, embedding2, ...]
      ▼
FastAPI continues: classification → edge write
```

**Infrastructure:**
- Separate Kubernetes Deployment with `nvidia.com/gpu: 1` resource request
- Separate HPA targeting GPU utilization (or custom metrics via KEDA)
- GPU node pool in the K8s cluster (AWS p3 instances, GCP A100 nodes)
- Model served via NVIDIA Triton Inference Server for batching and optimization

**Why this is better:**
- API pods scale independently from GPU workers
- GPU workers can batch multiple inference requests (8-32 images per GPU call
  is typically 10× more efficient than 1 image at a time)
- InsightFace with ONNX Runtime on GPU: ~10ms per image vs ~200ms on CPU

---

## Priority 3: pgvector at Scale

**Current problem:**
- O(n_profiles) Python cosine loop per detected face
- All embeddings loaded into RAM per request

**Current migration path:**
```bash
psql $DATABASE_URL -f infra/docker/migrate_pgvector.sql
python backend/scripts/migrate_embeddings.py
# Verify: GET /admin/benchmark
```

**At production scale:** IVFFlat is appropriate to ~1M vectors.
Above that, HNSW or a dedicated vector database:

| Scale | Technology | Why |
|---|---|---|
| <10K profiles | Python brute-force | Zero overhead, works fine |
| 10K–1M profiles | pgvector IVFFlat | O(sqrt(n)), stays in Postgres |
| >1M profiles | pgvector HNSW or Pinecone/Weaviate | Better recall-speed tradeoff, distributed |

**HNSW index (already in migrate_pgvector.sql as a comment):**
```sql
CREATE INDEX idx_person_profiles_embedding_hnsw
    ON person_profiles
    USING hnsw (embedding_vec vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

---

## Priority 4: Object Storage for Raw Images

**Current problem:**
- Uploaded images are stored on a PVC (NFS/EFS) mounted to all pods.
  This works but has limits: PVC capacity is fixed, NFS can become a
  throughput bottleneck at high ingest rates, and cross-region replication
  is not automatic.

**Solution:**
```python
# On upload: save to S3, store URI in DB
s3_client.upload_fileobj(file, bucket, key)
cur.execute("INSERT INTO uploads (image_s3_uri, ...) VALUES (%s, ...)", (s3_uri,))

# On serve: generate pre-signed URL (valid 1h, no public bucket needed)
url = s3_client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)
```

**Benefits:**
- Effectively unlimited storage capacity
- CDN integration for low-latency image serving
- Cross-region replication with S3 CRR
- Versioning and lifecycle policies (move old images to Glacier)
- No PVC to manage or resize

---

## Priority 5: Event Streaming to Frontend (WebSockets)

**Current problem:**
- The batch ingest status is polled via `GET /jobs/{job_id}`.
  This creates unnecessary HTTP traffic and adds perceived latency
  (the client doesn't know a job completed until the next poll interval).

**Solution: WebSocket push notifications**

```python
@app.websocket("/ws/jobs/{job_id}")
async def job_status_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()
    while True:
        job = job_manager.get_job(job_id)
        await websocket.send_json({"status": job.status, "progress": job.progress})
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            break
        await asyncio.sleep(0.5)
```

**For Tesla-scale real-time telemetry**, the frontend would subscribe to
a WebSocket channel that receives live vehicle telemetry events as they're
processed — no polling, events appear in real-time.

---

## Priority 6: Graph Database for Complex Traversals

**Current problem:**
- Graph queries (BFS ego network, shortest path) are implemented in Python
  by fetching edges from Postgres and building an in-memory graph.
- This is O(edges loaded) and doesn't scale to dense graphs with millions
  of edges.

**Solution:** Move graph storage to a purpose-built graph database:

| Option | Best for |
|---|---|
| **Neo4j** | Complex traversals, Cypher query language, mature ecosystem |
| **Amazon Neptune** | AWS-native, Gremlin + SPARQL, managed service |
| **Postgres + recursive CTEs** | Moderate graph complexity, stays in Postgres, no new infra |

At demo scale, Postgres with proper indexes and recursive CTEs (`WITH RECURSIVE`)
handles BFS to depth 3-4 efficiently. Neo4j becomes worth the operational cost
when graph traversals are the primary query pattern (millions of nodes, complex paths).

---

## Priority 7: Structured Event Schema with Schema Registry

**Current problem:**
- `ObservationEvent` is a Pydantic model checked at runtime.
- No cross-service schema contract — if the schema changes, consumers break silently.

**Solution:** Avro or Protobuf schemas registered in Confluent Schema Registry:

```protobuf
message ObservationEvent {
  string event_id = 1;
  string source_filename = 2;
  PipelineStage stage = 3;
  int32 faces_detected = 4;
  repeated EdgeProvenance edge_provenance = 5;
  map<string, double> latency_ms = 6;
}
```

**Benefits:**
- Schema evolution with backward/forward compatibility guarantees
- Strong typing across services (Python, Go, Rust consumers)
- Schema registry prevents producers from publishing incompatible events

---

## Summary Roadmap

| Phase | Work | Impact |
|---|---|---|
| **Now (done)** | Connection pool, Redis cache, circuit breaker, K8s manifests, HPA, Prometheus alerts, API key auth, rate limiting, pgvector migration path | Production-ready at demo scale |
| **Next (3 months)** | GPU inference service, S3 for images, pgvector HNSW, WebSocket progress | Production-ready at medium scale (~100K events/day) |
| **Future (6-12 months)** | Kafka pipeline, schema registry, graph database, KEDA autoscaling, multi-region | Tesla-scale telemetry (millions of events/day) |
