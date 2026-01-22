#!/usr/bin/env bash
# demo.sh - Run a quick demo of the Connections Social API
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
API_URL="${API_URL:-http://localhost:8000}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
SYNC_DEMO=false
for arg in "$@"; do
    case $arg in
        --sync-demo)
            SYNC_DEMO=true
            shift
            ;;
        *)
            echo -e "${RED}Unknown argument: $arg${NC}"
            echo "Usage: $0 [--sync-demo]"
            echo "  --sync-demo  Copy images from demo_uploads/ to uploads/ before ingestion"
            exit 1
            ;;
    esac
done

# Pretty print JSON if python available
json_pp() {
    if command -v python3 &> /dev/null; then
        python3 -m json.tool 2>/dev/null || cat
    elif command -v python &> /dev/null; then
        python -m json.tool 2>/dev/null || cat
    else
        cat
    fi
}

echo -e "${BLUE}=== Connections Social Demo ===${NC}"
echo ""

# Check docker services
echo -e "${YELLOW}Checking Docker services...${NC}"
cd "$REPO_ROOT"

if ! docker compose ps --status running 2>/dev/null | grep -q "postgres"; then
    echo -e "${YELLOW}PostgreSQL not running. Starting docker services...${NC}"
    docker compose up -d
    echo "Waiting for services to be ready..."
    sleep 3
fi

if docker compose ps --status running 2>/dev/null | grep -q "postgres"; then
    echo -e "${GREEN}Docker services are running.${NC}"
else
    echo -e "${RED}Failed to start Docker services. Please check docker compose.${NC}"
    exit 1
fi

# Check venv exists
if [ ! -d "$REPO_ROOT/backend/venv" ]; then
    echo ""
    echo -e "${RED}Python virtual environment not found.${NC}"
    echo "Please create it first:"
    echo ""
    echo "  cd $REPO_ROOT/backend"
    echo "  python -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    echo ""
    exit 1
fi

# Check if backend is running
echo ""
echo -e "${YELLOW}Checking backend...${NC}"
if ! curl -s "$API_URL/health" > /dev/null 2>&1; then
    echo -e "${RED}Backend is not running.${NC}"
    echo "Please start it in another terminal:"
    echo ""
    echo "  cd $REPO_ROOT/backend"
    echo "  source venv/bin/activate"
    echo "  uvicorn app.main:app --host 0.0.0.0 --port 8000"
    echo ""
    exit 1
fi
echo -e "${GREEN}Backend is running at $API_URL${NC}"

# Sync demo images if requested
if [ "$SYNC_DEMO" = true ]; then
    echo ""
    echo -e "${YELLOW}Syncing demo images...${NC}"
    DEMO_DIR="$REPO_ROOT/demo_uploads"
    UPLOADS_DIR="$REPO_ROOT/uploads"

    if [ ! -d "$DEMO_DIR" ]; then
        echo -e "${RED}demo_uploads/ directory not found.${NC}"
        echo "Create it and add some multi-person images:"
        echo "  mkdir -p $DEMO_DIR"
        echo "  cp /path/to/images/*.jpg $DEMO_DIR/"
    else
        mkdir -p "$UPLOADS_DIR"
        count=0
        for ext in jpg jpeg png JPG JPEG PNG; do
            for f in "$DEMO_DIR"/*."$ext" /dev/null; do
                if [ -f "$f" ]; then
                    fname=$(basename "$f")
                    if [ ! -f "$UPLOADS_DIR/$fname" ]; then
                        cp "$f" "$UPLOADS_DIR/"
                        ((count++)) || true
                    fi
                fi
            done
        done
        echo -e "${GREEN}Copied $count new images to uploads/${NC}"
    fi
fi

echo ""
echo -e "${BLUE}--- 1. Rebuild Profile Index ---${NC}"
echo "POST $API_URL/admin/rebuild-profile-index"
curl -s -X POST "$API_URL/admin/rebuild-profile-index" | json_pp
echo ""

echo ""
echo -e "${BLUE}--- 2. Ingest Photos ---${NC}"
echo "POST $API_URL/ingest/folder"
curl -s -X POST "$API_URL/ingest/folder" | json_pp
echo ""

echo ""
echo -e "${BLUE}--- 3. Graph Summary ---${NC}"
echo "GET $API_URL/graph/summary"
curl -s "$API_URL/graph/summary" | json_pp
echo ""

echo ""
echo -e "${BLUE}--- 4. Neighbors of Joe Biden ---${NC}"
echo "GET $API_URL/graph/neighbors?person=Joe%20Biden"
response=$(curl -s "$API_URL/graph/neighbors?person=Joe%20Biden")
if echo "$response" | grep -q "not found"; then
    echo -e "${YELLOW}Joe Biden not in graph (no matching photos ingested)${NC}"
    echo "$response" | json_pp
else
    echo "$response" | json_pp
fi
echo ""

echo ""
echo -e "${GREEN}=== Demo Complete ===${NC}"
echo ""
echo "Next steps:"
echo "  - Add more images to uploads/ and run: curl -X POST $API_URL/ingest/folder"
echo "  - Explore the graph: curl '$API_URL/graph/summary?include_unknown=false'"
echo "  - Try ego network: curl '$API_URL/graph/ego?person=Barack%20Obama&depth=2'"
