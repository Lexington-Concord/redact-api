Decision Log
============

Why the template looks the way it does:

- Async-only FastAPI and SQLAlchemy to match modern Python concurrency.
- SQLModel for schema + ORM models, Alembic for migrations.
- UUID primary keys to avoid ID collisions and simplify distributed systems.
- ``updated_at`` handled by Postgres triggers to prevent ORM bypass.
- ECS JSON logging for structured log ingestion.
- Prometheus metrics via ``/metrics`` for observability.
- k3d + DevSpace for local Kubernetes workflows.
- Tests use Postgres with Alembic drift detection.
