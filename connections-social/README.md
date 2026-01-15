# Connections Social

Build a social graph from photos using face recognition.

## Architecture

- **Backend**: FastAPI (Python)
- **Worker**: RQ (Redis Queue) for async processing
- **Frontend**: Next.js (planned)
- **Database**: PostgreSQL
- **Cache/Queue**: Redis

## Prerequisites

- Docker & Docker Compose
- Python 3.10+
- Node.js 18+ (for frontend, later)

## Quick Start

### 1. Start Database Services

```bash
cd connections-social
docker compose up -d
```

This starts:
- PostgreSQL on port 5432 (user: connections, password: connections, db: connections)
- Redis on port 6379

The database schema is automatically initialized on first start.

### 2. Set Up Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Backend

```bash
cd backend
source venv/bin/activate

# Run FastAPI server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is now available at http://localhost:8000

### 4. Verify Health

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "healthy", "database": "ok"}
```

## API Endpoints

### Health Check

```
GET /health
```

Returns system health status including database connectivity.

### Rebuild Profile Index

```
POST /admin/rebuild-profile-index
```

Scans the profile images directory and builds the person index:
- Reads from `~/Connections/phase2-engine/data/profiles/<Identity>/*.jpg`
- Extracts face embeddings using InsightFace (buffalo_l model)
- Enforces exactly 1 face per image (rejects multi-face or no-face images)
- Stores persons and embeddings in PostgreSQL

Example:
```bash
curl -X POST http://localhost:8000/admin/rebuild-profile-index
```

Response:
```json
{
  "status": "completed",
  "profiles_dir": "/path/to/profiles",
  "total_images_scanned": 100,
  "persons_created": 50,
  "profiles_inserted": 95,
  "images_rejected": 5,
  "rejected_details": [...]
}
```

## Database Schema

- **persons**: Known identities (name)
- **person_profiles**: Face embeddings for each person
- **uploads**: User-uploaded images
- **faces**: Detected faces in uploads with match results
- **edges**: Connections between persons (weighted)
- **edge_evidence**: Photos proving connections

## Configuration

Environment variables (defaults shown):

```bash
DATABASE_URL=postgresql://connections:connections@localhost:5432/connections
REDIS_URL=redis://localhost:6379/0
PROFILES_DIR=~/Connections/phase2-engine/data/profiles
INSIGHTFACE_MODEL=buffalo_l
```

## Development

### View Logs

```bash
# Docker services
docker compose logs -f

# Backend (when running with --reload)
# Logs appear in terminal
```

### Reset Database

```bash
docker compose down -v
docker compose up -d
```

### Stop Services

```bash
docker compose down
```
