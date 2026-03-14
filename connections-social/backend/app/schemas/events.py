"""Event schema definitions for the ingestion pipeline.

Why explicit schemas matter
───────────────────────────
Without a formal event schema, the pipeline is implicit: data flows through
function arguments and dict returns, and the structure of each stage is only
discoverable by reading the code.  Explicit Pydantic models make the pipeline
observable in three ways:

  1. API consumers get self-documenting response structures (visible in /docs).
  2. Each pipeline stage has a clear data contract — fields in, fields out.
  3. The event lifecycle is visible end-to-end: RECEIVED → FEATURE_EXTRACTION
     → CLASSIFICATION → PERSISTED, with per-stage latencies.

This maps directly to how Tesla's Autonomy Telemetry team thinks about data:
every observation (sensor reading, camera frame, radar ping) has a defined
schema, moves through a sequence of enrichment stages, and is stored with
full provenance — model version, confidence, timestamp, processing latency.

Tesla Autonomy Telemetry analogy
─────────────────────────────────
  ObservationEvent  →  A single telemetry record (e.g. one camera frame)
  DetectionResult   →  Feature extraction output (e.g. object bounding boxes)
  MatchResult       →  Classification result (e.g. identity / object class)
  PipelineStage     →  Named stage in the processing lifecycle
  EdgeProvenance    →  Data lineage record stored with every graph edge
  PipelineSummary   →  Aggregate outcome of a batch ingestion run
"""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline stage lifecycle
# ─────────────────────────────────────────────────────────────────────────────

class PipelineStage(str, Enum):
    """Named stages in the observation processing lifecycle.

    An observation event advances through these stages sequentially.
    Each stage transition is timestamped, enabling per-stage latency
    measurement and pinpointing where slowdowns occur.

    Tesla analog: stages map to the cloud-side processing steps after
    a vehicle uploads a telemetry batch — validation, feature extraction,
    model inference, database write, index update.
    """
    RECEIVED = "received"               # Raw input accepted, idempotency checked
    FEATURE_EXTRACTION = "feature_extraction"  # Face detection + embedding computed
    CLASSIFICATION = "classification"   # Embedding matched against reference corpus
    PERSISTED = "persisted"             # Edges + evidence written to database
    SKIPPED = "skipped"                 # Already processed (idempotency guard triggered)
    FAILED = "failed"                   # Unrecoverable error at any stage


# ─────────────────────────────────────────────────────────────────────────────
# Per-face detection result
# ─────────────────────────────────────────────────────────────────────────────

class BoundingBox(BaseModel):
    """Spatial location of a detected face in the source image."""
    x1: float = Field(..., description="Left edge (pixels)")
    y1: float = Field(..., description="Top edge (pixels)")
    x2: float = Field(..., description="Right edge (pixels)")
    y2: float = Field(..., description="Bottom edge (pixels)")
    area: float = Field(..., description="Bounding box area in pixels²")


class MatchResult(BaseModel):
    """Classification result: which identity did this face match?

    Analogous to a model inference output in a telemetry pipeline —
    the raw embedding is the 'sensor reading'; the match result is the
    'enriched classification' stored alongside it.
    """
    matched: bool = Field(..., description="True if a confident match was found")
    person_name: str = Field(
        ...,
        description="Matched identity name, or UNKNOWN_XXXX if unclassified"
    )
    confidence_score: float = Field(
        ...,
        ge=-1.0, le=1.0,
        description="Cosine similarity score between detected and reference embedding"
    )
    second_best_score: float = Field(
        default=0.0,
        description="Score of the second-best candidate (margin = score - second_best)"
    )
    margin: float = Field(
        ...,
        ge=0.0,
        description="Confidence margin: score minus second-best. Must exceed MIN_SCORE_MARGIN=0.05."
    )
    model_version: str = Field(
        default="buffalo_l",
        description="ML model version that produced this classification (data lineage)"
    )


class DetectionResult(BaseModel):
    """Feature extraction output for a single detected face.

    Captures everything about one face in the source image: where it is,
    how it was identified, and the latency of the detection step.
    """
    face_index: int = Field(..., description="Zero-based index of this face in the image")
    bounding_box: Optional[BoundingBox] = Field(
        None,
        description="Pixel coordinates of the detected face"
    )
    embedding_dim: int = Field(
        default=512,
        description="Dimensionality of the face embedding vector"
    )
    match: MatchResult = Field(..., description="Classification result for this face")


# ─────────────────────────────────────────────────────────────────────────────
# Edge provenance record
# ─────────────────────────────────────────────────────────────────────────────

class EdgeProvenance(BaseModel):
    """Data lineage for a co-occurrence edge written to the graph.

    Every edge in the graph is backed by at least one EdgeProvenance record,
    stored in the edge_evidence table.  This enables:
      - Replay: reprocess images through a new model and regenerate edges
      - Audit: trace any edge back to the exact image and model version
      - Drift detection: compare confidence distributions across model versions

    Tesla analog: this is equivalent to storing the sensor calibration version
    and confidence score alongside every telemetry event — you can always
    trace an annotation back to the exact model and data that produced it.
    """
    person_a: str = Field(..., description="First person in the co-occurrence")
    person_b: str = Field(..., description="Second person in the co-occurrence")
    confidence_a: float = Field(..., description="Match confidence for person_a")
    confidence_b: float = Field(..., description="Match confidence for person_b")
    model_version: str = Field(..., description="ML model that produced both matches")
    new_edge: bool = Field(..., description="True if this is a new edge, False if weight incremented")
    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this edge was written"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Top-level observation event
