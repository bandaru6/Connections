"""Connections Social FastAPI application."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import UPLOADS_DIR
from app.db import check_db_connection
from app.routes import admin, ingest, graph, profiles, jobs

# Import observability components
from app.observability import (
    configure_logging,
    ObservabilityMiddleware,
    metrics_router,
)
from app.observability.tracing import init_tracing

# Configure structured logging
configure_logging()
logger = logging.getLogger(__name__)

# Initialize OpenTelemetry tracing (if enabled)
init_tracing()

app = FastAPI(
    title="Connections Social API",
    description="Social graph from photos",
    version="0.1.0"
)

# Observability middleware (must be added before CORS)
app.add_middleware(ObservabilityMiddleware)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://frontend:3000",  # Docker network
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers (including metrics)
app.include_router(metrics_router)  # /metrics endpoint for Prometheus
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(graph.router, prefix="/graph", tags=["graph"])
app.include_router(profiles.router, prefix="/profiles", tags=["profiles"])

# Serve uploaded images statically for evidence viewing
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=str(UPLOADS_DIR)), name="images")


@app.get("/")
def root():
    """API information and endpoint directory."""
    return {
        "name": "Connections Social",
        "description": "Build a social graph from photos using face recognition",
        "version": "0.1.0",
        "endpoints": {
            "/health": "GET - Health check with database status",
            "/metrics": "GET - Prometheus metrics endpoint",
            "/admin/rebuild-profile-index": "POST - Rebuild person index from profile photos",
            "/admin/reset-demo": "POST - Reset graph state (keeps profiles)",
            "/admin/clear-processed": "POST - Clear processed_images only",
            "/admin/replay": "POST - Reprocess historical images with current model",
            "/ingest/upload": "POST - Upload and process a single image",
            "/ingest/folder": "POST - Process all images in uploads/ folder",
            "/ingest/batch": "POST - Async batch ingestion with job status",
            "/ingest/circuit-breaker/status": "GET - ML inference circuit breaker status",
            "/ingest/circuit-breaker/reset": "POST - Reset circuit breaker",
            "/jobs/{job_id}": "GET - Get job status and progress",
            "/graph/summary": "GET - Graph statistics and top edges",
            "/graph/neighbors": "GET - Get neighbors of a person (?person=Name)",
            "/graph/ego": "GET - Get ego network (?person=Name&depth=2)",
            "/profiles/list": "GET - List all known profiles",
            "/profiles/create": "POST - Create new profile (multipart: name, images[])",
            "/profiles/check-match": "POST - Check if face matches existing profile",
            "/images/{filename}": "GET - Serve uploaded images"
        }
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    db_ok = check_db_connection()
    status = "healthy" if db_ok else "degraded"
    return {
        "status": status,
        "database": "ok" if db_ok else "unavailable"
    }
