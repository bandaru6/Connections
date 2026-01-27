# Connections Social - Makefile
# Run `make help` to see available commands

.PHONY: help demo up down reset seed logs status clean dev backend frontend run test lint

# Default target
help:
	@echo "Connections Social - Available Commands"
	@echo ""
	@echo "  make demo      Start databases, backend, frontend + seed data"
	@echo "  make run       Start databases + backend + frontend (no seed)"
	@echo "  make dev       Start only Postgres/Redis (for local dev)"
	@echo "  make backend   Start backend server (requires databases)"
	@echo "  make frontend  Start frontend server"
	@echo "  make seed      Rebuild profiles and ingest demo photos"
	@echo "  make down      Stop database services"
	@echo "  make reset     Wipe all data and restart fresh"
	@echo "  make status    Show service health status"
	@echo "  make logs      Tail database logs"
	@echo "  make clean     Remove all containers, images, and volumes"
	@echo "  make test      Run tests"
	@echo "  make lint      Run linters"
	@echo ""

# Docker Compose file location
DC := docker compose -f infra/docker-compose.yml

# Full demo: databases + backend + frontend + seed
demo: dev
	@echo ""
	@echo "Starting backend..."
	@cd backend && source venv/bin/activate 2>/dev/null && \
		DATABASE_URL="postgresql://connections:connections@localhost:5433/connections" \
		nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &
	@echo "Starting frontend..."
	@cd frontend && nohup npm run dev > /tmp/frontend.log 2>&1 &
	@echo "Waiting for services..."
	@sleep 10
	@$(MAKE) seed
	@echo ""
	@echo "Demo ready!"
	@echo "  Frontend: http://localhost:3000"
	@echo "  Backend:  http://localhost:8000"
	@echo "  API Docs: http://localhost:8000/docs"

# Start all services without seeding
run: dev
	@echo ""
	@echo "Starting backend..."
	@cd backend && source venv/bin/activate 2>/dev/null && \
		DATABASE_URL="postgresql://connections:connections@localhost:5433/connections" \
		nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &
	@echo "Starting frontend..."
	@cd frontend && nohup npm run dev > /tmp/frontend.log 2>&1 &
	@sleep 5
	@echo ""
	@echo "Services started:"
	@echo "  Frontend: http://localhost:3000"
	@echo "  Backend:  http://localhost:8000"
	@echo "  API Docs: http://localhost:8000/docs"

# Start only databases
up:
	$(DC) up -d
	@echo ""
	@echo "Databases started:"
	@echo "  PostgreSQL: localhost:5433"
	@echo "  Redis:      localhost:6379"

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

# Start backend server
backend:
	@echo "Starting backend on http://localhost:8000..."
	cd backend && source venv/bin/activate && \
		DATABASE_URL="postgresql://connections:connections@localhost:5433/connections" \
		uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Start frontend server
frontend:
	@echo "Starting frontend on http://localhost:3000..."
	cd frontend && npm run dev

# Stop backend and frontend
stop:
	@pkill -f "uvicorn app.main:app" 2>/dev/null || true
	@pkill -f "next dev" 2>/dev/null || true
	@echo "Stopped backend and frontend"

# Build images (N/A for local dev)
build:
	@echo "No Docker build needed - backend/frontend run locally"
	@echo "To install dependencies:"
	@echo "  Backend:  cd backend && pip install -r requirements.txt"
	@echo "  Frontend: cd frontend && npm install"

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
