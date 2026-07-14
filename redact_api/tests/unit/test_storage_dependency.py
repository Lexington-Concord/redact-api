"""Unit tests for the storage-client FastAPI dependency wiring.

Pure -- no database, no network. Exercises ``get_storage_client`` against a
duck-typed request whose ``app.state`` carries (or omits) a storage client.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from redact_api.storage.client import StorageClient
from redact_api.storage.dependency import get_storage_client

if TYPE_CHECKING:
    from fastapi import Request


def _request_with_state(**state: object) -> Request:
    """Build a duck-typed Request exposing ``request.app.state`` attributes."""
    app = SimpleNamespace(state=SimpleNamespace(**state))
    return cast("Request", SimpleNamespace(app=app))


class TestGetStorageClient:
    def test_returns_client_from_app_state(self) -> None:
        client = StorageClient(access_key="k", secret_key="s")
        request = _request_with_state(storage_client=client)

        assert get_storage_client(request) is client

    def test_raises_when_client_absent(self) -> None:
        request = _request_with_state()

        with pytest.raises(RuntimeError):
            get_storage_client(request)

    def test_raises_when_client_is_none(self) -> None:
        request = _request_with_state(storage_client=None)

        with pytest.raises(RuntimeError):
            get_storage_client(request)
