"""Prometheus metrics for Connections Social backend."""

from typing import Callable
from fastapi import APIRouter, Response
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)

from app.observability.config import config

# Create metrics router
metrics_router = APIRouter(tags=["metrics"])

# --- HTTP Metrics ---

# Total HTTP requests counter
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"]
)

# HTTP request duration histogram
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

# HTTP request errors counter
http_request_errors_total = Counter(
    "http_request_errors_total",
    "Total HTTP request errors",
    ["method", "path", "exception"]
)

# In-flight requests gauge
in_flight_requests = Gauge(
    "in_flight_requests",
    "Number of requests currently being processed"
)

# --- Application Metrics ---

# Active WebSocket connections (placeholder)
websocket_connections = Gauge(
    "websocket_connections_active",
    "Number of active WebSocket connections"
)

# Background job queue length (placeholder)
# TODO: Connect to actual queue if Redis queue is implemented
job_queue_length = Gauge(
    "job_queue_length",
    "Number of jobs in the background queue"
)

# Face processing metrics
faces_detected_total = Counter(
    "faces_detected_total",
    "Total faces detected in uploaded images"
)

faces_matched_total = Counter(
    "faces_matched_total",
    "Total faces successfully matched to known profiles"
)

images_processed_total = Counter(
    "images_processed_total",
    "Total images processed"
)

# Graph metrics (gauges updated periodically)
graph_persons_total = Gauge(
    "graph_persons_total",
    "Total persons in the social graph"
)

graph_edges_total = Gauge(
    "graph_edges_total",
    "Total edges in the social graph"
)


def normalize_path(path: str) -> str:
    """Normalize path for metrics to avoid high cardinality.

    Replaces dynamic path segments (UUIDs, IDs) with placeholders.
    """
    import re
    # Replace UUIDs
    path = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "{uuid}",
        path,
        flags=re.IGNORECASE
    )
    # Replace numeric IDs
    path = re.sub(r"/\d+(/|$)", r"/{id}\1", path)
    # Replace image filenames
    path = re.sub(r"/images/[^/]+\.(jpg|jpeg|png|gif)", r"/images/{filename}", path, flags=re.IGNORECASE)
    return path


def track_request(method: str, path: str, status_code: int, duration: float) -> None:
    """Track metrics for a completed request."""
    if not config.metrics_enabled:
        return

    normalized_path = normalize_path(path)

    http_requests_total.labels(
        method=method,
        path=normalized_path,
        status=str(status_code)
    ).inc()

    http_request_duration_seconds.labels(
        method=method,
        path=normalized_path
    ).observe(duration)


def track_error(method: str, path: str, exception_type: str) -> None:
    """Track metrics for a request error."""
    if not config.metrics_enabled:
        return

    normalized_path = normalize_path(path)

    http_request_errors_total.labels(
        method=method,
        path=normalized_path,
        exception=exception_type
    ).inc()


def track_in_flight(increment: bool) -> None:
    """Track in-flight requests."""
    if not config.metrics_enabled:
        return

    if increment:
        in_flight_requests.inc()
    else:
        in_flight_requests.dec()


def track_image_processing(faces_detected: int, faces_matched: int) -> None:
    """Track image processing metrics."""
    if not config.metrics_enabled:
        return

    images_processed_total.inc()
    faces_detected_total.inc(faces_detected)
    faces_matched_total.inc(faces_matched)


def update_graph_metrics(persons: int, edges: int) -> None:
    """Update graph metrics."""
    if not config.metrics_enabled:
        return

    graph_persons_total.set(persons)
    graph_edges_total.set(edges)


@metrics_router.get("/metrics")
async def get_metrics() -> Response:
    """Expose Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST
    )
