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
