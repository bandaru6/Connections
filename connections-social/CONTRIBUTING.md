# Contributing to Connections Social

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- Node.js 18+

### One-Command Demo
```bash
make demo
```

### Local Development

1. **Start databases:**
   ```bash
   make dev
   ```

2. **Backend (Terminal 1):**
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```

3. **Frontend (Terminal 2):**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

## Project Structure

```
connections-social/
├── backend/          # FastAPI application
├── frontend/         # Next.js application
├── infra/            # Docker, database scripts
├── scripts/          # Dev & maintenance scripts
├── data/             # Profiles and demo images
├── docs/             # Documentation
└── assets/           # Screenshots, diagrams
```

## Code Style

### Python (Backend)
- Follow PEP 8
- Use type hints
- Docstrings for public functions

```bash
# Lint
cd backend
pip install ruff
ruff check .

# Format
ruff format .
```

### TypeScript (Frontend)
- Follow ESLint config
- Use TypeScript strict mode

```bash
# Lint
cd frontend
npm run lint

# Type check
npx tsc --noEmit
```

## Testing

### Backend
```bash
cd backend
pip install pytest pytest-asyncio
pytest
```

### Frontend
```bash
cd frontend
npm test
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and linting
5. Commit with descriptive message
6. Push to your fork
7. Open a Pull Request

## Commit Messages

Use conventional commits:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation
- `refactor:` Code refactoring
- `test:` Tests
- `chore:` Maintenance

## Architecture Decisions

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for system design details.

## API Reference

See [docs/API.md](docs/API.md) for endpoint documentation.

## Questions?

Open an issue or reach out to the maintainers.
