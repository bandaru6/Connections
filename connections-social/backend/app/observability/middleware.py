"""Request logging and observability middleware."""

import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.observability.config import config
from app.observability.logger import get_logger, log_exception, log_request
from app.observability.metrics import track_error, track_in_flight, track_request
from app.observability.tracing import get_trace_id

logger = get_logger(__name__)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Middleware for request logging, metrics, and tracing."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process request with observability instrumentation."""
        # Skip observability for certain paths
        path = request.url.path
        if any(path.startswith(skip) for skip in config.skip_paths):
            return await call_next(request)

        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())

        # Get trace ID if OpenTelemetry is enabled
        trace_id = get_trace_id() if config.otel_enabled else None

        # Store request ID in request state for use by handlers
        request.state.request_id = request_id
        request.state.trace_id = trace_id

        # Extract request metadata
        method = request.method
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "")
        bytes_in = self._get_content_length(request)

        # Track in-flight requests
        track_in_flight(increment=True)

        # Time the request
        start_time = time.perf_counter()

        try:
            # Process the request
            response = await call_next(request)

            # Calculate duration
            duration = time.perf_counter() - start_time
            latency_ms = duration * 1000

            # Get response metadata
            status_code = response.status_code
            bytes_out = self._get_response_content_length(response)

            # Get endpoint name if available
            endpoint = self._get_endpoint_name(request)

            # Log the request
            log_request(
                request_id=request_id,
                method=method,
                path=path,
                status_code=status_code,
                latency_ms=latency_ms,
                client_ip=client_ip,
                user_agent=user_agent,
                bytes_in=bytes_in,
                bytes_out=bytes_out,
                trace_id=trace_id,
                endpoint=endpoint,
            )

            # Track metrics
            track_request(method, path, status_code, duration)

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            if trace_id:
                response.headers["X-Trace-ID"] = trace_id

            return response

        except Exception as exc:
            # Calculate duration even on error
            duration = time.perf_counter() - start_time
            latency_ms = duration * 1000

            # Log the exception
            log_exception(request_id, exc, trace_id)

            # Track error metrics
            track_error(method, path, type(exc).__name__)

            # Log failed request
            log_request(
                request_id=request_id,
                method=method,
                path=path,
                status_code=500,
                latency_ms=latency_ms,
                client_ip=client_ip,
                user_agent=user_agent,
                trace_id=trace_id,
            )

            # Re-raise to let FastAPI handle the error response
            raise

        finally:
            # Always decrement in-flight counter
            track_in_flight(increment=False)

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request, handling proxies."""
        # Check for forwarded headers (when behind proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct client
        if request.client:
            return request.client.host

        return "unknown"

    def _get_content_length(self, request: Request) -> int | None:
        """Get request content length if available."""
        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                return int(content_length)
            except ValueError:
                pass
        return None

    def _get_response_content_length(self, response: Response) -> int | None:
        """Get response content length if available."""
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                return int(content_length)
            except ValueError:
                pass
        return None

    def _get_endpoint_name(self, request: Request) -> str | None:
        """Get the route/endpoint name if available."""
        # FastAPI stores route info in request scope
        route = request.scope.get("route")
        if route:
            return route.name
        return None
