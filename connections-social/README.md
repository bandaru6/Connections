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

## Unknown Person Lifecycle

When ingesting photos, faces that don't match any known profile are assigned auto-generated identities:

1. **Detection**: InsightFace detects all faces in a group photo
2. **Matching**: Each face embedding is compared against all known profiles using cosine similarity
3. **Threshold Check**: If the best match score is < 0.45 (or fails the 0.05 margin check), the face is marked as unknown
4. **Identity Assignment**: Unknown faces get sequential IDs like `UNKNOWN_0001`, `UNKNOWN_0002`, etc.
5. **Graph Integration**: Unknown persons become permanent nodes and can have edges to other people

**Why Unknown Persons Grow**: Every unmatched face in every photo becomes a distinct identity. This explains why `persons_total` exceeds the number of profile folders.

**Filtering Unknown Faces**:
- All graph APIs support `include_unknown=false` (the default) to filter out unknown persons
- The UI has an "Advanced" section with a toggle to include/exclude unknowns
- The graph summary shows `known_persons_total` and `edges_known_only_total` separately

**Cleaning Up Unknowns**: Use `/admin/reset-demo` to clear all edges and unknowns while keeping profiles, or `/admin/rebuild-profile-index` for a complete reset.

## File Structure & Image Locations

The system is self-contained. Here is where images live:

*   **`data/profiles/`**: Source of truth for known identities.
    *   Structure: `data/profiles/<Person Name>/<photo>.jpg`
    *   Used by: `/admin/rebuild-profile-index`
*   **`uploads/`**: The active ingestion folder.
    *   Group photos uploaded via the UI or copied here are processed from this location.
    *   Used by: `/ingest/folder` and `/ingest/upload`
*   **`demo_uploads/`**: Backup of good demo images.
    *   Use the demo script to copy these into `uploads/`.
*   **`data/group_photos/`**: Optional dataset folder.
    *   Can be used for batch processing large datasets (requires copying to `uploads/` currently).

## Quickstart

### 1. Start Database Services

```bash
cd connections-social  # or wherever you cloned the repo
docker compose up -d
```

This starts:
- **PostgreSQL** on port **5433** (user: `connections`, password: `connections`, db: `connections`)
- **Redis** on port 6379

### 2. Set Up Python Environment

```bash
cd connections-social  # or wherever you cloned the repo/backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the Backend

```bash
cd connections-social  # or wherever you cloned the repo/backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The API is now available at http://localhost:8000

### 4. Verify Everything Works

```bash
# Health check
curl http://localhost:8000/health

# Build profile index (uses data/profiles/)
curl -X POST http://localhost:8000/admin/rebuild-profile-index

# Ingest photos from uploads/ folder
curl -X POST http://localhost:8000/ingest/folder

# Get graph summary
curl http://localhost:8000/graph/summary
```

## Demo Flow

For a quick demo, use the included script:

```bash
cd connections-social  # or wherever you cloned the repo

# Syncs images from demo_uploads/ to uploads/ and runs the full pipeline
./scripts/demo.sh --sync-demo
```

## Configuration

Environment variables (with defaults):

```bash
DATABASE_URL=postgresql://connections:connections@localhost:5433/connections
REDIS_URL=redis://localhost:6379/0
PROFILES_DIR=./data/profiles  # Relative to project root
UPLOADS_DIR=./uploads         # Relative to project root
INSIGHTFACE_MODEL=buffalo_l
```
