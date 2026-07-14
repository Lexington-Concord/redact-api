"""Conftest for unit tests.

Overrides autouse fixtures from parent conftest to allow running
unit tests without database dependencies.
"""

import shutil
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


def _empty_ocr(*_args: object, **_kwargs: object) -> str:
    """Stand-in for ``pytesseract.image_to_string`` that recognizes nothing."""
    return ""


@pytest.fixture(autouse=True)
def _ocr_stub(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default-stub tesseract OCR to empty output for unit tests.

    The verify gate (``redact_api.redaction.verify_gate``) rasterizes and OCRs every
    page, which requires the ``tesseract`` binary. To keep the non-OCR unit suite
    runnable without that binary, this autouse fixture replaces
    ``pytesseract.image_to_string`` with a no-op by default.

    Tests exercising OCR *detection* override this by monkeypatching the function to a
    specific return value (or one that raises). Tests marked ``real_ocr`` opt out
    entirely and use the real tesseract engine -- they are skipped when the binary is
    unavailable (as in local dev) and run for real in CI, where ``tesseract-ocr`` is
    installed. This keeps the OCR recognition path fully exercised in CI while the rest
    of the suite stays portable.
    """
    if "real_ocr" in request.keywords:
        if shutil.which("tesseract") is None:
            pytest.skip("tesseract binary unavailable; real-OCR test runs in CI")
        return
    monkeypatch.setattr("pytesseract.image_to_string", _empty_ocr)


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
