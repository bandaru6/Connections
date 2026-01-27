#!/bin/bash
# Demo script - starts all services and seeds data

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Connections Social Demo ==="
echo ""

cd "$PROJECT_DIR"

# Start services
echo "Starting services..."
docker compose -f infra/docker-compose.yml up -d

# Wait for services
echo "Waiting for services to be healthy..."
sleep 5

# Check health
until docker compose -f infra/docker-compose.yml ps | grep -q "healthy"; do
    echo "  Waiting..."
    sleep 3
done

echo "Services are ready!"
echo ""

# Run seed
"$SCRIPT_DIR/seed.sh"
