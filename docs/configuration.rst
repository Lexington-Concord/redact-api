Configuration Reference
=======================

All configuration is done via environment variables. The ``Settings`` class in
``redact_api/core/config.py`` defines all available options with their
defaults and descriptions.

Quick Start
-----------

1. Copy ``dotenv.example`` to ``.env``
2. Edit values as needed for your environment
3. The application loads settings automatically on startup

Environment Variables
---------------------

The following environment variables are available. All have sensible defaults
for local development.

.. autoclass:: redact_api.core.config.Settings
   :members:
   :undoc-members:
   :show-inheritance:
   :member-order: bysource

   .. rubric:: Application Settings

   - ``APP_NAME`` - Application name (default: ``redact_api``)
   - ``ENVIRONMENT`` - Deployment environment (default: ``local``)
   - ``LOG_LEVEL`` - Logging level (default: ``debug``)

   .. rubric:: Database Settings

   - ``DATABASE_URL`` - PostgreSQL connection string
   - ``SQLALCHEMY_ECHO`` - Enable SQL query logging (default: ``false``)
   - ``DB_POOL_SIZE`` - Connection pool size (default: ``5``)
   - ``DB_MAX_OVERFLOW`` - Max connections beyond pool (default: ``10``)
   - ``DB_POOL_TIMEOUT`` - Connection wait timeout (default: ``30``)
   - ``DB_POOL_RECYCLE`` - Connection recycle time (default: ``3600``)
   - ``DB_POOL_PRE_PING`` - Test connections before use (default: ``true``)

   .. rubric:: Authentication Settings

   - ``AUTH_PROVIDER_TYPE`` - Auth provider (``none``, ``ory``, ``auth0``, ``keycloak``, ``cognito``)
   - ``AUTH_PROVIDER_URL`` - Auth provider base URL
   - ``AUTH_PROVIDER_ISSUER`` - Expected JWT issuer
   - ``JWT_ALGORITHM`` - JWT signing algorithm (default: ``RS256``)
   - ``JWT_PUBLIC_KEY`` - Public key for JWT validation

   .. rubric:: Storage Settings

   - ``STORAGE_PROVIDER`` - Storage backend (``local``, ``azure``, ``aws_s3``, ``gcs``)
   - ``STORAGE_LOCAL_PATH`` - Local storage path (default: ``./uploads``)
   - ``STORAGE_AZURE_CONTAINER`` - Azure blob container name
   - ``STORAGE_AZURE_CONNECTION_STRING`` - Azure connection string
   - ``STORAGE_AWS_BUCKET`` - S3 bucket name
   - ``STORAGE_AWS_REGION`` - AWS region
   - ``STORAGE_GCS_BUCKET`` - GCS bucket name
   - ``STORAGE_GCS_PROJECT_ID`` - Google Cloud project ID

   .. rubric:: Security Settings

   - ``ENFORCE_TENANT_ISOLATION`` - Enable multi-tenant isolation (default: ``true``)
   - ``CORS_ALLOWED_ORIGINS`` - Allowed CORS origins (comma-separated)

   .. rubric:: Feature Flags

   - ``ENABLE_METRICS`` - Enable Prometheus metrics (default: ``true``)
   - ``ACTIVITY_LOGGING_ENABLED`` - Enable audit logging (default: ``true``)
   - ``ACTIVITY_LOG_RETENTION_DAYS`` - Log retention period (default: ``90``)

Configuration Errors
--------------------

.. autoclass:: redact_api.core.config.ConfigurationError
   :members:
   :show-inheritance:

Validation
----------

The ``Settings.validate_config()`` method checks configuration for production
readiness. Call this during application startup to fail fast on misconfiguration.

.. code-block:: python

   from redact_api.core.config import settings, ConfigurationError

   try:
       warnings = settings.validate_config()
       for warning in warnings:
           logger.warning("Configuration warning: %s", warning)
   except ConfigurationError as e:
       logger.error("Configuration error: %s", e)
       raise SystemExit(1)
