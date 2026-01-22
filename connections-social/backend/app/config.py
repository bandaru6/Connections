"""Configuration settings for connections-social backend."""

import os
from pathlib import Path

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://connections:connections@localhost:5433/connections"
)

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Paths
# Use local data/profiles directory relative to the project root
# We assume the backend is running from connections-social/backend or similar,
# so we resolve relative to this file's parent directory.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROFILES_DIR = Path(os.getenv(
    "PROFILES_DIR",
    BASE_DIR / "data" / "profiles"
))

UPLOADS_DIR = Path(os.getenv(
    "UPLOADS_DIR",
    BASE_DIR / "uploads"
))

# InsightFace model
INSIGHTFACE_MODEL = os.getenv("INSIGHTFACE_MODEL", "buffalo_l")
