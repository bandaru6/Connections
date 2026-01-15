# Connections Social

Build a social graph from photos using face recognition. Upload group photos, and the system automatically detects faces, matches them to known identities, and builds a weighted relationship graph based on co-appearances.

## What This Is

Connections Social is a backend API that:
- **Indexes known people** from a directory of profile photos (one face per photo)
- **Ingests group photos** to detect and match faces
- **Builds a social graph** where edges represent co-appearances in photos
- **Provides graph queries** to explore connections between people

## How It Works

```
Profile Photos → Face Embeddings → Person Index
                                        ↓
Group Photos → Face Detection → Identity Matching → Edge Creation
                                                          ↓
                                              Graph APIs (summary, neighbors, ego)
```

1. **Build Profile Index**: Scan profile photos, extract face embeddings with InsightFace, store in Postgres
2. **Ingest Photos**: For each group photo, detect faces, match against known profiles, assign UNKNOWN IDs for unrecognized faces
3. **Create Edges**: Every pair of people in a photo creates/updates an edge with weight and evidence
4. **Query Graph**: Explore connections via REST APIs

## Quickstart

### 1. Start Database Services

```bash
cd ~/Connections/connections-social
docker compose up -d
```

This starts:
- **PostgreSQL** on port **5433** (user: `connections`, password: `connections`, db: `connections`)
- **Redis** on port 6379

> **Note**: Postgres runs on port 5433 (not the default 5432) to avoid conflicts.

### 2. Set Up Python Environment

```bash
cd ~/Connections/connections-social/backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the Backend

```bash
cd ~/Connections/connections-social/backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The API is now available at http://localhost:8000

### 4. Verify Everything Works

```bash
# Health check
curl http://localhost:8000/health

# Build profile index (requires profile photos in ~/Connections/phase2-engine/data/profiles/)
curl -X POST http://localhost:8000/admin/rebuild-profile-index

# Ingest photos from uploads/ folder
curl -X POST http://localhost:8000/ingest/folder

# Get graph summary
curl http://localhost:8000/graph/summary

# Get neighbors of a person
curl "http://localhost:8000/graph/neighbors?person=Joe%20Biden"

# Get ego network (2-hop neighborhood)
curl "http://localhost:8000/graph/ego?person=Joe%20Biden&depth=2"
```

## Demo Flow

For a quick demo, use the included script:

```bash
cd ~/Connections/connections-social

# Put 6-10 multi-person images in demo_uploads/
# Then run:
./scripts/demo.sh --sync-demo
```

The `--sync-demo` flag copies images from `demo_uploads/` to `uploads/` before ingestion.

Without images, the script still runs and shows the API responses (with `processed: 0`).

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | API info and endpoint list |
| `/health` | GET | Health check with database status |
| `/admin/rebuild-profile-index` | POST | Rebuild person index from profile photos |
| `/ingest/upload` | POST | Upload and process a single image |
| `/ingest/folder` | POST | Process all images in `uploads/` folder |
| `/graph/summary` | GET | Graph statistics and top edges |
| `/graph/neighbors` | GET | Get neighbors of a person |
| `/graph/ego` | GET | Get ego network (multi-hop neighborhood) |

### Query Parameters

Most graph endpoints support:
- `include_unknown=true|false` - Include/exclude UNKNOWN_* persons (default: true)
- `limit=N` - Limit number of results

## Demo Images

Place 6-10 multi-person images in `demo_uploads/`:

```bash
# Example: copy some test images
cp /path/to/group-photos/*.jpg demo_uploads/
```

The demo script will sync these to `uploads/` when you run `./scripts/demo.sh --sync-demo`.

## Configuration

Environment variables (with defaults):

```bash
DATABASE_URL=postgresql://connections:connections@localhost:5433/connections
REDIS_URL=redis://localhost:6379/0
PROFILES_DIR=~/Connections/phase2-engine/data/profiles
UPLOADS_DIR=~/Connections/connections-social/uploads
INSIGHTFACE_MODEL=buffalo_l
```

## Database Schema

| Table | Purpose |
|-------|---------|
| `persons` | Known identities (name, created_at) |
| `person_profiles` | Face embeddings for each person |
| `uploads` | Processed images |
| `faces` | Detected faces with match results |
| `edges` | Connections between persons (weighted) |
| `edge_evidence` | Photos proving each connection |
| `processed_images` | Idempotency tracking for ingestion |

## Development

```bash
# View docker logs
docker compose logs -f

# Reset database (loses all data)
docker compose down -v
docker compose up -d

# Stop services
docker compose down
```
