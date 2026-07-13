How To Add A Model + Endpoint
=============================

Checklist for adding a new resource:

1. Create SQLModel table + schemas
   - Add a new model in ``app/models/``.
   - Use UUID primary keys and DB-managed timestamps.
   - Add any indexes and constraints you need.

2. Register the model for Alembic
   - Import the model in ``app/db/base.py`` so Alembic sees it.

3. Generate a migration
   - ``alembic revision --autogenerate -m "add <model>"``
   - Review the migration and ensure constraints/indexes are included.

4. Add services
   - Create CRUD helpers in ``app/services/``.

5. Add API endpoints
   - Define routes in ``app/api/``.
   - Use ``fastapi-pagination`` for list endpoints.
   - Prefer bulk queries to avoid N+1 patterns.

6. Add tests
   - Add CRUD tests under ``app/tests/``.
   - Ensure pytest-alembic drift checks still pass.

7. Update docs
   - Add endpoints to ``README.md`` and docs if needed.
