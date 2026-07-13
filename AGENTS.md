# AGENTS

## Project summary
- Async-only FastAPI service using SQLModel + SQLAlchemy async engine
- Alembic migrations with async setup
- Postgres via Bitnami Helm chart in k3d/DevSpace
- Prometheus `/metrics` endpoint and ECS JSON logging

## Key commands
- Install deps: `uv sync --dev`
- Run app locally: `uv run uvicorn app.main:app --reload`
- Run tests: `uv run pytest`
- Run migrations: `alembic upgrade head`
- DevSpace (k3d): `devspace dev -p dev`

## Layout
- `app/main.py` FastAPI app
- `app/api/` routers
- `app/models/` SQLModel models
- `app/services/` CRUD helpers
- `app/db/` async engine/session
- `alembic/` migrations
- `k8s/` app manifests
- `devspace.yaml` deployment config

## Conventions
- Async-only endpoints and DB access
- Use SQLModel schemas for Create/Read/Update
- Avoid authentication in this service
- Do not add code to `__init__.py`; use explicit imports
- Always generate Alembic migrations via `alembic revision --autogenerate`
- Tests should use real Postgres via `pytest-docker`, not SQLite
- Prefer SQLModel relationship annotations that are SQLAlchemy-compatible
- Keep stub packages unpinned so they stay at the latest version
- List endpoints use `fastapi-pagination` and should avoid N+1 queries
- Use Alembic migrations in tests (no `create_all`/`drop_all`)
- Logging is configured via `app/core/logging.yaml`; avoid configuring it in code
- Health checks should enforce a DB timeout and return 503 on failure
- Keep module-level docstrings for key files and update Sphinx docs in `docs/`
