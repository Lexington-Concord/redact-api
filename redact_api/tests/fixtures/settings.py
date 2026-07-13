"""Settings fixtures for testing with isolated configuration.

This module provides factory fixtures that create fresh Settings instances
for each test, ensuring pytest-xdist compatibility by avoiding global state
mutation.

Pattern:
    - test_settings_factory: Creates Settings with custom overrides
    - test_settings: Default factory with standard test database URL
    - test_settings_with_auth: Factory pre-configured for auth testing

Each fixture returns a fresh Settings instance (not the global singleton),
allowing tests to run in parallel without interference.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError
from redact_api.core.config import Settings
from redact_api.core.storage import StorageProvider


@pytest.fixture
def test_settings_factory() -> Callable[..., Settings]:
    """Factory for creating isolated Settings instances.

    Returns a callable that creates fresh Settings with custom overrides.
    Use this to create multiple Settings instances in a single test.

    Usage:
        def test_multiple_configs(test_settings_factory):
            settings_1 = test_settings_factory(environment="staging")
            settings_2 = test_settings_factory(environment="production")
            assert settings_1.environment != settings_2.environment

    Returns:
        Callable that accepts keyword arguments for Settings fields
    """

    def _factory(**overrides: dict) -> Settings:
        # Build field dictionary with test defaults
        fields = {
            "database_url": "postgresql+asyncpg://app:app@localhost:5432/app_test",
            "environment": "test",
            "log_level": "debug",
            "activity_logging_enabled": True,
            "auth_provider_type": "none",
            "app_name": "redact_api",
            "sqlalchemy_echo": False,
            "enable_metrics": True,
            "pagination_page_size": 50,
            "pagination_page_size_max": 200,
            "pagination_page_class": None,
            "activity_log_retention_days": 90,
            "max_file_size_bytes": 50 * 1024 * 1024,
            "auth_provider_url": None,
            "auth_provider_issuer": None,
            "jwt_algorithm": "RS256",
            "jwt_public_key": None,
            "cors_allowed_origins_raw": "http://localhost:3000",
            "enforce_tenant_isolation": True,
            "request_id_header": "X-Request-ID",
            "include_request_context_in_logs": False,
            "storage_provider": "local",
            "storage_local_path": "./uploads",
            "storage_azure_container": None,
            "storage_azure_connection_string": None,
            "storage_aws_bucket": None,
            "storage_aws_region": None,
            "storage_gcs_bucket": None,
            "storage_gcs_project_id": None,
        }

        # Apply overrides
        fields.update(overrides)

        # Validate enum fields before construction
        # storage_provider must be a valid StorageProvider enum
        if "storage_provider" in overrides:
            provider = overrides["storage_provider"]
            if isinstance(provider, str):
                # Validate enum value and raise ValidationError if invalid
                try:
                    fields["storage_provider"] = StorageProvider(provider)
                except ValueError as err:
                    error_msg = str(err)
                    # Raise ValidationError matching Pydantic's format
                    error_title = "Settings"
                    raise ValidationError.from_exception_data(
                        error_title,
                        [
                            {
                                "type": "enum",
                                "loc": ("storage_provider",),
                                "msg": error_msg,
                                "input": provider,
                                "ctx": {"expected": "a valid StorageProvider"},
                            }
                        ],
                    ) from err

        # NOTE: BaseSettings has extra='forbid' which prevents normal instantiation with kwargs.
        # In tests, we must use model_construct with validated field data.
        # This is acceptable in test context where we control all inputs.
        return Settings.model_construct(**fields)  # type: ignore[arg-type]

    return _factory


@pytest.fixture
def test_settings(test_settings_factory: Callable[..., Settings]) -> Settings:
    """Fresh Settings instance for testing.

    Creates an isolated Settings instance using default test configuration.
    Each test gets a fresh instance, supporting pytest-xdist parallel execution.

    Usage:
        def test_pagination(test_settings):
            assert test_settings.pagination_page_size == 50
            assert test_settings.pagination_page_size_max == 200

    Returns:
        Fresh Settings instance with test database URL
    """
    return test_settings_factory()


@pytest.fixture
def test_settings_with_auth(test_settings_factory: Callable[..., Settings]) -> Settings:
    """Settings configured for authentication testing.

    Pre-configures settings with a test auth provider setup.

    Usage:
        def test_auth_enabled(test_settings_with_auth):
            assert test_settings_with_auth.auth_provider_type == "ory"
            assert test_settings_with_auth.auth_provider_url is not None

    Returns:
        Fresh Settings instance with auth provider configured
    """
    return test_settings_factory(
        auth_provider_type="ory",
        auth_provider_url="https://test-ory.example.com",
        auth_provider_issuer="https://test-ory.example.com",
    )


@pytest.fixture
def test_settings_with_storage(test_settings_factory: Callable[..., Settings]) -> Settings:
    """Settings configured for cloud storage testing.

    Pre-configures settings with Azure Blob Storage for testing.

    Returns:
        Fresh Settings instance with Azure storage configured
    """
    return test_settings_factory(
        storage_provider=StorageProvider.AZURE,
        storage_azure_container="test-container",
        storage_azure_connection_string="DefaultEndpointsProtocol=https;AccountName=testaccount;AccountKey=testkey;EndpointSuffix=core.windows.net",
    )


@pytest.fixture
def test_settings_with_activity_logging_disabled(
    test_settings_factory: Callable[..., Settings],
) -> Settings:
    """Settings with activity logging disabled.

    Useful for testing that activity logging integration doesn't interfere
    with core functionality when disabled.

    Returns:
        Fresh Settings instance with activity logging disabled
    """
    return test_settings_factory(activity_logging_enabled=False)
