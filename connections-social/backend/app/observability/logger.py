"""Structured JSON logging for Connections Social backend."""

import json
import logging
import sys
import traceback
from datetime import datetime, timezone

from app.observability.config import config


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": config.service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields from record
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "trace_id"):
            log_data["trace_id"] = record.trace_id
        if hasattr(record, "method"):
            log_data["method"] = record.method
        if hasattr(record, "path"):
            log_data["path"] = record.path
        if hasattr(record, "status_code"):
            log_data["status_code"] = record.status_code
        if hasattr(record, "latency_ms"):
            log_data["latency_ms"] = record.latency_ms
        if hasattr(record, "client_ip"):
            log_data["client_ip"] = record.client_ip
        if hasattr(record, "user_agent"):
            log_data["user_agent"] = record.user_agent

        # Add exception info if present
        if record.exc_info:
            log_data["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            log_data["exception_message"] = str(record.exc_info[1]) if record.exc_info[1] else None
            log_data["stacktrace"] = "".join(traceback.format_exception(*record.exc_info))

        # Add any other extras
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "request_id", "trace_id", "method", "path", "status_code",
                "latency_ms", "client_ip", "user_agent", "message"
            ) and not key.startswith("_"):
                if isinstance(value, (str, int, float, bool, type(None))):
                    log_data[key] = value

        return json.dumps(log_data, default=str)


class StandardFormatter(logging.Formatter):
    """Standard text formatter for development."""

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )


def configure_logging() -> None:
    """Configure logging based on environment settings."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

    # Set formatter based on config
    if config.log_json:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(StandardFormatter())

    root_logger.addHandler(console_handler)

    # Reduce noise from third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)


class RequestLogger:
    """Helper class for logging request-scoped data."""

    def __init__(
        self,
        logger: logging.Logger,
        request_id: str,
        trace_id: str | None = None
    ):
        self.logger = logger
        self.request_id = request_id
        self.trace_id = trace_id

    def _add_context(self, extra: dict) -> dict:
        """Add request context to extra dict."""
        extra["request_id"] = self.request_id
        if self.trace_id:
            extra["trace_id"] = self.trace_id
        return extra

    def info(self, msg: str, **kwargs) -> None:
        """Log info message with request context."""
        self.logger.info(msg, extra=self._add_context(kwargs))

    def warning(self, msg: str, **kwargs) -> None:
        """Log warning message with request context."""
        self.logger.warning(msg, extra=self._add_context(kwargs))

    def error(self, msg: str, exc_info: bool = False, **kwargs) -> None:
        """Log error message with request context."""
        self.logger.error(msg, exc_info=exc_info, extra=self._add_context(kwargs))

    def debug(self, msg: str, **kwargs) -> None:
        """Log debug message with request context."""
        self.logger.debug(msg, extra=self._add_context(kwargs))


def log_request(
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    latency_ms: float,
    client_ip: str,
    user_agent: str,
    bytes_in: int | None = None,
    bytes_out: int | None = None,
    trace_id: str | None = None,
    endpoint: str | None = None,
) -> None:
    """Log a completed request."""
    logger = get_logger("request")
    extra = {
        "request_id": request_id,
        "method": method,
        "path": path,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "client_ip": client_ip,
        "user_agent": user_agent,
    }

    if trace_id:
        extra["trace_id"] = trace_id
    if bytes_in is not None:
        extra["bytes_in"] = bytes_in
    if bytes_out is not None:
        extra["bytes_out"] = bytes_out
    if endpoint:
        extra["endpoint"] = endpoint

    level = logging.INFO
    if status_code >= 500:
        level = logging.ERROR
    elif status_code >= 400:
        level = logging.WARNING

    logger.log(level, f"{method} {path} {status_code} {latency_ms:.2f}ms", extra=extra)


def log_exception(
    request_id: str,
    exception: Exception,
    trace_id: str | None = None,
) -> None:
    """Log an unhandled exception."""
    logger = get_logger("error")
    extra = {
        "request_id": request_id,
        "exception_type": type(exception).__name__,
    }
    if trace_id:
        extra["trace_id"] = trace_id

    logger.error(
        f"Unhandled exception: {type(exception).__name__}: {str(exception)}",
        exc_info=True,
        extra=extra
    )
