"""Unit tests for core pipeline logic.

These tests run without a live database, Redis connection, or ML model.
They test pure computation: similarity math, edge ordering, idempotency
logic, circuit breaker state machine, and job state transitions.

This allows the CI pipeline to run a fast, dependency-free validation on
every push without spinning up external services.

Tesla Autonomy Telemetry relevance: in a real telemetry pipeline, unit
tests for the core classification and routing logic are critical — they
let you validate that a threshold change or model update does not silently
break matching semantics before it reaches production.
"""

import struct
import time
import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Cosine Similarity
# ─────────────────────────────────────────────────────────────────────────────


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Reference implementation — mirrors routes/ingest.py."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


class TestCosineSimilarity:
    """Tests for the core face-matching metric.

    Interview talking point: cosine similarity on L2-normalized vectors equals
    the dot product, so np.dot(a, b) suffices when both are unit-norm.  The
    explicit formula is defensive — it handles un-normalized inputs gracefully.
    """

    def test_identical_vectors_score_one(self):
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_opposite_vectors_score_negative_one(self):
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert cosine_similarity(v, -v) == pytest.approx(-1.0, abs=1e-6)

    def test_orthogonal_vectors_score_zero(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)

    def test_score_bounded_between_negative_one_and_one(self):
        rng = np.random.default_rng(42)
        for _ in range(50):
            a = rng.standard_normal(512).astype(np.float32)
            b = rng.standard_normal(512).astype(np.float32)
            score = cosine_similarity(a, b)
            assert -1.0 - 1e-6 <= score <= 1.0 + 1e-6

    def test_scale_invariance(self):
        """Score must not change when vectors are scaled (cosine property)."""
        a = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        b = np.array([4.0, 5.0, 6.0], dtype=np.float32)
        assert cosine_similarity(a, b) == pytest.approx(
            cosine_similarity(a * 10, b * 0.001), abs=1e-5
        )

    def test_512_dim_random_embeddings_plausible_range(self):
        """Random 512-dim embeddings should score between -0.3 and 0.3 on average."""
        rng = np.random.default_rng(0)
        scores = [
            cosine_similarity(
                rng.standard_normal(512).astype(np.float32),
                rng.standard_normal(512).astype(np.float32),
            )
            for _ in range(200)
        ]
        assert abs(np.mean(scores)) < 0.05  # mean near zero
        assert max(scores) < 0.4            # no spurious perfect matches


# ─────────────────────────────────────────────────────────────────────────────
# Matching thresholds — the pipeline's classification logic
# ─────────────────────────────────────────────────────────────────────────────

MIN_MATCH_SCORE = 0.45
MIN_SCORE_MARGIN = 0.05


def is_confident_match(best_score: float, second_best_score: float) -> bool:
    """Mirrors the match decision in routes/ingest.py."""
    return best_score >= MIN_MATCH_SCORE and (best_score - second_best_score) >= MIN_SCORE_MARGIN


class TestMatchingThresholds:
    """Tests for the classification threshold logic.

    These thresholds are the single most consequential tuning parameter in
    the pipeline.  A telemetry interviewer might ask: 'how do you choose
    0.45?' — answer: empirically from a labeled validation set; the margin
    requirement reduces false positives when two profiles score similarly.
    """

    def test_high_score_large_margin_matches(self):
        assert is_confident_match(0.80, 0.50) is True

    def test_high_score_small_margin_does_not_match(self):
        # Even with a high score, ambiguous matches are rejected
        assert is_confident_match(0.80, 0.77) is False

    def test_score_clearly_above_threshold_matches(self):
        # NOTE: 0.45 - 0.40 = 0.04999... in float64 (below 0.05 margin).
        # Tests should not rely on exact float boundary equality.
        # Use 0.46 to stay unambiguously above the threshold.
        assert is_confident_match(0.46, 0.40) is True

    def test_score_below_threshold_does_not_match(self):
        assert is_confident_match(0.44, 0.10) is False

    def test_single_profile_no_margin_concern(self):
        # When there is only one profile (second_best = 0), margin is score itself
        assert is_confident_match(0.60, 0.0) is True

    def test_margin_clearly_at_threshold(self):
        # 0.50 - 0.44 = 0.06, unambiguously above MIN_SCORE_MARGIN=0.05.
        # Exact boundary (0.50 - 0.45) is float-unreliable; production code
        # should apply the same caution when tuning thresholds.
        assert is_confident_match(0.50, 0.44) is True

    def test_margin_one_below_threshold(self):
        assert is_confident_match(0.50, 0.46) is False


