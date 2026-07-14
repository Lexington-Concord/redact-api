"""Constants for the redaction verify gate.

Do not change OCR_MATCH_THRESHOLD without re-running the full fixture corpus in
``redact_api/tests/unit/test_verify_gate.py``. RAISING this value weakens the gate
(makes recoverable text harder to catch); LOWERING it risks false positives on
legitimately dissimilar text. This module exists so the threshold is independently
greppable and auditable, separate from the check logic that consumes it.
"""

from __future__ import annotations

# rapidfuzz.fuzz.partial_ratio score (0-100) at or above which OCR-extracted text is
# treated as a recoverable match for a redacted string. RAISING this constant weakens
# the verify gate.
OCR_MATCH_THRESHOLD = 85

# DPI used when rasterizing each page for the OCR check (fitz Page.get_pixmap). Higher
# DPI yields crisper glyphs for tesseract at the cost of more work per page.
OCR_RASTER_DPI = 300
