"""Post-apply recoverability verify gate.

Deliberately NOT a ``services/``-style async DB-session module: this is a pure,
session-less function library with no dependency on the database, FastAPI, or the rest
of the redaction pipeline, so it can gate any future ``apply`` implementation
(redact-api#6/#7) without coupling to how that implementation is built. See ticket
redact-api#1 resolution R8.

The gate runs three independent recoverability checks over the redacted PDF and fails
if any of them can still recover a redacted string:

1. Text layer  -- exact substring match against the normalized extracted text.
2. OCR         -- fuzzy match against tesseract OCR of each rasterized page.
3. Metadata    -- exact substring match against docinfo + XMP metadata.

OCR execution errors (e.g. ``TesseractNotFoundError``, a corrupt raster) are NOT
caught: a gate that cannot run must fail loud, not pass quiet, so they propagate
uncaught out of ``verify`` (per the redact-api#1 approval addendum).
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata

import fitz
import pytesseract
from PIL import Image
from rapidfuzz import fuzz

from redact_api.redaction.consts import OCR_MATCH_THRESHOLD, OCR_RASTER_DPI
from redact_api.redaction.models import (
    CheckSummary,
    CheckType,
    VerifyFinding,
    VerifyResult,
    VerifyVerdict,
)

# Findings not tied to a specific page (metadata) use this sentinel page number.
_DOCUMENT_LEVEL_PAGE = 0

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalize text for recoverability comparison (R1).

    Applies, in order: NFC unicode normalization, case folding, whitespace-run
    collapsing, and stripping. Both the redacted strings and the text extracted from the
    PDF are run through this so that trivial rendering differences (casing, runs of
    spaces, combining vs. precomposed accents) do not let a leak slip past the gate.
    """
    normalized = unicodedata.normalize("NFC", text)
    normalized = normalized.casefold()
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def _digest(normalized_text: str) -> str:
    """SHA-256 hex digest of already-normalized text (R4: findings carry no raw PII)."""
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def _normalized_targets(redacted_strings: list[str]) -> list[tuple[str, str]]:
    """Return ``(normalized, raw)`` pairs, dropping strings that normalize to empty.

    An empty normalized target would substring-match every page, so such strings (empty
    or whitespace-only) are skipped rather than producing spurious findings.
    """
    targets: list[tuple[str, str]] = []
    for raw in redacted_strings:
        normalized = normalize_text(raw)
        if normalized:
            targets.append((normalized, raw))
    return targets


def _first_bbox(page: fitz.Page, raw: str) -> tuple[float, float, float, float] | None:
    """Best-effort bounding box of ``raw`` on ``page`` via text search, or None."""
    rects = page.search_for(raw)
    if not rects:
        return None
    rect = rects[0]
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def _check_text_layer(doc: fitz.Document, redacted_strings: list[str]) -> tuple[CheckSummary, list[VerifyFinding]]:
    """Check 1: exact substring match against each page's normalized text layer."""
    targets = _normalized_targets(redacted_strings)
    findings: list[VerifyFinding] = []
    pages_checked = 0
    for page in doc:
        pages_checked += 1
        page_text = normalize_text(page.get_text())
        for normalized, raw in targets:
            if normalized in page_text:
                findings.append(
                    VerifyFinding(
                        redacted_string_digest=_digest(normalized),
                        check_type=CheckType.TEXT_LAYER,
                        page_number=page.number + 1,
                        bbox=_first_bbox(page, raw),
                    )
                )
    summary = CheckSummary(check_type=CheckType.TEXT_LAYER, passed=not findings, pages_checked=pages_checked)
    return summary, findings


def _check_ocr(doc: fitz.Document, redacted_strings: list[str]) -> tuple[CheckSummary, list[VerifyFinding]]:
    """Check 2: fuzzy match against tesseract OCR of each rasterized page.

    Runs on every page -- including image-only pages with no extractable text layer
    (R10) -- and never short-circuits on Check 1's result. OCR execution errors are
    intentionally not caught (see module docstring): they propagate so a gate that
    cannot run fails loud.
    """
    targets = _normalized_targets(redacted_strings)
    findings: list[VerifyFinding] = []
    pages_checked = 0
    for page in doc:
        pages_checked += 1
        if not targets:
            # Nothing to look for; the page is still counted so callers can see the
            # check ran, but the expensive rasterize + OCR is skipped.
            continue
        pixmap = page.get_pixmap(dpi=OCR_RASTER_DPI)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        ocr_text = normalize_text(pytesseract.image_to_string(image))
        for normalized, _raw in targets:
            score = float(fuzz.partial_ratio(normalized, ocr_text))
            if score >= OCR_MATCH_THRESHOLD:
                findings.append(
                    VerifyFinding(
                        redacted_string_digest=_digest(normalized),
                        check_type=CheckType.OCR,
                        page_number=page.number + 1,
                        match_score=score,
                    )
                )
    summary = CheckSummary(check_type=CheckType.OCR, passed=not findings, pages_checked=pages_checked)
    return summary, findings


def _check_metadata(doc: fitz.Document, redacted_strings: list[str]) -> tuple[CheckSummary, list[VerifyFinding]]:
    """Check 3: exact substring match against docinfo and XMP metadata."""
    targets = _normalized_targets(redacted_strings)
    findings: list[VerifyFinding] = []
    docinfo = " ".join(value for value in doc.metadata.values() if value)
    xmp = doc.get_xml_metadata() or ""
    haystack = normalize_text(f"{docinfo} {xmp}")
    for normalized, _raw in targets:
        if normalized in haystack:
            findings.append(
                VerifyFinding(
                    redacted_string_digest=_digest(normalized),
                    check_type=CheckType.METADATA,
                    page_number=_DOCUMENT_LEVEL_PAGE,
                )
            )
    summary = CheckSummary(check_type=CheckType.METADATA, passed=not findings, pages_checked=doc.page_count)
    return summary, findings


def verify(pdf_bytes: bytes, redacted_strings: list[str]) -> VerifyResult:
    """Assert that no redacted string is recoverable from ``pdf_bytes``.

    Opens the PDF and runs all three recoverability checks unconditionally -- even for
    an empty ``redacted_strings`` list or a zero-page document (R10) -- then aggregates
    their findings. The verdict is ``FAIL`` if any check produced a finding, else
    ``PASS``.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        text_summary, text_findings = _check_text_layer(doc, redacted_strings)
        ocr_summary, ocr_findings = _check_ocr(doc, redacted_strings)
        metadata_summary, metadata_findings = _check_metadata(doc, redacted_strings)
    finally:
        doc.close()

    checks = [text_summary, ocr_summary, metadata_summary]
    findings = [*text_findings, *ocr_findings, *metadata_findings]
    verdict = VerifyVerdict.FAIL if findings else VerifyVerdict.PASS
    return VerifyResult(verdict=verdict, checks=checks, findings=findings)
