"""Irreversible redaction burn-in (``apply``) -- STUB (red phase).

Real implementation lands in Phase 2. This stub exists so the test suite imports the
public surface and fails for the right reason (NotImplementedError), not an ImportError.
"""

from __future__ import annotations

import fitz

from redact_api.redaction.models import ApplyResult, ApprovedSpan


def _strip_document_javascript(doc: fitz.Document) -> None:
    """Remove document-level JavaScript from ``doc`` (stub)."""
    raise NotImplementedError


def apply(pdf_bytes: bytes, spans: list[ApprovedSpan]) -> ApplyResult:
    """Burn approved spans into ``pdf_bytes`` irreversibly and gate the output (stub)."""
    raise NotImplementedError
