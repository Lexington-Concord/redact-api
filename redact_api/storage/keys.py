"""Centralized MinIO object key construction for ingest artifacts.

All ingest artifact paths are defined here to ensure consistent naming
conventions and make it easy to add tenant prefixes, versioning, or other
path changes in one place (mirrors services/minutes-shared/minutes_shared/
storage/keys.py's style for this service's own artifacts).
"""

from __future__ import annotations

from uuid import UUID

DOCUMENTS_PREFIX = "documents"


def page_raster_key(document_id: UUID, page_number: int) -> str:
    """Object key for a page's rasterized PNG image."""
    return f"{DOCUMENTS_PREFIX}/{document_id}/pages/{page_number}/raster.png"


def page_text_layer_key(document_id: UUID, page_number: int) -> str:
    """Object key for a page's extracted text layer JSON."""
    return f"{DOCUMENTS_PREFIX}/{document_id}/pages/{page_number}/text_layer.json"
