"""Connections Social FastAPI application."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import UPLOADS_DIR
from app.db import check_db_connection
from app.routes import admin, ingest, graph, profiles

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Connections Social API",
    description="Social graph from photos",
    version="0.1.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
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
            "/admin/rebuild-profile-index": "POST - Rebuild person index from profile photos",
            "/admin/reset-demo": "POST - Reset graph state (keeps profiles)",
            "/admin/clear-processed": "POST - Clear processed_images only",
            "/ingest/upload": "POST - Upload and process a single image",
            "/ingest/folder": "POST - Process all images in uploads/ folder",
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
