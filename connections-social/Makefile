# Connections Social - Makefile
# Run `make help` to see available commands

.PHONY: help demo up down reset seed logs status clean dev build test lint

# Default target
help:
	@echo "Connections Social - Available Commands"
	@echo ""
	@echo "  make demo      Start everything + seed demo data"
	@echo "  make up        Start all services"
	@echo "  make down      Stop all services (preserves data)"
	@echo "  make reset     Wipe all data and restart fresh"
	@echo "  make seed      Populate demo data"
	@echo "  make logs      Tail logs from all services"
	@echo "  make status    Show service health status"
	@echo "  make clean     Remove all containers, images, and volumes"
	@echo "  make dev       Start only Postgres/Redis for local dev"
	@echo "  make build     Build all Docker images"
	@echo "  make test      Run tests"
	@echo "  make lint      Run linters"
	@echo ""

# Docker Compose file location
DC := docker compose -f infra/docker-compose.yml

# Start everything and seed data
demo: up
	@echo "Waiting for services to be healthy..."
	@sleep 10
	@$(MAKE) seed

# Start all services
up:
	$(DC) up -d
	@echo ""
	@echo "Services starting..."
	@echo "  Frontend: http://localhost:3000"
	@echo "  Backend:  http://localhost:8000"
	@echo "  API Docs: http://localhost:8000/docs"

# Stop services
down:
	$(DC) down

# Wipe everything and restart
reset:
	$(DC) down -v
	$(DC) up -d
	@sleep 5
	@$(MAKE) seed

# Seed demo data
seed:
	@echo "Rebuilding profile index..."
	@curl -s -X POST http://localhost:8000/admin/rebuild-profile-index | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Created {d.get(\"persons_created\", 0)} persons')"
	@echo "Copying demo photos..."
	@cp -n data/demo_uploads/* uploads/ 2>/dev/null || true
	@echo "Ingesting photos..."
	@curl -s -X POST http://localhost:8000/ingest/folder | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Processed {d.get(\"processed\", 0)} images, {d.get(\"total_edges_created\", 0)} edges')"
	@echo "Done!"

# View logs
logs:
	$(DC) logs -f

# Check status
status:
	$(DC) ps
	@echo ""
	@curl -s http://localhost:8000/health 2>/dev/null && echo "" || echo "Backend: Not responding"
	@curl -s http://localhost:3000 >/dev/null 2>&1 && echo "Frontend: OK" || echo "Frontend: Not responding"

# Remove everything
clean:
	$(DC) down -v --rmi all
	rm -rf uploads/*.jpg uploads/*.png uploads/*.jpeg 2>/dev/null || true

# Start only databases for local development
dev:
	$(DC) up -d postgres redis
	@echo ""
	@echo "Databases started:"
	@echo "  PostgreSQL: localhost:5433"
	@echo "  Redis:      localhost:6379"
	@echo ""
	@echo "Run backend:  cd backend && source venv/bin/activate && uvicorn app.main:app --reload"
	@echo "Run frontend: cd frontend && npm run dev"

# Build images
build:
	$(DC) build

# Run tests
test:
	@echo "Running backend tests..."
	cd backend && python -m pytest tests/ -v || true
	@echo ""
	@echo "Running frontend tests..."
	cd frontend && npm test || true

# Run linters
lint:
	@echo "Linting backend..."
	cd backend && python -m ruff check . || true
	@echo ""
	@echo "Linting frontend..."
	cd frontend && npm run lint || true
