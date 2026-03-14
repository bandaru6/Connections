"""Observability configuration."""

import os
from dataclasses import dataclass


@dataclass
class ObservabilityConfig:
    """Configuration for observability features."""

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_json: bool = os.getenv("LOG_JSON", "true").lower() == "true"
    service_name: str = os.getenv("SERVICE_NAME", "connections-backend")

    # OpenTelemetry — enabled by default; set OTEL_ENABLED=false to disable
    # Endpoint should point to Jaeger OTLP gRPC port (4317)
    otel_enabled: bool = os.getenv("OTEL_ENABLED", "true").lower() == "true"
    otel_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    otel_service_name: str = os.getenv("OTEL_SERVICE_NAME", "connections-backend")

    # Metrics
    metrics_enabled: bool = os.getenv("METRICS_ENABLED", "true").lower() == "true"

    # Paths to skip logging (internal endpoints)
    skip_paths: tuple = ("/metrics", "/health", "/docs", "/openapi.json", "/redoc")


# Global config instance
config = ObservabilityConfig()