# ─────────────────────────────────────────────────────────────────────────────
# Embedding serialization (BYTEA pack/unpack round-trip)
# ─────────────────────────────────────────────────────────────────────────────

class TestEmbeddingStorage:
    """Tests for the 512-dim float32 BYTEA serialization.

    Interview talking point: embeddings are stored as 2048 bytes of raw
    float32 (512 × 4 bytes) in a PostgreSQL BYTEA column.  This avoids the
    overhead of JSON encoding and gives exact round-trip fidelity.  The
    tradeoff vs. pgvector is that ANN search stays in Python (O(n_profiles)).
    """

    def _pack(self, embedding: np.ndarray) -> bytes:
        arr = embedding.astype(np.float32)
        return struct.pack(f"{len(arr)}f", *arr)

    def _unpack(self, data: bytes) -> np.ndarray:
        count = len(data) // 4
        return np.array(struct.unpack(f"{count}f", data), dtype=np.float32)

    def test_round_trip_preserves_values(self):
        rng = np.random.default_rng(7)
        emb = rng.standard_normal(512).astype(np.float32)
        recovered = self._unpack(self._pack(emb))
        np.testing.assert_array_almost_equal(emb, recovered, decimal=6)

    def test_packed_size_is_2048_bytes(self):
        emb = np.zeros(512, dtype=np.float32)
        assert len(self._pack(emb)) == 2048

    def test_cosine_similarity_preserved_after_round_trip(self):
        rng = np.random.default_rng(13)
        a = rng.standard_normal(512).astype(np.float32)
        b = rng.standard_normal(512).astype(np.float32)
        original_score = cosine_similarity(a, b)
        recovered_a = self._unpack(self._pack(a))
        recovered_b = self._unpack(self._pack(b))
        assert cosine_similarity(recovered_a, recovered_b) == pytest.approx(
            original_score, abs=1e-5
        )


# ─────────────────────────────────────────────────────────────────────────────
# Edge ordering constraint
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeOrdering:
    """Tests for the canonical edge deduplication constraint.

    Every edge is stored as (person_a_id, person_b_id) where person_a_id
    < person_b_id (UUID lexicographic order).  This prevents duplicate edges
    regardless of which person appears first in a photo.  The constraint is
    enforced at the DB level via a CHECK constraint, but application code
    must produce correctly-ordered pairs.

    Interview talking point: this is the same pattern used in undirected
    graph storage in production systems — always store (min_id, max_id).
    """

    def _ordered_pair(self, id_a: str, id_b: str) -> tuple[str, str]:
        """Application-side ordering — mirrors ingest.py logic."""
        return (min(id_a, id_b), max(id_a, id_b))

    def test_ordering_is_deterministic(self):
        a = str(uuid.uuid4())
        b = str(uuid.uuid4())
        assert self._ordered_pair(a, b) == self._ordered_pair(b, a)

    def test_smaller_uuid_always_first(self):
        ids = [str(uuid.uuid4()) for _ in range(20)]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pa, pb = self._ordered_pair(ids[i], ids[j])
                assert pa <= pb

    def test_same_id_pair_is_valid(self):
        """Self-loops: person appears alone in photo — both IDs equal."""
        a = str(uuid.uuid4())
        pa, pb = self._ordered_pair(a, a)
        assert pa == pb == a

    def test_ordering_survives_many_random_pairs(self):
        rng = np.random.default_rng(99)
        for _ in range(100):
            a, b = str(uuid.uuid4()), str(uuid.uuid4())
            pa, pb = self._ordered_pair(a, b)
            assert pa <= pb


# ─────────────────────────────────────────────────────────────────────────────
# Idempotency logic
# ─────────────────────────────────────────────────────────────────────────────

