"""Shared pytest fixtures for unit and integration tests."""

import os
import pytest

# Point tests at a test DB/Redis by default.
# CI overrides these via environment variables.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://connections:connections@localhost:5433/connections"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
