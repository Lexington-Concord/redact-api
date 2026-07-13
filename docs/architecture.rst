Architecture
============

High-level flow:

- Requests enter FastAPI routes under ``app/api/``.
- Route handlers call service helpers in ``app/services/``.
- Services use the async SQLAlchemy session provided by ``app/db/session.py``.
- SQLModel defines tables and schemas in ``app/models/``.
- Alembic reads ``SQLModel.metadata`` for migrations.

Runtime components:

- Postgres 18 for persistence
- Prometheus metrics via ``/metrics``
- ECS JSON logs for structured logging
