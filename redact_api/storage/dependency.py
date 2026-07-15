"""FastAPI dependency exposing the request-scoped MinIO ``StorageClient``.

The client is a single long-lived instance built once in the application lifespan
and stored on ``app.state.storage_client`` (mirroring the ``app.state.engine`` /
``app.state.async_session_maker`` pattern for pytest-xdist compatibility). Tests
inject a fake by setting the same attribute before issuing requests.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from redact_api.storage.client import StorageClient


def get_storage_client(request: Request) -> StorageClient:
    """Return the storage client wired onto ``app.state`` during lifespan startup.

    Raises ``RuntimeError`` if the client was never initialized -- a fail-loud signal
    of a misconfigured app rather than a silent ``None`` propagating into a handler.
    """
    client: StorageClient | None = getattr(request.app.state, "storage_client", None)
    if client is None:
        msg = "Storage client is not configured on app.state.storage_client"
        raise RuntimeError(msg)
    return client


StorageClientDep = Annotated[StorageClient, Depends(get_storage_client)]
