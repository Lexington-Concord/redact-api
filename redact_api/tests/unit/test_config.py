"""Tests for core configuration module.

Tests cover:
- JWT algorithm validation (field_validator)
- CORS allowed origins parsing and caching
- Configuration validation (auth, storage, production)
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from redact_api.core.config import ConfigurationError, Settings
from redact_api.core.storage import StorageProvider


class TestJwtAlgorithmValidator:
    """Tests for JWT algorithm validation."""

    def test_valid_rs256(self, test_settings_factory: Callable[..., Settings]) -> None:
        """RS256 algorithm should be accepted."""
        settings = test_settings_factory(jwt_algorithm="RS256")

        assert settings.jwt_algorithm == "RS256"

    def test_valid_es256(self, test_settings_factory: Callable[..., Settings]) -> None:
        """ES256 (ECDSA) algorithm should be accepted."""
        settings = test_settings_factory(jwt_algorithm="ES256")

        assert settings.jwt_algorithm == "ES256"

    def test_valid_ps256(self, test_settings_factory: Callable[..., Settings]) -> None:
        """PS256 (RSA-PSS) algorithm should be accepted."""
        settings = test_settings_factory(jwt_algorithm="PS256")

        assert settings.jwt_algorithm == "PS256"

    def test_invalid_hs256_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HS256 (symmetric) algorithm should be rejected."""
        monkeypatch.setenv("JWT_ALGORITHM", "HS256")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "JWT algorithm" in str(exc_info.value)

    def test_invalid_algorithm_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Arbitrary invalid algorithm should be rejected."""
        monkeypatch.setenv("JWT_ALGORITHM", "INVALID")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        assert "JWT algorithm" in str(exc_info.value)

    def test_all_valid_rsa_algorithms(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """All RSA algorithm variants should be accepted."""
        rsa_algorithms = ["RS256", "RS384", "RS512"]

        for algo in rsa_algorithms:
            settings = test_settings_factory(jwt_algorithm=algo)
            assert settings.jwt_algorithm == algo

    def test_all_valid_ecdsa_algorithms(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """All ECDSA algorithm variants should be accepted."""
        ecdsa_algorithms = ["ES256", "ES384", "ES512"]

        for algo in ecdsa_algorithms:
            settings = test_settings_factory(jwt_algorithm=algo)
            assert settings.jwt_algorithm == algo

    def test_all_valid_rsapss_algorithms(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """All RSA-PSS algorithm variants should be accepted."""
        rsapss_algorithms = ["PS256", "PS384", "PS512"]

        for algo in rsapss_algorithms:
            settings = test_settings_factory(jwt_algorithm=algo)
            assert settings.jwt_algorithm == algo


class TestCorsAllowedOrigins:
    """Tests for CORS allowed origins property."""

    def test_parses_comma_separated_string(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Comma-separated string should be parsed into list."""
        settings = test_settings_factory(
            cors_allowed_origins_raw="http://a.com,http://b.com,http://c.com",
        )

        result = settings.cors_allowed_origins

        assert result == ["http://a.com", "http://b.com", "http://c.com"]

    def test_handles_list_input(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """List input should be returned as-is."""
        origins = ["http://a.com", "http://b.com"]
        settings = test_settings_factory(cors_allowed_origins_raw=origins)

        result = settings.cors_allowed_origins

        assert result == origins

    def test_strips_whitespace(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Whitespace around origins should be stripped."""
        settings = test_settings_factory(
            cors_allowed_origins_raw="  http://a.com  ,  http://b.com  ",
        )

        result = settings.cors_allowed_origins

        assert result == ["http://a.com", "http://b.com"]

    def test_caches_result(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Parsed result should be cached for performance."""
        settings = test_settings_factory(cors_allowed_origins_raw="http://a.com")

        first = settings.cors_allowed_origins
        second = settings.cors_allowed_origins

        # Same object reference indicates caching
        assert first is second

    def test_empty_entries_filtered(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Empty entries from trailing commas should be filtered."""
        settings = test_settings_factory(
            cors_allowed_origins_raw="http://a.com,,http://b.com,",
        )

        result = settings.cors_allowed_origins

        assert result == ["http://a.com", "http://b.com"]


class TestValidateConfig:
    """Tests for validate_config method."""

    def test_valid_config_returns_empty_warnings(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Valid minimal configuration should return empty warnings list."""
        settings = test_settings_factory(
            database_url="postgresql+asyncpg://app:app@localhost:5432/app",
            auth_provider_type="none",
            storage_provider=StorageProvider.LOCAL,
        )

        warnings = settings.validate_config()

        assert isinstance(warnings, list)
        assert len(warnings) == 0

    def test_missing_database_url_raises(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Empty database URL should raise ConfigurationError."""
        settings = test_settings_factory(database_url="")

        with pytest.raises(ConfigurationError) as exc_info:
            settings.validate_config()

        assert "DATABASE_URL" in str(exc_info.value)

    def test_auth_provider_requires_url(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Auth provider without URL should raise ConfigurationError."""
        settings = test_settings_factory(
            auth_provider_type="ory",
            auth_provider_url=None,
        )

        with pytest.raises(ConfigurationError) as exc_info:
            settings.validate_config()

        assert "AUTH_PROVIDER_URL" in str(exc_info.value)

    def test_auth_provider_requires_issuer(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Auth provider without issuer should raise ConfigurationError."""
        settings = test_settings_factory(
            auth_provider_type="ory",
            auth_provider_url="https://auth.example.com",
            auth_provider_issuer=None,
        )

        with pytest.raises(ConfigurationError) as exc_info:
            settings.validate_config()

        assert "AUTH_PROVIDER_ISSUER" in str(exc_info.value)

    def test_azure_storage_requires_container(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Azure storage without container should raise ConfigurationError."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.AZURE,
            storage_azure_container=None,
            storage_azure_connection_string="connection-string",
        )

        with pytest.raises(ConfigurationError) as exc_info:
            settings.validate_config()

        assert "STORAGE_AZURE_CONTAINER" in str(exc_info.value)

    def test_azure_storage_requires_connection_string(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Azure storage without connection string should raise ConfigurationError."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.AZURE,
            storage_azure_container="container",
            storage_azure_connection_string=None,
        )

        with pytest.raises(ConfigurationError) as exc_info:
            settings.validate_config()

        assert "STORAGE_AZURE_CONNECTION_STRING" in str(exc_info.value)

    def test_aws_storage_requires_bucket(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """AWS S3 storage without bucket should raise ConfigurationError."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.AWS_S3,
            storage_aws_bucket=None,
            storage_aws_region="us-east-1",
        )

        with pytest.raises(ConfigurationError) as exc_info:
            settings.validate_config()

        assert "STORAGE_AWS_BUCKET" in str(exc_info.value)

    def test_aws_storage_requires_region(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """AWS S3 storage without region should raise ConfigurationError."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.AWS_S3,
            storage_aws_bucket="bucket",
            storage_aws_region=None,
        )

        with pytest.raises(ConfigurationError) as exc_info:
            settings.validate_config()

        assert "STORAGE_AWS_REGION" in str(exc_info.value)

    def test_gcs_storage_requires_bucket(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """GCS storage without bucket should raise ConfigurationError."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.GCS,
            storage_gcs_bucket=None,
            storage_gcs_project_id="project-id",
        )

        with pytest.raises(ConfigurationError) as exc_info:
            settings.validate_config()

        assert "STORAGE_GCS_BUCKET" in str(exc_info.value)

    def test_gcs_storage_requires_project_id(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """GCS storage without project ID should raise ConfigurationError."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.GCS,
            storage_gcs_bucket="bucket",
            storage_gcs_project_id=None,
        )

        with pytest.raises(ConfigurationError) as exc_info:
            settings.validate_config()

        assert "STORAGE_GCS_PROJECT_ID" in str(exc_info.value)

    def test_production_localhost_cors_warning(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Production with localhost CORS should return warning."""
        settings = test_settings_factory(
            environment="production",
            cors_allowed_origins_raw="http://localhost:3000",
        )

        warnings = settings.validate_config()

        assert any("localhost" in w for w in warnings)

    def test_production_wildcard_cors_warning(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Production with wildcard CORS should return warning."""
        settings = test_settings_factory(
            environment="production",
            cors_allowed_origins_raw=["*"],
        )

        warnings = settings.validate_config()

        assert any("wildcard" in w.lower() or "localhost" in w.lower() for w in warnings)

    def test_production_sqlalchemy_echo_warning(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Production with SQLAlchemy echo enabled should return warning."""
        settings = test_settings_factory(
            environment="production",
            cors_allowed_origins_raw="https://example.com",
            sqlalchemy_echo=True,
        )

        warnings = settings.validate_config()

        assert any("SQLALCHEMY_ECHO" in w for w in warnings)

    def test_auth_provider_warns_missing_jwt_public_key(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Auth provider without JWT public key should return warning."""
        settings = test_settings_factory(
            auth_provider_type="ory",
            auth_provider_url="https://auth.example.com",
            auth_provider_issuer="https://auth.example.com",
            jwt_public_key=None,
        )

        warnings = settings.validate_config()

        assert any("JWT_PUBLIC_KEY" in w for w in warnings)

    def test_cognito_auth_no_jwt_public_key_warning(
        self,
        test_settings_factory: Callable[..., Settings],
    ) -> None:
        """Cognito auth without JWT public key should not warn (uses JWKS)."""
        settings = test_settings_factory(
            auth_provider_type="cognito",
            auth_provider_url="https://cognito.example.com",
            auth_provider_issuer="https://cognito.example.com",
            jwt_public_key=None,
        )

        warnings = settings.validate_config()

        # Cognito uses JWKS, so no warning about missing JWT_PUBLIC_KEY
        assert not any("JWT_PUBLIC_KEY" in w for w in warnings)
