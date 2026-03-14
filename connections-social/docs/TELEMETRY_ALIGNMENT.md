# Telemetry Alignment — Tesla Autonomy ↔ This System

This document maps Tesla Autonomy Telemetry concepts to the equivalent implementation
in this project.  Use it as a reference during the technical interview.

---

## Event Lifecycle Mapping

| Tesla Autonomy Concept | This System | Implementation |
|---|---|---|
| **Sensor observation** | Uploaded image | `POST /ingest/upload`, saved to `UPLOADS_DIR` |
| **Feature extraction** | InsightFace detection → 512-dim embedding | `detect_faces()` in `routes/ingest.py` |
| **Object classification** | Cosine similarity match → identity label + confidence | `match_face_to_person()` |
| **Telemetry event record** | `ObservationEvent` Pydantic schema | `schemas/events.py` |
| **Event persistence** | `edge_evidence` row in PostgreSQL | `store_edge_evidence()` |
| **Model version tracking** | `model_version` field on every evidence row | `edge_evidence.model_version` column |
| **Deduplication / idempotency** | `processed_images` ledger table | `is_already_processed()` |
| **Replay / backfill** | `POST /admin/replay` — reprocess with current model | `_execute_replay_sync()` |
| **Event schema versioning** | `ObservationEvent.stage` enum (`PipelineStage`) | `schemas/events.py` |
| **Batch ingestion** | `POST /ingest/batch` → async job → poll `/jobs/{id}` | `jobs.py`, `routes/ingest.py` |

---

## Pipeline Stage Enum

`PipelineStage` in `schemas/events.py` models the typed lifecycle of a telemetry event:

```python
class PipelineStage(str, Enum):
    RECEIVED          = "RECEIVED"           # Observation saved, idempotency checked
    FEATURE_EXTRACTION = "FEATURE_EXTRACTION" # InsightFace running
    CLASSIFICATION    = "CLASSIFICATION"      # Cosine match running
    PERSISTED         = "PERSISTED"           # Edge + evidence written
    SKIPPED           = "SKIPPED"             # Duplicate — already in ledger
    FAILED            = "FAILED"              # Unrecoverable error
```

Tesla equivalent: a frame processing pipeline might have stages like
`RECEIVED → DECODED → ANNOTATED → CLASSIFIED → STORED → INDEXED`.

---

## Data Lineage Model

Every graph edge in this system has full provenance, equivalent to how a
telemetry event record would capture its processing context:

```sql
-- edge_evidence table: one row per observation that supports an edge
CREATE TABLE edge_evidence (
    person_a_id    UUID,
    person_b_id    UUID,
    upload_id      UUID,          -- which observation produced this
    model_version  TEXT,          -- buffalo_l, or future model name
    confidence_a   FLOAT,         -- match confidence for person_a
    confidence_b   FLOAT,         -- match confidence for person_b
    processed_at   TIMESTAMPTZ    -- when this event was written
);
```

Tesla equivalent: a detection event record would include `model_version`,
`confidence_score`, `sensor_id`, and `processing_timestamp` so that
detections can be filtered and replayed by model version.

---

## Idempotency Pattern

This system uses a **write-side deduplication ledger** (`processed_images`),
which is the same pattern used in real telemetry pipelines to prevent
duplicate processing of retried events:

```
Client sends image  →  check filename in processed_images
   ├── EXISTS: return ObservationEvent(stage=SKIPPED)
   └── MISSING: run pipeline, then INSERT into processed_images
```

The `force=True` parameter on `/ingest/upload` and `/ingest/folder` mirrors
a telemetry system's "replay" flag — delete the deduplication key and
reprocess.

**In a production telemetry system:** the deduplication key would typically
be a content hash (SHA256 of the frame) rather than a filename, to handle
identical frames uploaded under different names.

---

## Replay Capability

`POST /admin/replay` is this system's equivalent of a Kafka consumer group
being reset to an earlier offset and replayed:

1. Find all events processed in a date range (or by a specific model version)
2. Delete their `processed_images` entries (reset deduplication state)
3. Rerun the pipeline with the current model
4. Write new `edge_evidence` rows with the updated `model_version`

```bash
# Replay all events from January with the current model
POST /admin/replay?from_date=2024-01-01&to_date=2024-01-31

# Replay only events processed by an old model version
POST /admin/replay?model_version=buffalo_s
```

**Tesla equivalent:** reprocessing archived camera frames through an updated
perception model to regenerate annotations, metrics, or training labels.

---

## Observability Alignment

| Telemetry Concern | This System |
|---|---|
| Per-event latency breakdown | `latency_ms: {receive, pipeline, total}` in `ObservationEvent` |
| Pipeline throughput | `http_requests_total{path="/ingest/upload"}` counter |
| Inference availability | `CircuitBreakerOpen` alert (1m) + `/ingest/circuit-breaker/status` |
| Ingest stall detection | `IngestStalled` alert fires if rate=0 while service is up for 30m |
| Backpressure signal | `in_flight_requests` gauge + `HighInFlightRequests` alert at >20 |
| Resource utilization | `/system/info`: CPU%, RSS, pool utilization, embedding memory model |

---

## Scaling Bottleneck — The Embedding Search Problem

The current O(n) Python cosine loop is the same class of problem as
brute-force nearest-neighbor search in a large feature embedding space:

| Scale | Profiles | Python loop time | Memory per request |
|---|---|---|---|
| Demo | 50 | ~0.1ms | ~100KB |
| Small org | 500 | ~1ms | ~1MB |
| Medium | 5,000 | ~10ms | ~10MB |
| Large | 50,000 | ~100ms | ~100MB |
| Tesla-scale | 500,000+ | ~1,000ms | ~1GB — not viable |

The `GET /admin/benchmark` endpoint runs both the Python loop and a pgvector
IVFFlat query against live data, showing the actual measured speedup.

pgvector IVFFlat reduces this to O(sqrt(n) × probes) — sub-linear, with
recall controlled by the `ivfflat.probes` session variable.

**In a Tesla-scale telemetry system**, the equivalent would be ANN search
over millions of sensor event embeddings to find similar historical events
for debugging, clustering, or training data curation.

---

## Async Processing Pattern

The `/ingest/batch` → job ID → poll pattern is this system's lightweight
version of the async pipeline pattern:

```
POST /ingest/batch
    → create_job() → job_id returned immediately
    → run_async(job_id, worker) → thread pool

GET /jobs/{job_id}
    → poll Redis or in-memory store
    → returns {status, progress.current, progress.total, result}
```

**Tesla equivalent:** submitting a batch of frames for cloud-side processing
and polling for completion, rather than waiting synchronously for
potentially thousands of inference calls.

The natural evolution of this pattern is a Kafka-based job queue where
the batch submission publishes events to a topic and consumers process
them, reporting progress via a status topic.
