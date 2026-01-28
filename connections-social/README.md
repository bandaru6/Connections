# Connections Social

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Next.js 14](https://img.shields.io/badge/Next.js-14-black.svg)](https://nextjs.org/)
[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](https://www.docker.com/)

Build a social graph from photos using face recognition. Upload group photos, and the system automatically detects faces, matches them to known identities, and builds a weighted relationship graph based on co-appearances.

<p align="center">
  <img src="assets/demo-screenshot.png" alt="Demo Screenshot" width="800">
</p>

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose (v2.0+)
- 8GB+ RAM recommended (for ML model)

### One-Command Demo

```bash
git clone https://github.com/bandaru6/Connections.git
cd Connections/connections-social
cp .env.example .env
docker compose up --build -d
```

Wait for services to start (first run downloads ML models, ~2-5 min), then seed demo data:

```bash
make seed
```

**That's it!** Open your browser:

| Service | URL |
|---------|-----|
| **Frontend** | http://localhost:3000 |
| **Backend API** | http://localhost:8000 |
| **API Docs** | http://localhost:8000/docs |

### What You Should See

1. **Graph View**: An interactive network visualization showing 10 demo people connected by 18 edges
2. **People Panel**: List of all persons in the graph with connection counts
3. **Stats**: Graph summary showing total nodes, edges, and co-appearances

### Stopping

```bash
docker compose down        # Stop services (keeps data)
docker compose down -v     # Stop and wipe all data
```

## Features

### Core Functionality
- **Face Detection & Recognition** — InsightFace (buffalo_l) for accurate face detection and 512-dimensional embeddings
- **Identity Matching** — Cosine similarity matching against known profiles with configurable thresholds
- **Social Graph Construction** — Weighted edges based on co-appearances with photo evidence
- **Graph Queries** — Neighbors, ego networks, shortest paths between people
- **Interactive UI** — Next.js dashboard with vis-network graph visualization
- **One-Command Setup** — Fully containerized with Docker Compose

### Production-Grade Infrastructure
- **Observability** — Structured JSON logging, Prometheus metrics (`/metrics`), optional OpenTelemetry tracing
- **Data Lineage** — Every graph edge tracks model version, confidence scores, and processing timestamp
- **Async Processing** — Background job system with Redis-backed status tracking (poll via `/jobs/{id}`)
- **Circuit Breaker** — ML inference isolation with automatic failure detection and recovery
- **Idempotent Ingestion** — Duplicate detection prevents reprocessing of identical images
- **Replay Capability** — Reprocess historical data with updated models via `/admin/replay`

## Architecture

```
                              ┌─────────────────────────────────────┐
                              │           Observability             │
                              │  • Structured JSON Logs             │
                              │  • Prometheus Metrics (/metrics)    │
                              │  • OpenTelemetry Traces (optional)  │
                              └──────────────────┬──────────────────┘
                                                 │
┌─────────────┐     ┌────────────────────────────▼───────────────────┐
│   Next.js   │────▶│              FastAPI Backend                   │
│   :3000     │     │  ┌──────────────┐  ┌────────────────────────┐  │
└─────────────┘     │  │   Circuit    │  │   Async Job System     │  │
                    │  │   Breaker    │──│   (Redis-backed)       │  │
                    │  └──────┬───────┘  └────────────────────────┘  │
                    │         │                                       │
                    │  ┌──────▼───────┐  ┌────────────────────────┐  │
                    │  │  InsightFace │  │   Data Lineage         │  │
                    │  │  (buffalo_l) │  │   (model version,      │  │
                    │  └──────────────┘  │    confidence, time)   │  │
                    │                    └────────────────────────┘  │
                    └───────────────────────────┬────────────────────┘
                                                │
                          ┌─────────────────────┼─────────────────────┐
                          │                     │                     │
                    ┌─────▼─────┐         ┌─────▼─────┐               │
                    │ PostgreSQL│         │   Redis   │               │
                    │   :5433   │         │   :6379   │               │
                    │  (graph,  │         │  (jobs,   │               │
                    │  lineage) │         │  cache)   │               │
                    └───────────┘         └───────────┘               │
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed system design.

## Commands

### Docker (Recommended)

| Command | Description |
|---------|-------------|
| `make up` | Build and start all services |
| `make down` | Stop all services (preserves data) |
| `make reset` | Wipe all data and restart fresh |
| `make seed` | Seed demo data into the database |
| `make logs` | Tail logs from all services |
| `make status` | Show service health status |
| `make clean` | Remove all containers, images, and volumes |

### Local Development

For development without full Docker:

```bash
# Start databases only
make dev

# Terminal 1: Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
make backend

# Terminal 2: Frontend
cd frontend
npm install
make frontend
```

| Command | Description |
|---------|-------------|
| `make dev` | Start only Postgres/Redis |
| `make backend` | Start backend locally |
| `make frontend` | Start frontend locally |
| `make stop` | Stop local backend and frontend |

## Project Structure

```
connections-social/
├── backend/              # FastAPI application
│   ├── app/
│   │   ├── main.py       # Entry point
│   │   ├── config.py     # Configuration
│   │   ├── db.py         # Database connection
│   │   └── routes/       # API endpoints
│   ├── Dockerfile        # Backend container
│   └── requirements.txt
├── frontend/             # Next.js application
│   ├── app/              # App router pages
│   ├── components/       # React components
│   ├── lib/              # Utilities
│   └── Dockerfile        # Frontend container
├── infra/                # Infrastructure
│   ├── docker/
│   │   └── init.sql      # Database schema
│   └── docker-compose.yml  # DB-only compose (local dev)
├── scripts/              # Utility scripts
│   ├── seed_demo.py      # Seed demo data
│   └── repopulate_profiles.py
├── data/                 # Data files
│   ├── profiles/         # Reference face images (1 per person)
│   └── demo_uploads/     # Demo group photos
├── docs/                 # Documentation
├── docker-compose.yml    # Full stack compose
├── Makefile              # Developer commands
└── .env.example          # Environment template
```

## API Overview

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/metrics` | GET | Prometheus metrics |
| `/admin/rebuild-profile-index` | POST | Rebuild face embeddings from profiles |
| `/admin/reset-demo` | POST | Clear graph, keep profiles |
| `/admin/replay` | POST | Reprocess historical data with current model |
| `/ingest/upload` | POST | Upload and process single image |
| `/ingest/folder` | POST | Process all images in uploads/ (blocking) |
| `/ingest/batch` | POST | Async batch ingestion (returns job ID) |
| `/jobs/{job_id}` | GET | Poll job status and progress |
| `/graph/summary` | GET | Graph statistics |
| `/graph/neighbors` | GET | Get person's connections |
| `/graph/ego` | GET | Get ego network |
| `/graph/path` | GET | Find shortest path |
| `/profiles/list` | GET | List all profiles |
| `/profiles/create` | POST | Create new profile |

### Reliability Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ingest/circuit-breaker/status` | GET | Check ML inference circuit breaker state |
| `/ingest/circuit-breaker/reset` | POST | Manually reset circuit breaker |

See [docs/API.md](docs/API.md) for full API reference.

## How It Works

### 1. Profile Index
```
data/profiles/Barack Obama/*.jpg  →  InsightFace  →  512-dim embedding  →  PostgreSQL
```

### 2. Image Ingestion
```
uploads/group_photo.jpg  →  Detect faces  →  Match to profiles  →  Create edges
```

### 3. Graph Query
```
GET /graph/ego?person=Barack Obama&depth=2  →  BFS traversal  →  Subgraph JSON
```

## Observability & Reliability

### Structured Logging

All requests are logged in JSON format with request IDs, latencies, and status codes:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "INFO",
  "request_id": "abc-123",
  "method": "POST",
  "path": "/ingest/upload",
  "status_code": 200,
  "latency_ms": 1523.45
}
```

### Metrics

Prometheus metrics available at `/metrics`:

- `http_requests_total` — Request counts by method, path, status
- `http_request_duration_seconds` — Latency histogram (p50, p95, p99)
- `faces_detected_total` — Total faces detected
- `faces_matched_total` — Successful identity matches
- `in_flight_requests` — Currently processing requests

### Circuit Breaker

ML inference is protected by a circuit breaker that:
- Opens after 5 failures in 60 seconds
- Returns 503 immediately when open (fail-fast)
- Automatically tests recovery after 30 seconds

Check status: `GET /ingest/circuit-breaker/status`

### Async Job Processing

Long-running operations return immediately with a job ID:

```bash
# Start batch ingestion
curl -X POST localhost:8000/ingest/batch
# {"job_id": "abc-123", "poll_url": "/jobs/abc-123"}

# Poll for status
curl localhost:8000/jobs/abc-123
# {"status": "running", "progress": {"current": 5, "total": 20, "percentage": 25.0}}
```

### Data Lineage

Every graph edge tracks provenance:
- `model_version`: Which ML model produced the match
- `confidence_a`, `confidence_b`: Match confidence for each person
- `processed_at`: When the edge was created

Query lineage via `/admin/replay` to reprocess with updated models.

## Configuration

Environment variables (`.env`):

```bash
# Backend Core
DATABASE_URL=postgresql://connections:connections@postgres:5432/connections
REDIS_URL=redis://redis:6379/0
PROFILES_DIR=/app/data/profiles
UPLOADS_DIR=/app/uploads
INSIGHTFACE_MODEL=buffalo_l

# Observability
LOG_LEVEL=INFO                           # DEBUG, INFO, WARNING, ERROR
LOG_JSON=true                            # JSON logs for production
METRICS_ENABLED=true                     # Enable Prometheus metrics
OTEL_ENABLED=false                       # Enable OpenTelemetry tracing
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Frontend
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000

# Ports (change if conflicts)
POSTGRES_PORT=5433
REDIS_PORT=6379
BACKEND_PORT=8000
FRONTEND_PORT=3000
```

## Troubleshooting

### Services not starting?
```bash
make logs                    # Check logs
make status                  # Check health
docker compose ps            # See container status
```

### Port conflicts?
Edit `.env` to change ports:
```bash
BACKEND_PORT=8001
FRONTEND_PORT=3001
```

### Fresh start?
```bash
make clean                   # Remove everything
make up && make seed         # Start fresh
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [InsightFace](https://github.com/deepinsight/insightface) for face recognition
- [vis-network](https://visjs.github.io/vis-network/docs/network/) for graph visualization
