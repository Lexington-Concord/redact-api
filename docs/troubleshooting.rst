Troubleshooting
===============

Common issues and fixes:

Migrations not detecting tables
  Ensure the new model is imported in ``app/db/base.py``. Alembic uses
  ``SQLModel.metadata`` and will not see models that are not imported.

"relation does not exist" in tests
  The test harness uses Alembic migrations. Confirm the migration exists and
  pytest-alembic runs without errors. Check the containerized Postgres logs.

DevSpace cannot find pods
  Confirm the image selector matches the Helm chart label and that the build
  step ran. The default selector uses ``app.kubernetes.io/name=devspace-app``.

Health endpoint hangs
  The health endpoint enforces a short DB timeout. If it hangs, ensure the
  DB connection is healthy and the timeout setting is applied.

Logging level mismatch
  Logging is configured via ``app/core/logging.yaml`` only. If logs are too
  noisy or too quiet, update the YAML file or provide an alternate config.
