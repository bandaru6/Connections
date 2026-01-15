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
PROFILES_DIR = Path(os.getenv(
    "PROFILES_DIR",
    os.path.expanduser("~/Connections/phase2-engine/data/profiles")
))

UPLOADS_DIR = Path(os.getenv(
    "UPLOADS_DIR",
    os.path.expanduser("~/Connections/connections-social/uploads")
))

# InsightFace model
INSIGHTFACE_MODEL = os.getenv("INSIGHTFACE_MODEL", "buffalo_l")
