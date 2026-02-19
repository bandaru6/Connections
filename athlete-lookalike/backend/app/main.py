"""
Athlete Lookalike API - Find which athlete you look like most!

Supports NBA and NFL player comparisons using face recognition.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import compare, athletes, admin
from . import config

app = FastAPI(
    title="Athlete Lookalike API",
    description="Upload a photo and find out which NBA or NFL player you look like!",
    version="1.0.0"
)

# Serve athlete profile images
app.mount("/images", StaticFiles(directory=str(config.PROFILES_DIR)), name="images")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(compare.router, prefix="/compare", tags=["compare"])
app.include_router(athletes.router, prefix="/athletes", tags=["athletes"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "athlete-lookalike",
        "version": "1.0.0"
    }


@app.get("/")
async def root():
    """API root - welcome message."""
    return {
        "message": "Welcome to Athlete Lookalike API!",
        "docs": "/docs",
        "endpoints": {
            "compare": "/compare/upload - Upload a photo to find your athlete match",
            "athletes": "/athletes/list - List all athletes in the database",
            "admin": "/admin/rebuild-index - Rebuild athlete face embeddings"
        }
    }
