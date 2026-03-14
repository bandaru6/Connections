"""Configuration settings for connections-social backend."""

import os
from pathlib import Path

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://connections:connections@localhost:5433/connections"
)

# Connection pool sizing.
# min=2 keeps warm connections available at idle.
# max=10 caps DB-side connection usage; requests queue rather than exhaust the DB.
# Rule of thumb: max = (CPU cores * 2) + num_disks, capped by DB max_connections.
DB_POOL_MIN_CONN = int(os.getenv("DB_POOL_MIN_CONN", "2"))
DB_POOL_MAX_CONN = int(os.getenv("DB_POOL_MAX_CONN", "10"))

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

# API key authentication.
# Set via K8s Secret / env in production.  Empty string = disabled (dev mode).
API_KEY = os.getenv("API_KEY", "")

# pgvector feature flag.
# false (default): brute-force Python cosine loop — works with stock PostgreSQL.
# true: use pgvector IVFFlat ANN query — requires migrate_pgvector.sql + migrate_embeddings.py.
USE_PGVECTOR = os.getenv("USE_PGVECTOR", "false").lower() == "true"

# Upload validation
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))  # 50 MB default
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp", "image/tiff"}
