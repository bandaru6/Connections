"""
Configuration management for Athlete Lookalike API.
"""

import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = DATA_DIR / "profiles"
UPLOADS_DIR = BASE_DIR / "uploads"

# Ensure directories exist
PROFILES_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://athlete:athlete@localhost:5433/athlete_lookalike"
)

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ML Model
INSIGHTFACE_MODEL = os.getenv("INSIGHTFACE_MODEL", "buffalo_l")

# Matching thresholds
MIN_MATCH_SCORE = float(os.getenv("MIN_MATCH_SCORE", "0.20"))  # Lower threshold to show more matches
TOP_MATCHES = int(os.getenv("TOP_MATCHES", "10"))

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Observability
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_JSON = os.getenv("LOG_JSON", "false").lower() == "true"
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"
