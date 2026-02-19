.PHONY: up down reset backend frontend seed download-nba download-nfl download-all status help

# Default target
help:
	@echo "Athlete Lookalike - Development Commands"
	@echo ""
	@echo "Infrastructure:"
	@echo "  make up        - Start PostgreSQL and Redis containers"
	@echo "  make down      - Stop all containers"
	@echo "  make reset     - Stop containers, remove volumes, and restart"
	@echo ""
	@echo "Development:"
	@echo "  make backend   - Start the FastAPI backend (port 8000)"
	@echo "  make frontend  - Start the Next.js frontend (port 3001)"
	@echo ""
	@echo "Data:"
	@echo "  make download-nba  - Download NBA player headshots"
	@echo "  make download-nfl  - Download NFL player headshots"
	@echo "  make download-all  - Download all athlete headshots"
	@echo "  make seed          - Build face embeddings from downloaded images"
	@echo ""
	@echo "Status:"
	@echo "  make status    - Check health of all services"

# Infrastructure
up:
	docker compose up -d
	@echo "Waiting for services to be healthy..."
	@sleep 3
	@make status

down:
	docker compose down

reset:
	docker compose down -v
	docker compose up -d
	@sleep 3
	@make status

# Development servers
backend:
	cd backend && \
	python -m venv venv 2>/dev/null || true && \
	. venv/bin/activate && \
	pip install -r requirements.txt -q && \
	DATABASE_URL=postgresql://athlete:athlete@localhost:5434/athlete_lookalike \
	REDIS_URL=redis://localhost:6380/0 \
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && \
	npm install && \
	npm run dev -- -p 3001

# Data download
download-nba:
	cd backend && \
	. venv/bin/activate 2>/dev/null || python -m venv venv && . venv/bin/activate && \
	pip install requests -q && \
	python ../scripts/download_athletes.py --league nba

download-nfl:
	cd backend && \
	. venv/bin/activate 2>/dev/null || python -m venv venv && . venv/bin/activate && \
	pip install requests -q && \
	python ../scripts/download_athletes.py --league nfl

download-all:
	cd backend && \
	. venv/bin/activate 2>/dev/null || python -m venv venv && . venv/bin/activate && \
	pip install requests -q && \
	python ../scripts/download_athletes.py --league all

download-current:
	cd backend && \
	. venv/bin/activate 2>/dev/null || python -m venv venv && . venv/bin/activate && \
	pip install requests -q && \
	python ../scripts/download_athletes.py --league all --current-only

# Seed database with embeddings
seed:
	@echo "Building face embeddings from downloaded images..."
	curl -X POST http://localhost:8000/admin/rebuild-index | python -m json.tool

# Status check
status:
	@echo "=== Service Health ==="
	@echo -n "PostgreSQL: " && (docker exec athlete-lookalike-db pg_isready -U athlete -d athlete_lookalike 2>/dev/null && echo "healthy") || echo "not running"
	@echo -n "Redis: " && (docker exec athlete-lookalike-redis redis-cli ping 2>/dev/null) || echo "not running"
	@echo -n "Backend: " && (curl -s http://localhost:8000/health | grep -q healthy && echo "healthy") || echo "not running"
	@echo ""
	@echo "=== Quick Start ==="
	@echo "1. make up              # Start databases"
	@echo "2. make download-all    # Download athlete photos"
	@echo "3. make backend         # Start API server"
	@echo "4. make seed            # Build embeddings"
