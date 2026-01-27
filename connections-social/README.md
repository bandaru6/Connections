# Connections Social

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Next.js 14](https://img.shields.io/badge/Next.js-14-black.svg)](https://nextjs.org/)

Build a social graph from photos using face recognition. Upload group photos, and the system automatically detects faces, matches them to known identities, and builds a weighted relationship graph based on co-appearances.

<p align="center">
  <img src="assets/demo-screenshot.png" alt="Demo Screenshot" width="800">
</p>

## Features

- **Face Detection & Recognition** — InsightFace (buffalo_l) for accurate face detection and 512-dimensional embeddings
- **Identity Matching** — Cosine similarity matching against known profiles with configurable thresholds
- **Social Graph Construction** — Weighted edges based on co-appearances with photo evidence
- **Graph Queries** — Neighbors, ego networks, shortest paths between people
- **Interactive UI** — Next.js dashboard with vis-network graph visualization

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Make (optional, for convenience commands)

### One Command

```bash
git clone https://github.com/bandaru6/Connections.git
cd Connections/connections-social
make demo
```

That's it! Once services are healthy:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Next.js   │────▶│   FastAPI   │────▶│ InsightFace │
│   :3000     │     │   :8000     │     │  (buffalo_l)│
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼─────┐ ┌────▼────┐      │
        │ PostgreSQL│ │  Redis  │      │
        │  :5433    │ │  :6379  │      │
        └───────────┘ └─────────┘      │
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed system design.

## Project Structure

```
connections-social/
├── backend/              # FastAPI application
│   ├── app/
│   │   ├── main.py       # Entry point
│   │   ├── config.py     # Configuration
│   │   ├── db.py         # Database connection
│   │   └── routes/       # API endpoints
│   └── requirements.txt
├── frontend/             # Next.js application
│   ├── app/              # App router pages
│   ├── components/       # React components
│   └── lib/              # Utilities
├── infra/                # Infrastructure
│   ├── docker/
│   │   └── init.sql      # Database schema
│   └── docker-compose.yml
├── scripts/              # Utility scripts
│   ├── seed.sh           # Seed demo data
│   ├── demo.sh           # Full demo setup
│   └── repopulate_profiles.py
├── data/                 # Data files
│   ├── profiles/         # Reference face images (1 per person)
│   └── demo_uploads/     # Demo group photos
├── docs/                 # Documentation
│   ├── ARCHITECTURE.md
│   ├── API.md
│   └── AUDIT_REPORT.md
└── assets/               # Screenshots, diagrams
```

## Commands

| Command | Description |
|---------|-------------|
| `make demo` | Start everything + seed demo data |
| `make up` | Start all services |
| `make down` | Stop all services (preserves data) |
| `make reset` | Wipe all data and restart fresh |
| `make seed` | Rebuild profiles and ingest demo photos |
| `make logs` | Tail logs from all services |
| `make status` | Show service health status |
| `make clean` | Remove all containers, images, and volumes |
| `make dev` | Start only Postgres/Redis for local development |

## Local Development

For development without full Docker:

```bash
# Start databases only
make dev

# Terminal 1: Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm install
npm run dev
```

## API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/admin/rebuild-profile-index` | POST | Rebuild face embeddings from profiles |
| `/admin/reset-demo` | POST | Clear graph, keep profiles |
| `/ingest/upload` | POST | Upload and process single image |
| `/ingest/folder` | POST | Process all images in uploads/ |
| `/graph/summary` | GET | Graph statistics |
| `/graph/neighbors` | GET | Get person's connections |
| `/graph/ego` | GET | Get ego network |
| `/graph/path` | GET | Find shortest path |
| `/profiles/list` | GET | List all profiles |
| `/profiles/create` | POST | Create new profile |

See [docs/API.md](docs/API.md) for full API reference.

## How It Works

### 1. Profile Index
```
data/profiles/Barack_Obama/*.jpg  →  InsightFace  →  512-dim embedding  →  PostgreSQL
```

### 2. Image Ingestion
```
uploads/group_photo.jpg  →  Detect faces  →  Match to profiles  →  Create edges
```

### 3. Graph Query
```
GET /graph/ego?person=Barack Obama&depth=2  →  BFS traversal  →  Subgraph JSON
```

## Configuration

Copy `.env.example` to `.env` and customize:

```bash
# Backend
DATABASE_URL=postgresql://connections:connections@localhost:5433/connections
REDIS_URL=redis://localhost:6379/0
PROFILES_DIR=./data/profiles
UPLOADS_DIR=./uploads
INSIGHTFACE_MODEL=buffalo_l

# Frontend
BACKEND_URL=http://localhost:8000
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- [InsightFace](https://github.com/deepinsight/insightface) for face recognition
- [vis-network](https://visjs.github.io/vis-network/docs/network/) for graph visualization