# ─────────────────────────────────────────────────────────────────────────────

class ObservationEvent(BaseModel):
    """Full lifecycle record for a single ingested observation (image).

    This is the primary output of the /ingest/upload endpoint.  It captures
    the complete journey of one observation through the pipeline, from the
    moment it was received to the moment its derived events were persisted.

    Design principle: a single ObservationEvent should contain enough
    information to:
      1. Reproduce the processing (source filename + model version)
      2. Audit the outcome (stage, detections, matches, edges)
      3. Diagnose latency (per-stage timing breakdown)
      4. Replay if needed (idempotency key + model version in each MatchResult)
    """
    # Schema versioning — allows consumers to handle evolving event contracts
    schema_version: str = Field(
        default="1.0",
        description=(
            "Event schema version. Increment when adding breaking fields. "
            "Consumers should check this before deserializing."
        )
    )

    # Identity and provenance
    event_id: str = Field(..., description="UUID for this observation event")
    source_filename: str = Field(..., description="Original filename (idempotency key)")
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the observation was received"
    )

    # Pipeline lifecycle
    stage: PipelineStage = Field(..., description="Final stage reached by this event")
    skipped_reason: Optional[str] = Field(
        None,
        description="If stage=SKIPPED, explains why (e.g. 'already_processed')"
    )
    error_message: Optional[str] = Field(
        None,
        description="If stage=FAILED, the error that caused the failure"
    )

    # Feature extraction results
    faces_detected: int = Field(
        default=0,
        description="Total faces detected by the face detection model"
    )
    detections: List[DetectionResult] = Field(
        default_factory=list,
        description="Per-face detection and classification results"
    )

    # Persistence results
    known_matches: int = Field(
        default=0,
        description="Faces matched to a known identity in the reference corpus"
    )
    unknown_faces: int = Field(
        default=0,
        description="Faces that did not match any known identity (assigned UNKNOWN_XXXX)"
    )
    edges_created: int = Field(
        default=0,
        description="New or updated co-occurrence edges written to the graph"
    )
    edge_provenance: List[EdgeProvenance] = Field(
        default_factory=list,
        description="Lineage records for each edge created/updated"
    )

    # Latency breakdown (milliseconds per stage)
    latency_ms: dict = Field(
        default_factory=dict,
        description=(
            "Per-stage latency in milliseconds. Keys: receive, feature_extraction, "
            "classification, persistence, total"
        ),
        example={
            "receive": 0.5,
            "feature_extraction": 850.2,
            "classification": 12.4,
            "persistence": 8.1,
            "total": 871.2
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# Batch pipeline summary
# ─────────────────────────────────────────────────────────────────────────────

class PipelineSummary(BaseModel):
    """Aggregate outcome of a batch ingestion run (returned by /ingest/folder
    and embedded in async job results from /ingest/batch).

    Provides the operational metrics needed to assess pipeline health after
    a batch run: throughput, match rate, error rate, and overall latency.
    """
    total_images: int = Field(..., description="Total images submitted")
    processed: int = Field(..., description="Images successfully processed")
    skipped: int = Field(..., description="Images skipped (already in ledger)")
    failed: int = Field(..., description="Images that failed processing")

    total_faces_detected: int = Field(default=0)
    total_known_matches: int = Field(default=0)
    total_unknown_faces: int = Field(default=0)
    total_edges_created: int = Field(default=0)

    match_rate: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="Fraction of detected faces that matched a known identity"
    )
    error_rate: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="Fraction of images that failed processing"
    )

    total_latency_ms: float = Field(
        default=0.0,
        description="Wall-clock time for the entire batch in milliseconds"
    )
    avg_latency_per_image_ms: float = Field(
        default=0.0,
        description="Average processing time per image in milliseconds"
    )

    model_version: str = Field(
        default="buffalo_l",
        description="ML model version used for all classifications in this batch"
    )
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @classmethod
    def from_events(cls, events: List[ObservationEvent], total_ms: float) -> "PipelineSummary":
        """Aggregate a list of ObservationEvents into a batch summary."""
        processed = sum(1 for e in events if e.stage == PipelineStage.PERSISTED)
        skipped = sum(1 for e in events if e.stage == PipelineStage.SKIPPED)
        failed = sum(1 for e in events if e.stage == PipelineStage.FAILED)
        total_faces = sum(e.faces_detected for e in events)
        total_matched = sum(e.known_matches for e in events)
        total_unknown = sum(e.unknown_faces for e in events)
        total_edges = sum(e.edges_created for e in events)

        match_rate = (total_matched / total_faces) if total_faces > 0 else 0.0
        error_rate = (failed / len(events)) if events else 0.0
        avg_ms = (total_ms / len(events)) if events else 0.0

        return cls(
            total_images=len(events),
            processed=processed,
            skipped=skipped,
            failed=failed,
            total_faces_detected=total_faces,
            total_known_matches=total_matched,
            total_unknown_faces=total_unknown,
            total_edges_created=total_edges,
            match_rate=match_rate,
            error_rate=error_rate,
            total_latency_ms=total_ms,
            avg_latency_per_image_ms=avg_ms,
        )
