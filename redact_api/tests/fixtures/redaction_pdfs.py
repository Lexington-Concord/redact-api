"""Programmatic PDF fixture builders for the redaction verify-gate tests.

These builders generate PDF bytes on the fly with PyMuPDF (``fitz``) -- the same
library ``redact_api.redaction.verify_gate`` reads with -- so no binary blobs are
committed to the repo (per redact-api#1 resolution R5). Each ``make_*`` function
encodes exactly one failure mode the verify gate must catch, plus a clean control
that must PASS all three checks.

The failure modes:

* ``make_overlay_only_pdf``   -- live text layer under an opaque box (Check 1 catches).
* ``make_translucent_box_pdf`` -- rasterized text under a *translucent* box, no text
  layer (only the OCR check, Check 2, can catch this one).
* ``make_metadata_leak_pdf``  -- clean body but the redacted string leaks in the PDF
  docinfo dictionary or the XMP packet (Check 3 catches).
* ``make_properly_redacted_pdf`` -- image-only page with a benign label, clean
  metadata: the control, must PASS.

Note on the "empty PDF" edge case: MuPDF refuses to serialize a zero-page document
(``ValueError: cannot save with zero pages``), so a genuinely page-less PDF cannot be
produced as bytes. ``make_blank_pdf`` returns the representable "empty" case -- a
single blank page with no text, no images, and clean metadata.
"""

from __future__ import annotations

import io

import fitz
from PIL import Image, ImageDraw, ImageFont

# Default subject used across fixtures; a two-token name exercises whitespace
# normalization in the text-layer check without being so short that OCR noise
# would spuriously match it.
DEFAULT_REDACTED_STRING = "John Smith"

# Benign label rendered on control / metadata-leak pages so they look like a real
# redacted document body rather than a blank page.
REDACTED_LABEL = "[REDACTED]"

# Source-image geometry for rendered-text pages. Rendered large so that after the
# page is rasterized at OCR_RASTER_DPI the glyphs stay crisp for tesseract.
_IMAGE_WIDTH = 1000
_IMAGE_HEIGHT = 200
_FONT_SIZE = 90
_PAGE_WIDTH = 612.0
_PAGE_HEIGHT = 200.0
# Rect the source image is drawn into on the page (preserves the 1000x200 aspect).
_IMAGE_RECT = fitz.Rect(0, 0, _PAGE_WIDTH, _PAGE_WIDTH * _IMAGE_HEIGHT / _IMAGE_WIDTH)


def _render_text_image(text: str) -> bytes:
    """Render ``text`` as black glyphs on a white PNG and return the bytes.

    Used to place *visible but non-text-layer* content on a page: the resulting
    image carries no extractable text, so ``page.get_text()`` stays empty while the
    rasterized page remains OCR-legible.
    """
    img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=_FONT_SIZE)
    draw.text((30, 40), text, fill="black", font=font)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def make_overlay_only_pdf(redacted_string: str = DEFAULT_REDACTED_STRING) -> bytes:
    """Live text layer with an opaque black box drawn over it.

    The classic "black box over selectable text" failure: the box hides the text
    visually (so OCR sees nothing) but ``page.get_text()`` still returns the string.
    Only the text-layer check (Check 1) can catch this.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), redacted_string, fontsize=14)
    page.draw_rect(fitz.Rect(60, 58, 320, 90), color=(0, 0, 0), fill=(0, 0, 0))
    data: bytes = doc.tobytes()
    doc.close()
    return data


def make_translucent_box_pdf(redacted_string: str = DEFAULT_REDACTED_STRING) -> bytes:
    """Rasterized text under a *translucent* box, with no surviving text layer.

    The string is drawn as an image (no text layer), then a semi-transparent
    rectangle is laid over it. ``page.get_text()`` is empty -- Check 1 cannot see it --
    but the text is still legible once the page is rasterized, so only the OCR check
    (Check 2) can catch this.
    """
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    page.insert_image(_IMAGE_RECT, stream=_render_text_image(redacted_string))
    page.draw_rect(_IMAGE_RECT, color=None, fill=(0.5, 0.5, 0.5), fill_opacity=0.35)
    data: bytes = doc.tobytes()
    doc.close()
    return data


def make_metadata_leak_pdf(
    redacted_string: str = DEFAULT_REDACTED_STRING,
    *,
    location: str = "docinfo",
) -> bytes:
    """Clean visible body, but the redacted string leaks in document metadata.

    ``location="docinfo"`` embeds the string in the classic PDF docinfo dictionary
    (the ``author`` field); ``location="xmp"`` embeds it in the raw XMP packet. Both
    are covered by the metadata check (Check 3).
    """
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), REDACTED_LABEL, fontsize=14)
    if location == "xmp":
        doc.set_metadata({"title": "Quarterly Report"})
        doc.set_xml_metadata(
            f"<x:xmpmeta xmlns:x='adobe:ns:meta/'><dc:creator>{redacted_string}</dc:creator></x:xmpmeta>"
        )
    else:
        doc.set_metadata({"title": "Quarterly Report", "author": redacted_string})
    data: bytes = doc.tobytes()
    doc.close()
    return data


def make_image_only_pdf(text: str = REDACTED_LABEL) -> bytes:
    """Single page whose only content is a rasterized image of ``text`` (no text layer).

    Exercises the R10 image-only-page edge case: there is nothing for the text-layer
    check to extract, so the OCR check must still rasterize and inspect the page.
    """
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    page.insert_image(_IMAGE_RECT, stream=_render_text_image(text))
    data: bytes = doc.tobytes()
    doc.close()
    return data


def make_properly_redacted_pdf(redacted_string: str = DEFAULT_REDACTED_STRING) -> bytes:
    """Control: a genuinely clean, properly redacted document.

    Image-only page showing a benign ``[REDACTED]`` label (no text layer), no trace of
    ``redacted_string`` anywhere, and clean metadata. Must PASS all three checks.

    The ``redacted_string`` parameter is accepted for signature symmetry with the
    failing builders and to make the caller's intent explicit; it is deliberately
    *not* embedded anywhere in the output.
    """
    _ = redacted_string
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    page.insert_image(_IMAGE_RECT, stream=_render_text_image(REDACTED_LABEL))
    doc.set_metadata({"title": "Quarterly Report", "author": "Records Office"})
    data: bytes = doc.tobytes()
    doc.close()
    return data


def make_blank_pdf() -> bytes:
    """Single blank page, no text/images, clean metadata -- the representable "empty" PDF.

    A truly zero-page PDF cannot be serialized (MuPDF raises ``ValueError: cannot save
    with zero pages``), so this single-blank-page document stands in for the empty-document
    edge case: the three checks run over it as no-ops and the verdict is PASS.
    """
    doc = fitz.open()
    doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    data: bytes = doc.tobytes()
    doc.close()
    return data
