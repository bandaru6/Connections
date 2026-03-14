# Backend Dockerfile - FastAPI with InsightFace
# Force x86_64 platform for reliable mirrors and pre-built wheels
# Uses Rosetta 2 emulation on Apple Silicon (slower but works)

FROM --platform=linux/amd64 python:3.11-slim-bullseye

# Install minimal dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        libglib2.0-0 \
        libgl1-mesa-glx \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (pre-built x86_64 wheels available)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create directories and non-root user
# Running as root inside a container is a security risk:
#   - If the process is compromised, the attacker has root inside the container
#   - Some K8s policies (PodSecurityPolicy / OPA) reject root containers
# UID 1000 is the conventional non-privileged user for application containers.
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --no-create-home appuser && \
    mkdir -p /app/data/profiles /app/uploads && \
    chown -R appuser:appuser /app

# Switch to non-root user before running the application
USER appuser

# Environment variables (non-sensitive defaults — override via K8s Secret / env)
ENV DATABASE_URL=postgresql://connections:connections@postgres:5432/connections
ENV REDIS_URL=redis://redis:6379/0
ENV PROFILES_DIR=/app/data/profiles
ENV UPLOADS_DIR=/app/uploads
ENV INSIGHTFACE_MODEL=buffalo_l

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