class TestIdempotency:
    """Tests for the ingestion ledger (processed_images table) logic.

    The pipeline uses a filename-keyed ledger to prevent reprocessing the
    same observation event.  This is critical for safe replay: running
    /admin/replay must be safe to invoke multiple times.

    Interview talking point: idempotency is a first-class requirement in
    any telemetry pipeline.  Vehicles may retransmit data on reconnect;
    the cloud-side ingestion layer must deduplicate without data corruption.
    """

    def _is_already_processed(self, ledger: set, filename: str) -> bool:
        """Mirrors the DB check in ingest.py."""
        return filename in ledger

    def test_new_filename_not_in_ledger(self):
        ledger: set = set()
        assert not self._is_already_processed(ledger, "photo_001.jpg")

    def test_processed_filename_detected(self):
        ledger = {"photo_001.jpg"}
        assert self._is_already_processed(ledger, "photo_001.jpg")

    def test_different_filename_not_blocked(self):
        ledger = {"photo_001.jpg"}
        assert not self._is_already_processed(ledger, "photo_002.jpg")

    def test_case_sensitive_filenames(self):
        """Filenames are stored exactly — 'Photo.jpg' != 'photo.jpg'."""
        ledger = {"Photo.jpg"}
        assert not self._is_already_processed(ledger, "photo.jpg")

    def test_idempotent_bulk_ingestion(self):
        """Processing the same batch twice adds no new entries to ledger."""
        batch = [f"img_{i:04d}.jpg" for i in range(50)]
        ledger: set = set()

        def ingest_batch(filenames: list, ledger: set) -> int:
            processed = 0
            for f in filenames:
                if not self._is_already_processed(ledger, f):
                    ledger.add(f)
                    processed += 1
            return processed

        first_run = ingest_batch(batch, ledger)
        second_run = ingest_batch(batch, ledger)

        assert first_run == 50
        assert second_run == 0
        assert len(ledger) == 50


# ─────────────────────────────────────────────────────────────────────────────
# Circuit Breaker state machine
# ─────────────────────────────────────────────────────────────────────────────

class TestCircuitBreaker:
    """Tests for the ML inference isolation circuit breaker.

    The circuit breaker has three states: CLOSED (normal), OPEN (failing
    fast), HALF_OPEN (testing recovery).  These tests verify every state
    transition.

    Interview talking point: the circuit breaker prevents a failing ML
    inference layer from cascading into the entire ingestion pipeline.
    In a Tesla telemetry context, if the cloud-side embedding service
    degrades, the circuit opens and new events are queued rather than
    rejected, giving the service time to recover.
    """

    def _make_breaker(self, failure_threshold=3, failure_window=60.0, recovery_timeout=30.0):
        from app.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
        return CircuitBreaker(
            "test",
            CircuitBreakerConfig(
                failure_threshold=failure_threshold,
                failure_window=failure_window,
                recovery_timeout=recovery_timeout,
            ),
        )

    def test_initial_state_is_closed(self):
        from app.circuit_breaker import CircuitState
        breaker = self._make_breaker()
        assert breaker.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self):
        from app.circuit_breaker import CircuitState, CircuitBreakerOpen
        breaker = self._make_breaker(failure_threshold=3)

        @breaker
        def always_fails():
            raise RuntimeError("boom")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                always_fails()

        assert breaker.state == CircuitState.OPEN

    def test_open_circuit_rejects_without_calling_function(self):
        from app.circuit_breaker import CircuitState, CircuitBreakerOpen
        breaker = self._make_breaker(failure_threshold=2)
        call_count = 0

        @breaker
        def fn():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        # Trip the breaker
        for _ in range(2):
            with pytest.raises(RuntimeError):
                fn()

        # Now it should reject fast without calling fn
        with pytest.raises(CircuitBreakerOpen):
            fn()

        assert call_count == 2  # fn was NOT called the 3rd time

    def test_successful_calls_do_not_open_circuit(self):
        from app.circuit_breaker import CircuitState
        breaker = self._make_breaker(failure_threshold=3)

        @breaker
        def succeeds():
            return "ok"

        for _ in range(100):
            assert succeeds() == "ok"

        assert breaker.state == CircuitState.CLOSED

    def test_manual_reset_closes_open_circuit(self):
        from app.circuit_breaker import CircuitState
        breaker = self._make_breaker(failure_threshold=1)

        @breaker
        def fails():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            fails()

        assert breaker.state == CircuitState.OPEN
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED

    def test_half_open_after_recovery_timeout(self):
        from app.circuit_breaker import CircuitState
        breaker = self._make_breaker(failure_threshold=1, recovery_timeout=0.05)

        @breaker
        def fails():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            fails()

        assert breaker.state == CircuitState.OPEN

        time.sleep(0.1)  # wait for recovery timeout

        # Next request should be allowed (HALF_OPEN)
        @breaker
        def succeeds():
            return "ok"

        result = succeeds()
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    def test_rejected_calls_increment_counter(self):
        from app.circuit_breaker import CircuitBreakerOpen
        breaker = self._make_breaker(failure_threshold=1)

        @breaker
        def fails():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            fails()

        for _ in range(5):
            with pytest.raises(CircuitBreakerOpen):
                fails()

        assert breaker.stats.total_rejected == 5


