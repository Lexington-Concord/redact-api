"""Shared constants for the PDF ingest pipeline."""

from __future__ import annotations

RASTER_DPI = 150
"""DPI used when rasterizing PDF pages to PNG for redaction review."""

MAX_PAGE_COUNT = 500
"""Maximum number of pages a single document may contain for ingest."""
