# Connections Social Frontend

A minimal Next.js frontend for the Connections Social API.

## Quick Start

### 1. Start the Backend Services

```bash
# Terminal 1: Start Docker (Postgres)
docker compose up -d

# Terminal 2: Start FastAPI backend
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2. Start the Frontend

```bash
# Terminal 3: Start Next.js frontend
cd frontend
npm install
npm run dev
```

### 3. Open the App

Open **http://localhost:3000** in your browser.

## Pages

| Route | Description |
|-------|-------------|
| `/` | Dashboard - Health check, rebuild, reset, ingest, summary |
| `/explore` | Explore - Query neighbors and ego networks |

## Demo Flow

1. Go to **Dashboard** (http://localhost:3000)
2. Click **Rebuild Profile Index** to index known faces from `data/profiles/`
3. Click **Ingest Folder** to process photos from `uploads/`
4. Click **Refresh Summary** to see graph stats
5. Go to **Explore** and enter a person name (e.g., "Barack Obama")
6. Click **Get Neighbors** or **Get Ego Network**

## API Proxy

The frontend proxies all `/api/*` requests to the backend at `http://127.0.0.1:8000`.

- `GET /api/health` → `GET http://127.0.0.1:8000/health`
- `POST /api/admin/rebuild-profile-index` → `POST http://127.0.0.1:8000/admin/rebuild-profile-index`
- etc.

## Configuration

Environment variables in `.env.local`:

```
BACKEND_URL=http://127.0.0.1:8000
```

## Features

- **Loading states** on all buttons
- **Error handling** with visible error messages
- **JSON panel** showing last API response (great for demos)
- **Force ingest** toggle to re-process already-ingested images
- **Include unknown** toggle to show/hide UNKNOWN_* persons
- **Clickable neighbors** to quickly explore the graph
