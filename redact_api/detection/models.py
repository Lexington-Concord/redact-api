"""DB-free candidate-span model emitted by Tier-1 detectors (redact-api#4 R3).

``CandidateSpan`` is a pure Pydantic model with no SQLModel/DB-session
dependency. Its ``text``/``category``/``source_tier``/``confidence`` fields are
deliberately named to align with ``redact_api.models.span.SpanBase`` so a later
persistence step can map one onto the other. Where ``SpanBase`` carries a
``page_id`` foreign key, ``CandidateSpan`` -- which never sees the database --
carries the ingest ``page_number`` instead.
"""

from __future__ import annotations

from pydantic import BaseModel

from redact_api.models.span import SourceTier


class CandidateSpan(BaseModel):
    """A single detected PII candidate, prior to any persistence or review.

    ``start``/``end`` are character offsets into the owning ``PageModel.text``
    (raw text, so ``text == page.text[start:end]``). ``bboxes`` is one
    ``(x0, y0, x1, y1)`` tuple per contributing word, in document order.
    """

    page_number: int
    start: int
    end: int
    bboxes: list[tuple[float, float, float, float]]
    text: str
    category: str
    source_tier: SourceTier
    confidence: float
