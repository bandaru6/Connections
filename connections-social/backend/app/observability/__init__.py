"""Observability module for Connections Social backend.

Provides:
- Structured JSON logging
- Prometheus metrics
- Optional OpenTelemetry tracing
"""

from app.observability.config import ObservabilityConfig
from app.observability.logger import get_logger, configure_logging
from app.observability.middleware import ObservabilityMiddleware
from app.observability.metrics import metrics_router, track_request, track_error

__all__ = [
    "ObservabilityConfig",
    "get_logger",
    "configure_logging",
    "ObservabilityMiddleware",
    "metrics_router",
    "track_request",
    "track_error",
]
