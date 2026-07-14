"""Constants for the redaction pipeline (verify gate + apply).

Do not change OCR_MATCH_THRESHOLD without re-running the full fixture corpus in
``redact_api/tests/unit/test_verify_gate.py``. RAISING this value weakens the gate
(makes recoverable text harder to catch); LOWERING it risks false positives on
legitimately dissimilar text. This module exists so the threshold is independently
greppable and auditable, separate from the check logic that consumes it. That warning
is scoped to the verify-gate threshold only; the apply constants below carry their own
rationale inline.
"""

from __future__ import annotations

# rapidfuzz.fuzz.partial_ratio score (0-100) at or above which OCR-extracted text is
# treated as a recoverable match for a redacted string. RAISING this constant weakens
# the verify gate.
OCR_MATCH_THRESHOLD = 85

# DPI used when rasterizing each page for the OCR check (fitz Page.get_pixmap). Higher
# DPI yields crisper glyphs for tesseract at the cost of more work per page.
OCR_RASTER_DPI = 300

# DPI at which ``apply`` rasterizes each source page before burning in redaction boxes
# and rebuilding the output PDF from those images only. A fidelity/size tradeoff: higher
# DPI keeps the rebuilt document legible and print-quality but enlarges the output; 300
# matches the OCR check's raster resolution so what the gate re-reads is exactly what a
# reader sees. This is intentionally NOT ingest's RASTER_DPI (150) -- apply's output is
# the archival redacted artifact, not an ingest preview, so it warrants a higher floor.
APPLY_OUTPUT_DPI = 300

# Points added on every side of an approved span's bbox before the opaque box is drawn.
# Why: bboxes are tight to the glyph ink, and rasterization anti-aliasing bleeds partial
# glyph pixels just outside that tight rect; without a small inflation the box can
# under-cover, leaving a recoverable sliver of the redacted text at the edges.
BOX_PADDING_PTS = 2.0
