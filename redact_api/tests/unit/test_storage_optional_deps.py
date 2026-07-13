"""Tests for optional storage provider dependencies.

This module verifies that:
1. Local storage works without additional dependencies
2. Cloud storage providers (Azure, AWS, GCS) provide helpful error messages
   when required packages are missing
3. Configuration validation prevents misconfiguration
4. Factory function instantiates correct provider based on settings

Cloud provider tests use mocking to avoid requiring actual packages.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
from pydantic_core import ValidationError

from redact_api.core.config import Settings
from redact_api.core.storage import (
    StorageProvider,
    get_storage_service,
)


class TestLocalStorageProvider:
    """Test local filesystem storage provider (always available)."""

    def test_local_storage_instantiation(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Local storage should instantiate without additional dependencies."""
        settings = test_settings_factory(storage_provider=StorageProvider.LOCAL)
        with patch("redact_api.core.storage.settings", settings):
            storage = get_storage_service()
            assert storage is not None
            # Verify it's actually a local storage service
            assert hasattr(storage, "upload")
            assert hasattr(storage, "download")
            assert hasattr(storage, "delete")

    def test_local_storage_with_custom_path(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Local storage should accept custom path configuration."""
        custom_path = "/custom/storage/path"
        settings = test_settings_factory(
            storage_provider=StorageProvider.LOCAL,
            storage_local_path=custom_path,
        )
        with patch("redact_api.core.storage.settings", settings):
            storage = get_storage_service()
            assert storage is not None
            # Verify base_path is set correctly (convert Path to string for comparison)
            assert str(storage.base_path) == custom_path  # type: ignore[attr-defined]


class TestAzureStorageProvider:
    """Test Azure Blob Storage provider with optional dependency handling."""

    def test_azure_storage_missing_dependency(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Should raise helpful error when azure-storage-blob is not installed."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.AZURE,
            storage_azure_container="test-container",
            storage_azure_connection_string="test-connection",
        )

        # Mock ImportError to simulate missing azure-storage-blob
        def mock_import(
            name: str,
            *args: Any,  # noqa: ANN401
            **kwargs: Any,  # noqa: ANN401
        ) -> Any:  # noqa: ANN401
            if "AzureBlobStorageService" in str(name):
                msg = "No module named 'azure.storage.blob'"
                raise ImportError(msg)
            return __import__(name, *args, **kwargs)

        with (
            patch("redact_api.core.storage.settings", settings),
            patch("builtins.__import__", side_effect=mock_import),
            pytest.raises(ValueError, match="azure-storage-blob"),
        ):
            get_storage_service()

    def test_azure_storage_missing_configuration(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Should raise error when Azure configuration is incomplete."""
        # Missing connection string
        settings = test_settings_factory(
            storage_provider=StorageProvider.AZURE,
            storage_azure_container="test-container",
            storage_azure_connection_string=None,
        )

        with (
            patch("redact_api.core.storage.settings", settings),
            pytest.raises(ValueError, match="STORAGE_AZURE_CONTAINER"),
        ):
            get_storage_service()

    def test_azure_storage_missing_container(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Should raise error when container name is missing."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.AZURE,
            storage_azure_container=None,
            storage_azure_connection_string="test-connection",
        )

        with (
            patch("redact_api.core.storage.settings", settings),
            pytest.raises(ValueError, match="STORAGE_AZURE"),
        ):
            get_storage_service()


class TestAWSS3StorageProvider:
    """Test AWS S3 provider with optional dependency handling."""

    def test_s3_storage_missing_dependency(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Should raise helpful error when aioboto3 is not installed."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.AWS_S3,
            storage_aws_bucket="test-bucket",
            storage_aws_region="us-east-1",
        )

        def mock_import(
            name: str,
            *args: Any,  # noqa: ANN401
            **kwargs: Any,  # noqa: ANN401
        ) -> Any:  # noqa: ANN401
            if "S3StorageService" in str(name):
                msg = "No module named 'aioboto3'"
                raise ImportError(msg)
            return __import__(name, *args, **kwargs)

        with (
            patch("redact_api.core.storage.settings", settings),
            patch("builtins.__import__", side_effect=mock_import),
            pytest.raises(ValueError, match="aioboto3"),
        ):
            get_storage_service()

    def test_s3_storage_missing_bucket(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Should raise error when S3 bucket name is missing."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.AWS_S3,
            storage_aws_bucket=None,
            storage_aws_region="us-east-1",
        )

        with (
            patch("redact_api.core.storage.settings", settings),
            pytest.raises(ValueError, match="STORAGE_AWS"),
        ):
            get_storage_service()

    def test_s3_storage_missing_region(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Should raise error when AWS region is missing."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.AWS_S3,
            storage_aws_bucket="test-bucket",
            storage_aws_region=None,
        )

        with (
            patch("redact_api.core.storage.settings", settings),
            pytest.raises(ValueError, match="STORAGE_AWS"),
        ):
            get_storage_service()


class TestGCSStorageProvider:
    """Test Google Cloud Storage provider with optional dependency handling."""

    def test_gcs_storage_missing_dependency(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Should raise helpful error when google-cloud-storage is not installed."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.GCS,
            storage_gcs_bucket="test-bucket",
            storage_gcs_project_id="test-project",
        )

        def mock_import(
            name: str,
            *args: Any,  # noqa: ANN401
            **kwargs: Any,  # noqa: ANN401
        ) -> Any:  # noqa: ANN401
            if "GCSStorageService" in str(name):
                msg = "No module named 'google.cloud.storage'"
                raise ImportError(msg)
            return __import__(name, *args, **kwargs)

        with (
            patch("redact_api.core.storage.settings", settings),
            patch("builtins.__import__", side_effect=mock_import),
            pytest.raises(ValueError, match="google-cloud-storage"),
        ):
            get_storage_service()

    def test_gcs_storage_missing_bucket(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Should raise error when GCS bucket name is missing."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.GCS,
            storage_gcs_bucket=None,
            storage_gcs_project_id="test-project",
        )

        with (
            patch("redact_api.core.storage.settings", settings),
            pytest.raises(ValueError, match="STORAGE_GCS"),
        ):
            get_storage_service()

    def test_gcs_storage_missing_project_id(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Should raise error when GCS project ID is missing."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.GCS,
            storage_gcs_bucket="test-bucket",
            storage_gcs_project_id=None,
        )

        with (
            patch("redact_api.core.storage.settings", settings),
            pytest.raises(ValueError, match="STORAGE_GCS"),
        ):
            get_storage_service()


class TestStorageProviderFactory:
    """Test factory function behavior with different configurations."""

    def test_factory_invalid_provider(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Should raise ValidationError for invalid provider in Settings.

        Invalid storage providers are caught by Pydantic enum validation
        at the Settings level, not in the factory function. This is correct
        behavior - configuration errors should be caught during initialization.
        """
        with pytest.raises(ValidationError, match="storage_provider"):
            test_settings_factory(storage_provider="invalid_provider")

    def test_factory_returns_correct_provider_local(self, test_settings_factory: Callable[..., Settings]) -> None:
        """Factory should return local storage service for LOCAL provider."""
        settings = test_settings_factory(storage_provider=StorageProvider.LOCAL)

        with patch("redact_api.core.storage.settings", settings):
            storage = get_storage_service()
            assert storage is not None
            # Verify it's the local storage service by checking base_path
            assert hasattr(storage, "base_path")

    def test_error_messages_include_installation_instructions(
        self, test_settings_factory: Callable[..., Settings]
    ) -> None:
        """Error messages should include pip install instructions."""
        settings = test_settings_factory(
            storage_provider=StorageProvider.AZURE,
            storage_azure_container="container",
            storage_azure_connection_string="string",
        )

        def mock_import(
            name: str,
            *args: Any,  # noqa: ANN401
            **kwargs: Any,  # noqa: ANN401
        ) -> Any:  # noqa: ANN401
            if "AzureBlobStorageService" in str(name):
                msg = "No module named 'azure'"
                raise ImportError(msg)
            return __import__(name, *args, **kwargs)

        with (
            patch("redact_api.core.storage.settings", settings),
            patch("builtins.__import__", side_effect=mock_import),
            pytest.raises(ValueError, match="pip install") as exc_info,
        ):
            get_storage_service()
        # Verify error message includes installation instruction
        assert "[azure]" in str(exc_info.value)


class TestStorageProviderEnum:
    """Test StorageProvider enum values and behavior."""

    def test_provider_enum_values(self) -> None:
        """Verify all expected provider types are available."""
        expected_providers = {"local", "azure", "aws_s3", "gcs"}
        actual_providers = {p.value for p in StorageProvider}
        assert actual_providers == expected_providers

    def test_provider_string_representation(self) -> None:
        """Verify provider values match configuration strings."""
        assert StorageProvider.LOCAL.value == "local"
        assert StorageProvider.AZURE.value == "azure"
        assert StorageProvider.AWS_S3.value == "aws_s3"
        assert StorageProvider.GCS.value == "gcs"