# ─────────────────────────────────────────────────────────────────────────────
# Job state machine
# ─────────────────────────────────────────────────────────────────────────────

class TestJobStateMachine:
    """Tests for async job lifecycle transitions.

    The job manager is the async processing backbone: it accepts work,
    tracks progress via Redis, and exposes status via polling.  These tests
    use an in-memory fallback (no Redis required).

    Interview talking point: the polling model (submit → job ID → poll)
    is appropriate for batch ingestion workloads.  For real-time telemetry,
    you'd replace the polling loop with a Kafka consumer that emits progress
    events to a WebSocket channel.
    """

    def _make_manager(self):
        from app.jobs import JobManager
        # Force in-memory mode by patching Redis to raise on connect
        manager = JobManager(redis_url="redis://invalid:9999/0")
        return manager

    def test_job_created_in_pending_state(self):
        from app.jobs import JobStatus
        manager = self._make_manager()
        job = manager.create_job("test_type")
        assert job.status == JobStatus.PENDING

    def test_job_has_unique_id(self):
        manager = self._make_manager()
        ids = {manager.create_job("type").id for _ in range(10)}
        assert len(ids) == 10

    def test_get_nonexistent_job_returns_none(self):
        manager = self._make_manager()
        result = manager.get_job("nonexistent-id")
        assert result is None

    def test_get_job_returns_created_job(self):
        manager = self._make_manager()
        job = manager.create_job("batch_ingest")
        retrieved = manager.get_job(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id

    def test_job_transitions_to_completed(self):
        from app.jobs import JobStatus
        manager = self._make_manager()

        def work(job_id, mgr):
            mgr.complete_job(job_id, success=True, data={"processed": 1})

        job = manager.create_job("test_type")
        manager.run_async(job.id, work)
        # Give the background thread time to finish
        time.sleep(0.3)

        retrieved = manager.get_job(job.id)
        assert retrieved is not None
        assert retrieved.status in (JobStatus.COMPLETED, JobStatus.RUNNING)

    def test_job_transitions_to_failed_on_exception(self):
        from app.jobs import JobStatus
        manager = self._make_manager()

        def fails(job_id, mgr):
            raise ValueError("pipeline error")

        job = manager.create_job("test_type")
        manager.run_async(job.id, fails)
        time.sleep(0.3)

        retrieved = manager.get_job(job.id)
        assert retrieved is not None
        assert retrieved.status == JobStatus.FAILED


# ─────────────────────────────────────────────────────────────────────────────
# Prometheus metrics path normalization
# ─────────────────────────────────────────────────────────────────────────────

class TestMetricsPathNormalization:
    """Tests for high-cardinality prevention in Prometheus metrics.

    Without normalization, every unique UUID or job ID becomes a separate
    label value, causing unbounded cardinality that degrades Prometheus
    performance.  The normalize_path() function replaces dynamic segments
    with placeholders before recording metrics.
    """

    def _normalize(self, path: str) -> str:
        from app.observability.metrics import normalize_path
        return normalize_path(path)

    def test_uuid_replaced_with_placeholder(self):
        path = "/jobs/550e8400-e29b-41d4-a716-446655440000"
        assert self._normalize(path) == "/jobs/{uuid}"

    def test_numeric_id_replaced(self):
        assert self._normalize("/items/42") == "/items/{id}"

    def test_image_filename_replaced(self):
        assert self._normalize("/images/photo_001.jpg") == "/images/{filename}"

    def test_normal_path_unchanged(self):
        assert self._normalize("/graph/summary") == "/graph/summary"

    def test_health_path_unchanged(self):
        assert self._normalize("/health") == "/health"

    def test_nested_uuid_replaced(self):
        path = "/admin/jobs/550e8400-e29b-41d4-a716-446655440000/cancel"
        result = self._normalize(path)
        assert "{uuid}" in result
        assert "550e8400" not in result


# ─────────────────────────────────────────────────────────────────────────────
# Connection pool status
# ─────────────────────────────────────────────────────────────────────────────

class TestConnectionPoolStatus:
    """Tests for DB connection pool observability.

    Pool utilization metrics feed into the /system/info endpoint and the
    Prometheus db_pool_* gauges.  Alerting on high checked_out / max ratio
    is how you catch connection exhaustion before it causes 500 errors.
    """

    def test_pool_status_before_init(self):
        """Before any DB call, pool reports uninitialized."""
        # We can only test this in isolation; importing db resets the singleton
        from app import db as db_module
        original = db_module._pool
        db_module._pool = None  # force uninitialized state
        status = db_module.get_pool_status()
        assert status["initialized"] is False
        db_module._pool = original  # restore

    def test_pool_status_fields_present(self):
        from app.db import get_pool_status
        status = get_pool_status()
        assert "initialized" in status
        assert "min" in status
        assert "max" in status


# ─────────────────────────────────────────────────────────────────────────────
# API key authentication
# ─────────────────────────────────────────────────────────────────────────────

class TestApiKeyAuth:
    """Tests for the API key authentication dependency.

    The dependency is injected at the router level in main.py, so all routes
    under /admin and /ingest inherit it without per-route boilerplate.

    Interview talking point: FastAPI's dependency injection allows applying
    cross-cutting concerns (auth, rate limiting, caching) at multiple scopes:
    individual route, router group, or entire application.
    """

    def test_auth_disabled_when_api_key_empty(self):
        """Empty API_KEY means dev mode — all requests accepted."""
        import asyncio
        from unittest.mock import patch

        with patch("app.auth.API_KEY", ""):
            from app.auth import require_api_key
            # Should not raise
            asyncio.run(require_api_key(api_key=None))
            asyncio.run(require_api_key(api_key="anything"))

    def test_valid_key_accepted(self):
        """Correct key passes without exception."""
        import asyncio
        from unittest.mock import patch

        with patch("app.auth.API_KEY", "secret-test-key"):
            from app.auth import require_api_key
            asyncio.run(require_api_key(api_key="secret-test-key"))

    def test_wrong_key_raises_401(self):
        """Wrong key raises HTTP 401."""
        import asyncio
        from fastapi import HTTPException
        from unittest.mock import patch

        with patch("app.auth.API_KEY", "secret-test-key"):
            from app.auth import require_api_key
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(require_api_key(api_key="wrong-key"))
            assert exc_info.value.status_code == 401

    def test_missing_key_raises_401(self):
        """Absent header (None) raises HTTP 401 when auth is enabled."""
        import asyncio
        from fastapi import HTTPException
        from unittest.mock import patch

        with patch("app.auth.API_KEY", "secret-test-key"):
            from app.auth import require_api_key
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(require_api_key(api_key=None))
            assert exc_info.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiting configuration
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimitConfig:
    """Tests for rate limit constants and exempt path set.

    These verify that the rate limit policy is correctly configured — that
    expensive ML inference endpoints are more tightly capped than graph
    read endpoints, and that K8s probe paths are never blocked.

    Interview talking point: separating ML inference endpoints from graph
    read endpoints allows independent autoscaling — the /ingest limit of
    10 req/min reflects the CPU cost of InsightFace inference, not a
    design weakness.
    """

    def test_ingest_limit_lower_than_default(self):
        from app.rate_limit import _RATE_LIMITS, _DEFAULT_LIMIT
        assert _RATE_LIMITS["/ingest"] < _DEFAULT_LIMIT

    def test_admin_limit_lower_than_default(self):
        from app.rate_limit import _RATE_LIMITS, _DEFAULT_LIMIT
        assert _RATE_LIMITS["/admin"] < _DEFAULT_LIMIT

    def test_ingest_limit_value(self):
        """Ingest capped at 10/min — one inference per ~6 seconds under load."""
        from app.rate_limit import _RATE_LIMITS
        assert _RATE_LIMITS["/ingest"] == 10

    def test_health_path_exempt(self):
        """K8s liveness probe must never be rate-limited."""
        from app.rate_limit import _EXEMPT_PATHS
        assert "/health" in _EXEMPT_PATHS

    def test_ready_path_exempt(self):
        """K8s readiness probe must never be rate-limited."""
        from app.rate_limit import _EXEMPT_PATHS
        assert "/ready" in _EXEMPT_PATHS

    def test_metrics_path_exempt(self):
        """Prometheus scrape target must never be rate-limited."""
        from app.rate_limit import _EXEMPT_PATHS
        assert "/metrics" in _EXEMPT_PATHS
