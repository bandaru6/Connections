"""Connections Social FastAPI application."""

import logging
from fastapi import FastAPI

from app.db import check_db_connection
from app.routes import admin, ingest, graph

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

# Include routers
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
app.include_router(graph.router, prefix="/graph", tags=["graph"])


@app.get("/health")
def health_check():
    """Health check endpoint."""
    db_ok = check_db_connection()
    status = "healthy" if db_ok else "degraded"
    return {
        "status": status,
        "database": "ok" if db_ok else "unavailable"
    }
