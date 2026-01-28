# Connections Social - Makefile
# Hybrid setup: Databases in Docker, App runs locally

.PHONY: help up down reset seed logs status clean backend frontend stop demo

help:
	@echo "Connections Social - Commands"
	@echo ""
	@echo "Quick Start:"
	@echo "  make up        Start databases (Postgres + Redis)"
	@echo "  make backend   Start backend server (new terminal)"
	@echo "  make frontend  Start frontend server (new terminal)"
	@echo "  make seed      Seed demo data"
	@echo ""
	@echo "Other:"
	@echo "  make down      Stop databases"
	@echo "  make reset     Wipe data and restart"
	@echo "  make status    Check service health"
	@echo "  make stop      Stop backend + frontend"
	@echo "  make logs      Tail database logs"
	@echo ""

# Start databases
up:
	docker compose up -d
	@echo ""
	@echo "Databases started:"
	@echo "  PostgreSQL: localhost:5433"
	@echo "  Redis:      localhost:6379"
	@echo ""
	@echo "Next steps:"
	@echo "  make backend   # Terminal 1"
	@echo "  make frontend  # Terminal 2"
	@echo "  make seed      # Seed demo data"

# Stop databases
down:
	docker compose down

# Reset everything
reset:
	docker compose down -v
	docker compose up -d
	@echo "Waiting for database..."
	@sleep 5
	@echo "Ready! Run: make backend"

# Seed demo data
seed:
	@echo "Rebuilding profile index..."
	@curl -s -X POST http://localhost:8000/admin/rebuild-profile-index | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Profiles: {d.get(\"persons_created\", 0)}')" 2>/dev/null || echo "  Backend not running - start with: make backend"
	@echo "Ingesting demo photos..."
	@cp -n data/demo_uploads/* uploads/ 2>/dev/null || true
	@curl -s -X POST http://localhost:8000/ingest/folder | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Images: {d.get(\"processed\", 0)}, Edges: {d.get(\"total_edges_created\", 0)}')" 2>/dev/null || echo "  Backend not running"
	@echo "Done! Open http://localhost:3000"

# Start backend
backend:
	@echo "Starting backend on http://localhost:8000..."
	@echo "API docs: http://localhost:8000/docs"
	@cd backend && \
		DATABASE_URL="postgresql://connections:connections@localhost:5433/connections" \
		python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Start frontend
frontend:
	@echo "Starting frontend on http://localhost:3000..."
	cd frontend && npm run dev

# Stop local servers
stop:
	@pkill -f "uvicorn app.main:app" 2>/dev/null || true
	@pkill -f "next dev" 2>/dev/null || true
	@echo "Stopped"

# Check status
status:
	@echo "Databases:"
	@docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || echo "  Not running"
	@echo ""
	@echo "Services:"
	@curl -s http://localhost:8000/health 2>/dev/null && echo "" || echo "  Backend: Not running"
	@curl -s http://localhost:3000 >/dev/null 2>&1 && echo "  Frontend: OK" || echo "  Frontend: Not running"

# View logs
logs:
	docker compose logs -f
