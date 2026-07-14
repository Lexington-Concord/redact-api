"""Pydantic models for the canonical ingest page-model contract.

These are the pinned, DB-free output shapes of the ingest pipeline: a
document's pages, each with a word-level text layer (character offsets +
bounding boxes) and a reference to its rasterized PNG in object storage.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class WordBBox(BaseModel):
    """A single word's character offsets into `PageModel.text` and its bounding box.

    `start`/`end` are Python `str` character indices (not byte indices) into
    the owning `PageModel.text`, so `text[start:end]` reconstructs the word.
    `bbox` is `(x0, y0, x1, y1)` in PDF-point units.
    """

    start: int
    end: int
    bbox: tuple[float, float, float, float]


class PageModel(BaseModel):
    """Canonical per-page extraction result: raster reference + word-level text layer."""

    page_number: int
    text: str
    words: list[WordBBox]
    rotation: int
    raster_key: str


class IngestResult(BaseModel):
    """Aggregate result of ingesting a single PDF document."""

    document_id: UUID
    page_count: int
    pages: list[PageModel]
