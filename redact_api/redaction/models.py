"""Typed public contract for the redaction verify gate (redact-api#1, R3).

The gate returns only these Pydantic/StrEnum types -- never a raw dict -- so callers
(a future apply/export endpoint) get a stable, typed result. Findings deliberately
carry a SHA-256 digest of the recoverable string rather than the string itself, so the
verify result can be logged or persisted without re-leaking what was redacted (R4).
"""

from __future__ import annotations

import enum

from pydantic import BaseModel


class VerifyVerdict(enum.StrEnum):
    """Overall outcome of the verify gate."""

    PASS = "pass"
    FAIL = "fail"


class CheckType(enum.StrEnum):
    """Which recoverability check produced a finding or summary."""

    TEXT_LAYER = "text_layer"
    OCR = "ocr"
    METADATA = "metadata"


class VerifyFinding(BaseModel):
    """A single recoverable-string hit found by one of the checks.

    MUST NOT contain the recoverable string or any substring of it -- only a digest
    (see R4). ``page_number`` is 1-based for page-level checks (text layer, OCR); it is
    ``0`` for document-level findings that are not tied to a page (metadata).
    """

    redacted_string_digest: str
    check_type: CheckType
    page_number: int
    match_score: float | None = None
    bbox: tuple[float, float, float, float] | None = None


class CheckSummary(BaseModel):
    """Per-check outcome, recorded even when the check produced no findings.

    ``pages_checked`` is the number of pages the check ranged over (the document page
    count for the metadata check, which is document-level). It stays populated even for
    a trivial input so callers can tell a check ran as a no-op from one that was skipped.
    """

    check_type: CheckType
    passed: bool
    pages_checked: int


class VerifyResult(BaseModel):
    """Aggregate result returned by ``verify``."""

    verdict: VerifyVerdict
    checks: list[CheckSummary]
    findings: list[VerifyFinding]


class ApprovedSpan(BaseModel):
    """A single already-approved, already-projected redaction span for ``apply`` (R1).

    Supplied by the caller -- ``apply`` is a pure, DB-free function that never derives
    spans from persistence itself (that projection is redact-api#7's job). ``page_number``
    is 1-based, matching the page numbering used throughout the redaction pipeline
    (e.g. ``VerifyFinding.page_number``). ``bbox`` is ``(x0, y0, x1, y1)`` in PDF-point
    units with a top-left origin, the same shape as ``ingest.models.WordBBox.bbox``.
    ``text`` is the recoverable string being burned in; ``apply`` forwards it to the
    verify gate so the gate can confirm the string is no longer recoverable from its own
    output.
    """

    page_number: int
    bbox: tuple[float, float, float, float]
    text: str


class ApplyResult(BaseModel):
    """Result of ``apply``: the redacted PDF plus the verify gate's verdict on it (R2).

    ``apply`` runs the verify gate on its *own* output before returning, so a caller
    can never obtain redacted bytes that were not gated. A ``FAIL`` verdict is a normal
    return value (surfaced via ``verify_result``), not a raised exception -- the caller
    decides how to react. ``passed`` is a convenience mirror of the gate verdict.
    """

    pdf_bytes: bytes
    verify_result: VerifyResult

    @property
    def passed(self) -> bool:
        """True when the verify gate passed on the redacted output (R2)."""
        return self.verify_result.verdict == VerifyVerdict.PASS
