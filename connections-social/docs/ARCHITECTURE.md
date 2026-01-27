# Architecture

## System Overview

Connections Social builds a social graph from photos using face recognition. The system detects faces in uploaded images, matches them against known identity profiles, and constructs a weighted relationship graph based on co-appearances.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client Layer                            │
├─────────────────────────────────────────────────────────────────┤
│  Next.js Frontend (React)                                       │
│  - Dashboard: System health, admin actions                      │
│  - Explore: Graph visualization with vis-network                │
│  - API proxy: /api/* → Backend                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         API Layer                               │
├─────────────────────────────────────────────────────────────────┤
│  FastAPI Backend                                                │
│  ├── /admin/*     - Profile index, reset, storage info          │
│  ├── /ingest/*    - Upload and process images                   │
│  ├── /graph/*     - Query relationships (neighbors, ego, path)  │
│  └── /profiles/*  - Manage identity profiles                    │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   PostgreSQL    │ │     Redis       │ │   InsightFace   │
│   (Storage)     │ │    (Cache)      │ │   (ML Model)    │
├─────────────────┤ ├─────────────────┤ ├─────────────────┤
│ - persons       │ │ - Session cache │ │ - buffalo_l     │
│ - person_profiles│ │ - Query cache   │ │ - Detection     │
│ - uploads       │ │                 │ │ - Recognition   │
│ - faces         │ │                 │ │ - 512-dim emb   │
│ - edges         │ │                 │ │                 │
│ - edge_evidence │ │                 │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## Data Flow

### 1. Profile Index Build
```
data/profiles/<Name>/*.jpg
        │
        ▼ POST /admin/rebuild-profile-index
┌───────────────────┐
│ For each image:   │
│ 1. Load image     │
│ 2. Detect face    │
│ 3. Extract 512-d  │
│    embedding      │
│ 4. Store in DB    │
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ persons table     │ ← Name
│ person_profiles   │ ← Embedding (bytea)
└───────────────────┘
```

### 2. Image Ingestion
```
uploads/*.jpg
        │
        ▼ POST /ingest/folder
┌───────────────────────────────────────┐
│ For each image:                       │
│ 1. Detect all faces                   │
│ 2. For each face:                     │
│    a. Compare against all profiles    │
│    b. If score >= 0.45 AND            │
│       margin >= 0.05 → Known person   │
│    c. Else → Create UNKNOWN_XXXX      │
│ 3. For each pair of faces:            │
│    a. Create/update edge              │
│    b. Store evidence                  │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────┐
│ edges table       │ ← Weight (co-appearances)
│ edge_evidence     │ ← Photo proof
└───────────────────┘
```

### 3. Graph Query
```
GET /graph/ego?person=Barack Obama&depth=2
        │
        ▼
┌───────────────────────────────────────┐
│ 1. Find person by name                │
│ 2. BFS traversal to depth N           │
│ 3. Collect nodes and edges            │
│ 4. Return subgraph                    │
└───────────────────────────────────────┘
        │
        ▼
{
  "center": "Barack Obama",
  "nodes": [...],
  "edges": [...]
}
```

## Database Schema

### Core Tables

| Table | Purpose |
|-------|---------|
| `persons` | Identity registry (known + unknown) |
| `person_profiles` | Face embeddings (512-dim vectors) |
| `uploads` | Processed image records |
| `faces` | Detected faces with bounding boxes |
| `edges` | Relationship graph (weighted) |
| `edge_evidence` | Photo proof for each edge |
| `processed_images` | Idempotency tracking |

### Key Relationships

```sql
persons 1──N person_profiles  (one person, multiple reference photos)
persons N──M persons          (via edges table, weighted)
edges   1──N edge_evidence    (one edge, multiple photo proofs)
uploads 1──N faces            (one photo, multiple faces)
faces   N──1 persons          (face matched to person)
```

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Frontend | Next.js 14, React 18 | UI and API proxy |
| Backend | FastAPI, Python 3.11 | REST API |
| Database | PostgreSQL 16 | Persistent storage |
| Cache | Redis 7 | Session/query cache |
| ML Model | InsightFace (buffalo_l) | Face detection/recognition |
| Visualization | vis-network | Graph rendering |
| Container | Docker, Docker Compose | Orchestration |

## Security Considerations

1. **Input Validation**: All uploads validated for image types
2. **SQL Injection**: Parameterized queries via psycopg2
3. **File Storage**: Uploaded files stored outside web root
4. **No Auth**: Current version has no authentication (demo only)

## Performance Notes

1. **Model Loading**: InsightFace buffalo_l (~350MB) loads lazily on first request
2. **Embedding Storage**: 512 floats × 4 bytes = 2KB per face, stored as bytea
3. **Batch Processing**: `/ingest/folder` processes all images in one transaction
4. **Idempotency**: `processed_images` table prevents re-processing

## Directory Structure

```
connections-social/
├── backend/                # FastAPI application
│   ├── app/
│   │   ├── main.py         # Application entry point
│   │   ├── config.py       # Configuration
│   │   ├── db.py           # Database connection
│   │   └── routes/         # API endpoints
│   ├── requirements.txt
│   └── tests/
├── frontend/               # Next.js application
│   ├── app/                # App router pages
│   ├── components/         # React components
│   └── lib/                # Utilities
├── infra/                  # Infrastructure
│   ├── docker/
│   │   └── init.sql        # Database schema
│   └── docker-compose.yml  # Service orchestration
├── scripts/                # Utility scripts
├── data/                   # Data files
│   ├── profiles/           # Reference face images
│   └── demo_uploads/       # Demo group photos
├── docs/                   # Documentation
└── assets/                 # Screenshots, diagrams
```
