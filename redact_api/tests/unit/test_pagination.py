"""Tests for pagination module.

Tests cover:
- DefaultParams class (page/size defaults and validation)
- configure_pagination function (custom page class loading)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi_pagination import Page

from redact_api.core.pagination import DefaultParams, configure_pagination


class TestDefaultParams:
    """Tests for DefaultParams class."""

    def test_default_page_is_one(self) -> None:
        """Default page should be 1."""
        params = DefaultParams()

        assert params.page == 1

    def test_default_size_from_settings(self) -> None:
        """Default size should come from settings."""
        params = DefaultParams()

        # Size comes from settings.pagination_page_size (default 50)
        assert params.size >= 1

    def test_custom_page_value(self) -> None:
        """Custom page value should be accepted."""
        params = DefaultParams(page=5)

        assert params.page == 5

    def test_custom_size_value(self) -> None:
        """Custom size value should be accepted."""
        params = DefaultParams(size=25)

        assert params.size == 25

    def test_page_must_be_at_least_one(self) -> None:
        """Page must be >= 1."""
        with pytest.raises(ValueError, match="greater than or equal to 1"):
            DefaultParams(page=0)

    def test_size_must_be_positive(self) -> None:
        """Size must be >= 1."""
        with pytest.raises(ValueError, match="greater than or equal to 1"):
            DefaultParams(size=0)

    def test_size_must_not_exceed_max(self) -> None:
        """Size must not exceed pagination_page_size_max."""
        # Default max is 200
        with pytest.raises(ValueError, match="less than or equal to"):
            DefaultParams(size=500)


class TestConfigurePagination:
    """Tests for configure_pagination function."""

    def test_no_op_when_no_custom_class(self) -> None:
        """Should do nothing when pagination_page_class is not set."""
        with patch("redact_api.core.pagination.settings") as mock_settings:
            mock_settings.pagination_page_class = None

            # Should not raise
            configure_pagination()

    def test_raises_on_invalid_module_path(self) -> None:
        """Should raise ValueError when path has no module separator."""
        with patch("redact_api.core.pagination.settings") as mock_settings:
            mock_settings.pagination_page_class = "invalid"  # No dot separator

            with pytest.raises(ValueError, match="importable path"):
                configure_pagination()

    def test_raises_on_non_page_class(self) -> None:
        """Should raise TypeError when class is not a Page subclass."""
        with patch("redact_api.core.pagination.settings") as mock_settings:
            mock_settings.pagination_page_class = "builtins.str"  # Not a Page

            with pytest.raises(TypeError) as exc_info:
                configure_pagination()

            assert "Page" in str(exc_info.value)

    def test_raises_on_module_not_found(self) -> None:
        """Should raise ModuleNotFoundError when module doesn't exist."""
        with patch("redact_api.core.pagination.settings") as mock_settings:
            mock_settings.pagination_page_class = "nonexistent.module.PageClass"

            with pytest.raises(ModuleNotFoundError):
                configure_pagination()

    def test_raises_on_attribute_not_found(self) -> None:
        """Should raise AttributeError when class doesn't exist in module."""
        with patch("redact_api.core.pagination.settings") as mock_settings:
            mock_settings.pagination_page_class = "builtins.NonexistentClass"

            with pytest.raises(AttributeError):
                configure_pagination()

    def test_sets_valid_page_class(self) -> None:
        """Should call set_page with valid Page subclass."""
        with (
            patch("redact_api.core.pagination.settings") as mock_settings,
            patch("redact_api.core.pagination.importlib") as mock_importlib,
            patch("redact_api.core.pagination.set_page") as mock_set_page,
        ):
            mock_settings.pagination_page_class = "myapp.pagination.CustomPage"

            mock_module = MagicMock()

            # Create a proper class that is a subclass of Page
            class CustomPage(Page):
                pass

            mock_module.CustomPage = CustomPage
            mock_importlib.import_module.return_value = mock_module

            configure_pagination()

            mock_set_page.assert_called_once_with(CustomPage)

    def test_parses_nested_module_path(self) -> None:
        """Should correctly parse nested module paths."""
        with (
            patch("redact_api.core.pagination.settings") as mock_settings,
            patch("redact_api.core.pagination.importlib") as mock_importlib,
            patch("redact_api.core.pagination.set_page"),
        ):
            mock_settings.pagination_page_class = "myapp.pagination.nested.module.CustomPage"

            mock_module = MagicMock()

            class CustomPage(Page):
                pass

            mock_module.CustomPage = CustomPage
            mock_importlib.import_module.return_value = mock_module

            configure_pagination()

            # Should import the full module path
            mock_importlib.import_module.assert_called_once_with(
                "myapp.pagination.nested.module",
            )
