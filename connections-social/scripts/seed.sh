#!/bin/bash
# Seed script - rebuilds profile index and ingests demo photos

set -e

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"

echo "=== Connections Social Seed Script ==="
echo "Backend URL: $BACKEND_URL"
echo ""

# Wait for backend to be ready
echo "Waiting for backend..."
until curl -s "$BACKEND_URL/health" > /dev/null 2>&1; do
    sleep 2
done
echo "Backend is ready!"
echo ""

# Step 1: Rebuild profile index
echo "Step 1: Rebuilding profile index..."
curl -s -X POST "$BACKEND_URL/admin/rebuild-profile-index" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f\"  Persons created: {data.get('persons_created', 'N/A')}\")
print(f\"  Profiles inserted: {data.get('profiles_inserted', 'N/A')}\")
print(f\"  Images rejected: {data.get('images_rejected', 'N/A')}\")
"
echo ""

# Step 2: Copy demo uploads to uploads directory
echo "Step 2: Copying demo photos to uploads..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cp -n "$PROJECT_DIR/data/demo_uploads/"* "$PROJECT_DIR/uploads/" 2>/dev/null || true
echo "  Done"
echo ""

# Step 3: Ingest folder
echo "Step 3: Ingesting photos..."
curl -s -X POST "$BACKEND_URL/ingest/folder" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f\"  Images processed: {data.get('processed', 'N/A')}\")
print(f\"  Faces detected: {data.get('total_faces_detected', 'N/A')}\")
print(f\"  Known matches: {data.get('total_known_matches', 'N/A')}\")
print(f\"  Edges created: {data.get('total_edges_created', 'N/A')}\")
"
echo ""

echo "=== Seed complete! ==="
echo "Frontend: http://localhost:3000"
echo "Backend:  http://localhost:8000"
echo "API Docs: http://localhost:8000/docs"
