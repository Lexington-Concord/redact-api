"""Runtime configuration sourced from environment variables."""

from __future__ import annotations

from pydantic import Field, PrivateAttr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from redact_api.core.storage import StorageProvider


class ConfigurationError(ValueError):
    """Raised when configuration validation fails.

    Inherits from ValueError for semantic clarity - this represents
    invalid configuration values. The exception message contains
    details about which settings are missing or invalid.

    This exception is raised during application startup if required
    configuration is missing or invalid, allowing for fail-fast behavior.

    Example:
        try:
            settings.validate()
        except ConfigurationError as e:
            logger.error("Configuration validation failed: %s", e)
            raise SystemExit(1)
    """


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "redact_api"
    environment: str = "local"
    log_level: str = Field(default="debug", alias="LOG_LEVEL")
    database_url: str = Field(
        default="postgresql+asyncpg://app:app@localhost:5432/app",
        alias="DATABASE_URL",
    )
    sqlalchemy_echo: bool = Field(default=False, alias="SQLALCHEMY_ECHO")
    enable_metrics: bool = Field(default=True, alias="ENABLE_METRICS")

    # Database pool configuration
    db_pool_size: int = Field(
        default=5,
        ge=1,
        le=100,
        alias="DB_POOL_SIZE",
        description="Maximum number of connections to maintain in the pool",
    )
    db_max_overflow: int = Field(
        default=10,
        ge=0,
        le=100,
        alias="DB_MAX_OVERFLOW",
        description="Maximum number of connections to create beyond pool_size",
    )
    db_pool_timeout: int = Field(
        default=30,
        ge=1,
        alias="DB_POOL_TIMEOUT",
        description="Seconds to wait before giving up on getting a connection from pool",
    )
    db_pool_recycle: int = Field(
        default=3600,
        ge=-1,
        alias="DB_POOL_RECYCLE",
        description="Seconds after which to recycle connections (default: 1 hour, -1 to disable)",
    )
    db_pool_pre_ping: bool = Field(
        default=True,
        alias="DB_POOL_PRE_PING",
        description="Test connections for liveness before using them",
    )
    pagination_page_size: int = 50
    pagination_page_size_max: int = 200
    pagination_page_class: str | None = None
    activity_logging_enabled: bool = Field(
        default=True,
        alias="ACTIVITY_LOGGING_ENABLED",
        description="Enable activity logging for audit trail",
    )
    activity_log_retention_days: int = Field(
        default=90,
        alias="ACTIVITY_LOG_RETENTION_DAYS",
        description="Number of days to retain activity logs before archival",
    )
    max_file_size_bytes: int = Field(
        default=50 * 1024 * 1024,
        alias="MAX_FILE_SIZE_BYTES",
        description="Maximum file size for document uploads in bytes (default: 50MB)",
    )
    auth_provider_type: str = Field(
        default="none",
        alias="AUTH_PROVIDER_TYPE",
        description="Authentication provider (none, ory, auth0, keycloak, cognito)",
    )
    auth_provider_url: str | None = Field(
        default=None,
        alias="AUTH_PROVIDER_URL",
        description="Base URL for authentication provider (for token introspection)",
    )
    auth_provider_issuer: str | None = Field(
        default=None,
        alias="AUTH_PROVIDER_ISSUER",
        description="Expected token issuer (iss claim) for JWT validation",
    )
    jwt_algorithm: str = Field(
        default="RS256",
        alias="JWT_ALGORITHM",
        description="JWT algorithm for token validation (RS256, HS256, etc.)",
    )
    jwt_public_key: str | None = Field(
        default=None,
        alias="JWT_PUBLIC_KEY",
        description="Public key for JWT validation (PEM format) or path to key file",
    )
    cors_allowed_origins_raw: str | list[str] = Field(
        default="http://localhost:3000",
        alias="CORS_ALLOWED_ORIGINS",
        description="List of allowed CORS origins (comma-separated string or list)",
    )
    _cors_allowed_origins_cache: list[str] | None = PrivateAttr(default=None)
    enforce_tenant_isolation: bool = Field(
        default=True,
        alias="ENFORCE_TENANT_ISOLATION",
        description=(
            "Enforce tenant isolation for multi-tenant applications. "
            "When True, all endpoints (except public paths) require tenant context. "
            "Disable only for single-tenant deployments or public APIs. "
            "WARNING: Disabling this in a multi-tenant environment creates "
            "severe data leak vulnerabilities."
        ),
    )

    # Logging configuration
    request_id_header: str = Field(
        default="x-request-id",
        alias="REQUEST_ID_HEADER",
        description="HTTP header name for request correlation ID",
    )
    include_request_context_in_logs: bool = Field(
        default=True,
        alias="INCLUDE_REQUEST_CONTEXT_IN_LOGS",
        description="Enable automatic request context logging (user_id, org_id, request_id)",
    )

    # Storage configuration
    storage_provider: StorageProvider = Field(
        default=StorageProvider.LOCAL,
        alias="STORAGE_PROVIDER",
        description="Storage backend (local, azure, aws_s3, gcs)",
    )
    storage_local_path: str = Field(
        default="./uploads",
        alias="STORAGE_LOCAL_PATH",
        description="Local filesystem storage directory (used when provider=local)",
    )

    # Azure Blob Storage configuration
    storage_azure_container: str | None = Field(
        default=None,
        alias="STORAGE_AZURE_CONTAINER",
        description="Azure Blob Storage container name",
    )
    storage_azure_connection_string: str | None = Field(
        default=None,
        alias="STORAGE_AZURE_CONNECTION_STRING",
        description="Azure Storage account connection string",
    )

    # AWS S3 configuration
    storage_aws_bucket: str | None = Field(
        default=None,
        alias="STORAGE_AWS_BUCKET",
        description="AWS S3 bucket name",
    )
    storage_aws_region: str | None = Field(
        default=None,
        alias="STORAGE_AWS_REGION",
        description="AWS region (e.g., us-east-1, eu-west-1)",
    )

    # Google Cloud Storage configuration
    storage_gcs_bucket: str | None = Field(
        default=None,
        alias="STORAGE_GCS_BUCKET",
        description="Google Cloud Storage bucket name",
    )
    storage_gcs_project_id: str | None = Field(
        default=None,
        alias="STORAGE_GCS_PROJECT_ID",
        description="Google Cloud project ID",
    )

    # MinIO / S3-compatible pipeline storage (redaction artifacts + original/redacted PDFs).
    # Distinct from storage_provider/storage_local_path above, which govern the unrelated
    # document-upload path in api/documents.py and are not reused here.
    minio_endpoint: str = Field(
        default="localhost:9000",
        alias="MINIO_ENDPOINT",
        description="MinIO/S3 endpoint host:port for redaction-pipeline object storage",
    )
    minio_access_key: str = Field(
        default="minioadmin",
        alias="MINIO_ACCESS_KEY",
        description="Access key for the redaction-pipeline object store",
    )
    minio_secret_key: str = Field(
        default="minioadmin",
        alias="MINIO_SECRET_KEY",
        description="Secret key for the redaction-pipeline object store",
    )
    minio_bucket: str = Field(
        default="redact-pipeline",
        alias="MINIO_BUCKET",
        description="Bucket holding redaction-pipeline artifacts and original/redacted PDFs",
    )
    minio_secure: bool = Field(
        default=False,
        alias="MINIO_SECURE",
        description="Use HTTPS when connecting to the MinIO/S3 endpoint",
    )

    # TaskIQ async pipeline (redact-api#8): the ingest/detect/apply tasks publish to
    # RabbitMQ and record results in Redis. Same env-var names as the worker template.
    rabbitmq_url: str = Field(
        default="amqp://guest:guest@localhost:5672/",
        alias="RABBITMQ_URL",
        description="RabbitMQ AMQP connection URL for the async task broker",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        alias="REDIS_URL",
        description="Redis connection URL for the TaskIQ result backend",
    )

    @field_validator("jwt_algorithm")
    @classmethod
    def validate_jwt_algorithm(cls, value: str) -> str:
        """Validate JWT algorithm is secure.

        Only allows asymmetric algorithms (RSA, ECDSA, RSA-PSS) which require
        public/private key pairs. Symmetric algorithms like HS256 are prohibited
        because they require sharing secret keys between services.

        Args:
            value: JWT algorithm name (e.g., "RS256")

        Returns:
            Validated algorithm name

        Raises:
            ValueError: If algorithm is not in allowed list
        """
        allowed_algorithms = [
            "RS256",
            "RS384",
            "RS512",  # RSA with SHA
            "ES256",
            "ES384",
            "ES512",  # ECDSA
            "PS256",
            "PS384",
            "PS512",  # RSA-PSS
        ]
        if value not in allowed_algorithms:
            error_msg = f"JWT algorithm '{value}' not allowed. Must be one of: {', '.join(allowed_algorithms)}"
            raise ValueError(error_msg)
        return value

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Get parsed list of allowed CORS origins.

        Parses comma-separated string from environment variable into list.
        Results are cached to avoid re-parsing on every access.

        Returns:
            List of allowed CORS origins (e.g., ["http://localhost:3000"])

        Examples:
            # From comma-separated string
            Settings(CORS_ALLOWED_ORIGINS="http://localhost:3000,http://localhost:3001")
            .cors_allowed_origins
            # ["http://localhost:3000", "http://localhost:3001"]

            # From list
            Settings(CORS_ALLOWED_ORIGINS=["http://localhost:3000"])
            .cors_allowed_origins
            # ["http://localhost:3000"]
        """
        # Return cached value if available
        if self._cors_allowed_origins_cache is not None:
            return self._cors_allowed_origins_cache

        # Parse raw value (either string or list)
        if isinstance(self.cors_allowed_origins_raw, str):
            parsed = [origin.strip() for origin in self.cors_allowed_origins_raw.split(",") if origin.strip()]
        else:
            parsed = self.cors_allowed_origins_raw

        # Cache the result
        self._cors_allowed_origins_cache = parsed
        return parsed

    def _validate_auth_config(self, errors: list[str], warnings: list[str]) -> None:
        """Validate authentication configuration."""
        if self.auth_provider_type == "none":
            return

        if not self.auth_provider_url:
            errors.append(f"AUTH_PROVIDER_URL required when AUTH_PROVIDER_TYPE={self.auth_provider_type}")
        if not self.auth_provider_issuer:
            errors.append(f"AUTH_PROVIDER_ISSUER required when AUTH_PROVIDER_TYPE={self.auth_provider_type}")
        # JWT_PUBLIC_KEY is recommended but not required (JWKS fallback exists)
        if not self.jwt_public_key and self.auth_provider_type != "cognito":
            warnings.append("JWT_PUBLIC_KEY not configured - will use remote validation (slower, more network calls)")

    def _validate_storage_config(self, errors: list[str]) -> None:
        """Validate storage provider configuration."""
        if self.storage_provider == StorageProvider.AZURE:
            if not self.storage_azure_container:
                errors.append("STORAGE_AZURE_CONTAINER required for Azure storage")
            if not self.storage_azure_connection_string:
                errors.append("STORAGE_AZURE_CONNECTION_STRING required for Azure storage")
        elif self.storage_provider == StorageProvider.AWS_S3:
            if not self.storage_aws_bucket:
                errors.append("STORAGE_AWS_BUCKET required for S3 storage")
            if not self.storage_aws_region:
                errors.append("STORAGE_AWS_REGION required for S3 storage")
        elif self.storage_provider == StorageProvider.GCS:
            if not self.storage_gcs_bucket:
                errors.append("STORAGE_GCS_BUCKET required for GCS storage")
            if not self.storage_gcs_project_id:
                errors.append("STORAGE_GCS_PROJECT_ID required for GCS storage")

    def _validate_production_config(self, warnings: list[str]) -> None:
        """Validate production environment configuration."""
        if self.environment != "production":
            return

        cors_str = str(self.cors_allowed_origins)
        if "*" in self.cors_allowed_origins or "http://localhost" in cors_str:
            warnings.append("CORS_ALLOWED_ORIGINS contains localhost or wildcard in production")
        if self.sqlalchemy_echo:
            warnings.append("SQLALCHEMY_ECHO=true in production (verbose SQL logging)")

    def validate_config(self) -> list[str]:
        """Validate configuration for production readiness.

        Checks all required settings are configured correctly based on
        the current deployment configuration. Returns a list of warnings
        or raises ValueError for critical misconfigurations.

        This should be called during application startup to fail fast
        on misconfiguration.

        Returns:
            List of warning messages for non-critical issues

        Raises:
            ConfigurationError: If critical configuration is missing or invalid

        Example:
            # In main.py lifespan
            warnings = settings.validate_config()
            for warning in warnings:
                logger.warning("config_warning", extra={"detail": warning})
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Database URL is always required
        if not self.database_url:
            errors.append("DATABASE_URL is required")

        self._validate_auth_config(errors, warnings)
        self._validate_storage_config(errors)
        self._validate_production_config(warnings)

        if errors:
            error_summary = "; ".join(errors)
            error_msg = f"Configuration errors: {error_summary}"
            raise ConfigurationError(error_msg)

        return warnings


settings = Settings()
