Conventions
===========

High-level rules we stick to in this template:

- Async-only API and database access.
- Alembic is the source of truth for schema changes.
- SQLModel table discovery happens via ``app/db/base.py``.
- Avoid putting code in ``__init__.py`` modules.
- Logging is configured via ``app/core/logging.yaml``.
- Health checks must fail fast and return 503 on DB issues.
- List endpoints use ``fastapi-pagination`` and stable ordering.

File and package layout:

- ``app/main.py``: FastAPI app wiring.
- ``app/api/``: API endpoints.
- ``app/models/``: SQLModel tables + read/write schemas.
- ``app/services/``: DB-facing CRUD helpers.
- ``app/db/``: async engine/session and Alembic model registry.
- ``alembic/``: migration environment and revisions.
- ``tests/``: pytest + postgres + alembic drift checks.
