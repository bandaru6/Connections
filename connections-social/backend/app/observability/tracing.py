"""OpenTelemetry tracing support for Connections Social backend.

Provides distributed tracing capabilities for debugging request flows
through detection, matching, and graph update operations.
"""

import os
from contextlib import contextmanager
from typing import Optional, Generator, Any

from app.observability.config import config

# Tracing state
_tracer = None
_trace_provider = None


def init_tracing() -> None:
    """Initialize OpenTelemetry tracing if enabled."""
    global _tracer, _trace_provider

    if not config.otel_enabled:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        # Create resource with service name
        resource = Resource(attributes={
            SERVICE_NAME: config.otel_service_name
        })

        # Create tracer provider
        _trace_provider = TracerProvider(resource=resource)

        # Configure OTLP exporter
        otlp_exporter = OTLPSpanExporter(
            endpoint=config.otel_endpoint,
            insecure=True  # For local development
        )

        # Add span processor
        _trace_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

        # Set as global tracer provider
        trace.set_tracer_provider(_trace_provider)

        # Get tracer instance
        _tracer = trace.get_tracer(config.service_name)

    except ImportError:
        # OpenTelemetry packages not installed
        pass
    except Exception as e:
        # Log but don't fail if tracing setup fails
        import logging
        logging.getLogger(__name__).warning(f"Failed to initialize tracing: {e}")


def get_tracer():
    """Get the OpenTelemetry tracer instance."""
    global _tracer
    if _tracer is None and config.otel_enabled:
        init_tracing()
    return _tracer


def get_trace_id() -> Optional[str]:
    """Get the current trace ID if tracing is active."""
    if not config.otel_enabled:
        return None

    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().trace_id, '032x')
    except ImportError:
        pass
    except Exception:
        pass

    return None


def get_span_id() -> Optional[str]:
    """Get the current span ID if tracing is active."""
    if not config.otel_enabled:
        return None

    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            return format(span.get_span_context().span_id, '016x')
    except ImportError:
        pass
    except Exception:
        pass

    return None


@contextmanager
def create_span(
    name: str,
    attributes: Optional[dict] = None
) -> Generator[Any, None, None]:
    """Create a new tracing span.

    Usage:
        with create_span("face_detection", {"image": filename}) as span:
            # do work
            span.set_attribute("faces_detected", count)
    """
    tracer = get_tracer()

    if tracer is None:
        # Tracing not enabled, yield a no-op context
        yield NoOpSpan()
        return

    try:
        with tracer.start_as_current_span(name, attributes=attributes) as span:
            yield span
    except Exception:
        yield NoOpSpan()


class NoOpSpan:
    """No-op span for when tracing is disabled."""

    def set_attribute(self, key: str, value: Any) -> None:
        """No-op set attribute."""
        pass

    def add_event(self, name: str, attributes: Optional[dict] = None) -> None:
        """No-op add event."""
        pass

    def record_exception(self, exception: Exception) -> None:
        """No-op record exception."""
        pass

    def set_status(self, status: Any) -> None:
        """No-op set status."""
        pass


def trace_function(name: Optional[str] = None):
    """Decorator to trace a function.

    Usage:
        @trace_function("process_image")
        def process_image(path):
            ...
    """
    def decorator(func):
        span_name = name or func.__name__

        def wrapper(*args, **kwargs):
            with create_span(span_name) as span:
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    raise

        # Preserve function metadata
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator
