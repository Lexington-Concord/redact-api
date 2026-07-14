"""Irreversible redaction burn-in (``apply``).

``apply`` is a pure, DB-free function -- it takes raw PDF bytes plus already-approved,
already-projected spans and returns redacted bytes with the verify gate's verdict on
them (redact-api#6). It never touches persistence, FastAPI, or the database; the
persistence -> ``ApprovedSpan`` projection is a separate concern (redact-api#7).

The burn-in is irreversible by construction: each source page is rasterized to an image,
opaque black boxes are painted over every approved span's (padded) bbox, and the output
PDF is rebuilt from those redacted images *only*. No original text layer, vector content,
annotation, or embedded object survives into the output, so there is nothing left to
"un-redact". On top of that structural guarantee, ``apply`` still runs the explicit R5
metadata/JS/embedded-file strip checklist (belt and suspenders against any convenience
copy MuPDF might carry forward), then gates its own output through ``verify`` before
returning -- a caller can never obtain redacted bytes that were not verified.
"""

from __future__ import annotations

import io

import fitz
from PIL import Image, ImageDraw

from redact_api.redaction.consts import APPLY_OUTPUT_DPI, BOX_PADDING_PTS
from redact_api.redaction.models import ApplyResult, ApprovedSpan
from redact_api.redaction.verify_gate import verify

# Opaque redaction fill and the PDF point-per-inch constant used for point<->pixel scaling.
_BLACK = (0, 0, 0)
_POINTS_PER_INCH = 72.0

# Catalog keys that can carry document-level JavaScript (a name tree, the open action, or
# an additional-actions dictionary); each is cleared during the strip.
_JAVASCRIPT_CATALOG_KEYS = ("Names/JavaScript", "OpenAction", "AA")


def _validate_page_numbers(spans: list[ApprovedSpan], page_count: int) -> None:
    """Raise ``ValueError`` if any span's 1-based page number is out of range."""
    for span in spans:
        if not 1 <= span.page_number <= page_count:
            message = f"span page number {span.page_number} is out of range for a {page_count}-page document"
            raise ValueError(message)


def _spans_by_page(spans: list[ApprovedSpan]) -> dict[int, list[ApprovedSpan]]:
    """Group spans by 0-based page index (matching ``fitz.Page.number``)."""
    grouped: dict[int, list[ApprovedSpan]] = {}
    for span in spans:
        grouped.setdefault(span.page_number - 1, []).append(span)
    return grouped


def _draw_boxes(image: Image.Image, spans: list[ApprovedSpan], scale: float) -> None:
    """Paint an opaque black box over each span's padded bbox, clamped to the image."""
    draw = ImageDraw.Draw(image)
    for span in spans:
        x0, y0, x1, y1 = span.bbox
        left = max(0, round((x0 - BOX_PADDING_PTS) * scale))
        top = max(0, round((y0 - BOX_PADDING_PTS) * scale))
        right = min(image.width, round((x1 + BOX_PADDING_PTS) * scale))
        bottom = min(image.height, round((y1 + BOX_PADDING_PTS) * scale))
        draw.rectangle((left, top, right, bottom), fill=_BLACK)


def _redact_page_image(page: fitz.Page, spans: list[ApprovedSpan]) -> Image.Image:
    """Rasterize ``page`` at APPLY_OUTPUT_DPI and burn its spans' boxes into the image."""
    scale = APPLY_OUTPUT_DPI / _POINTS_PER_INCH
    pixmap = page.get_pixmap(dpi=APPLY_OUTPUT_DPI)
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
    _draw_boxes(image, spans, scale)
    return image


def _append_image_page(out: fitz.Document, image: Image.Image) -> None:
    """Append a page sized from the image's pixel dimensions and insert the image.

    Sizing the page from the pixmap's actual pixel size (not ``page.rect``) keeps output
    dimensions correct even when the source page carried a rotation.
    """
    scale = APPLY_OUTPUT_DPI / _POINTS_PER_INCH
    page = out.new_page(width=image.width / scale, height=image.height / scale)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())


def _strip_document_javascript(doc: fitz.Document) -> None:
    """Remove document-level JavaScript (name tree, open action, additional actions)."""
    catalog = doc.pdf_catalog()
    for key in _JAVASCRIPT_CATALOG_KEYS:
        type_name, _value = doc.xref_get_key(catalog, key)
        if type_name != "null":
            doc.xref_set_key(catalog, key, "null")


def _strip_metadata(doc: fitz.Document) -> None:
    """Run the explicit R5 strip checklist: docinfo, XMP, embedded files, JavaScript.

    These calls are mandatory regardless of the image-only rebuild already dropping this
    content, guarding against any convenience copy MuPDF might carry into the output.
    """
    doc.set_metadata({})
    doc.del_xml_metadata()
    for name in list(doc.embfile_names()):
        doc.embfile_del(name)
    _strip_document_javascript(doc)


def _rebuild_redacted_pdf(source: fitz.Document, grouped: dict[int, list[ApprovedSpan]]) -> bytes:
    """Rebuild an image-only PDF from redacted rasters of every source page, then strip."""
    out = fitz.open()
    try:
        for page in source:
            image = _redact_page_image(page, grouped.get(page.number, []))
            _append_image_page(out, image)
        _strip_metadata(out)
        redacted_pdf: bytes = out.tobytes()
        return redacted_pdf
    finally:
        out.close()


def apply(pdf_bytes: bytes, spans: list[ApprovedSpan]) -> ApplyResult:
    """Burn approved spans into ``pdf_bytes`` irreversibly and gate the output.

    Rasterizes each page, paints opaque boxes over approved spans, rebuilds an image-only
    PDF, strips residual metadata/JavaScript/embedded files, then runs ``verify`` on the
    resulting bytes. Returns the redacted bytes bundled with the verify verdict; a FAIL
    verdict is a normal return (see ``ApplyResult``), not a raised exception.
    """
    source = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        _validate_page_numbers(spans, source.page_count)
        grouped = _spans_by_page(spans)
        redacted_pdf = _rebuild_redacted_pdf(source, grouped)
    finally:
        source.close()

    redacted_strings = sorted({span.text for span in spans})
    verify_result = verify(redacted_pdf, redacted_strings)
    return ApplyResult(pdf_bytes=redacted_pdf, verify_result=verify_result)
