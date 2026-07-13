"""Conftest for unit tests.

Overrides autouse fixtures from parent conftest to allow running
unit tests without database dependencies.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

# Import the settings fixtures (they don't require database)
from redact_api.tests.fixtures.settings import (  # noqa: F401
    test_settings,
    test_settings_factory,
    test_settings_with_activity_logging_disabled,
    test_settings_with_auth,
    test_settings_with_storage,
)


@pytest.fixture(autouse=True)
async def reset_db() -> None:
    """Override the parent reset_db fixture to be a no-op for unit tests."""


@pytest.fixture(autouse=True)
async def default_auth_user_in_org() -> None:
    """Override the parent default_auth_user_in_org fixture to be a no-op for unit tests."""


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    """Override engine fixture - unit tests should not use this."""
    error_msg = "Unit tests should not require database engine"
    raise NotImplementedError(error_msg)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    """Override session fixture - unit tests should not use this."""
    error_msg = "Unit tests should not require database session"
    raise NotImplementedError(error_msg)
