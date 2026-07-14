"""Programmatic PDF fixture builders for the redaction ``apply`` tests.

Like ``redaction_pdfs.py`` (the sibling verify-gate fixtures), these builders generate
PDF bytes on the fly with PyMuPDF (``fitz``) so no binary blobs are committed to the
repo (per redact-api#1 resolution R5). Each builder encodes exactly one input shape the
irreversible-burn-in ``apply`` implementation must handle.

The builders:

* ``make_pii_source_pdf``          -- one page with a *live text layer* PII string at a
  known bbox; the source ``apply`` must rasterize, box over, and rebuild image-only.
  Returns the bytes plus a ``PiiSpanRef`` giving the span's page/bbox/text so a test can
  construct the matching ``ApprovedSpan``.
* ``make_multi_page_pii_pdf``      -- several pages, each with its own PII string, for the
  multi-page redaction path.
* ``make_js_and_embedded_file_pdf`` -- clean-looking body but document-level JavaScript
  (Names tree + OpenAction), an embedded file, and metadata (docinfo + XMP) all carrying
  the redacted string: exercises the R5 metadata/JS/embedded-file strip checklist.
* ``make_annotated_exif_pdf``      -- a page carrying annotations and an image with EXIF
  metadata: the Amendment B structural regression fixture, pinning that rebuild-from-
  rasterized-images strips annotations and EXIF *for free*, distinct from and additional
  to the explicit R5 strip calls.
"""

from __future__ import annotations

import io
from typing import NamedTuple

import fitz
from PIL import Image, ImageDraw, ImageFont

# Default subject burned in across fixtures; a two-token name exercises whitespace
# normalization without being so short OCR noise would spuriously match it.
DEFAULT_REDACTED_STRING = "John Smith"

# Benign label rendered on pages so they look like a real redacted body, not a blank page.
REDACTED_LABEL = "[REDACTED]"

_PAGE_WIDTH = 400.0
_PAGE_HEIGHT = 200.0
_TEXT_ORIGIN = fitz.Point(72, 100)
_TEXT_FONTSIZE = 14

# Source-image geometry for the image-only body label (mirrors redaction_pdfs.py).
_IMAGE_WIDTH = 1000
_IMAGE_HEIGHT = 200
_LABEL_FONT_SIZE = 90
_IMAGE_RECT = fitz.Rect(0, 0, _PAGE_WIDTH, _PAGE_WIDTH * _IMAGE_HEIGHT / _IMAGE_WIDTH)

# EXIF Artist tag id (0x013B); attached to the annotated-EXIF fixture's embedded image.
_EXIF_ARTIST_TAG = 0x013B


class PiiSpanRef(NamedTuple):
    """A known PII span in a source fixture: 1-based page, PDF-point bbox, and text.

    Lets a test build the matching ``ApprovedSpan`` without re-searching the PDF.
    """

    page_number: int
    bbox: tuple[float, float, float, float]
    text: str


def _render_label_image(text: str) -> bytes:
    """Render ``text`` as black glyphs on a white PNG (visible, no text layer)."""
    img = Image.new("RGB", (_IMAGE_WIDTH, _IMAGE_HEIGHT), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=_LABEL_FONT_SIZE)
    draw.text((30, 40), text, fill="black", font=font)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _text_bbox(page: fitz.Page, text: str) -> tuple[float, float, float, float]:
    """Return the first on-page bbox of ``text`` in PDF points (x0, y0, x1, y1)."""
    rect = page.search_for(text)[0]
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def make_pii_source_pdf(redacted_string: str = DEFAULT_REDACTED_STRING) -> tuple[bytes, PiiSpanRef]:
    """One page with a live-text PII string at a known bbox (plus its span ref).

    The returned ``PiiSpanRef`` carries the exact glyph bbox so a test can build the
    ``ApprovedSpan`` that ``apply`` must burn a box over.
    """
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    page.insert_text(_TEXT_ORIGIN, redacted_string, fontsize=_TEXT_FONTSIZE)
    ref = PiiSpanRef(page_number=1, bbox=_text_bbox(page, redacted_string), text=redacted_string)
    data: bytes = doc.tobytes()
    doc.close()
    return data, ref


def make_multi_page_pii_pdf(redacted_strings: list[str]) -> tuple[bytes, list[PiiSpanRef]]:
    """Multi-page source: one live-text PII string per page, with per-page span refs."""
    doc = fitz.open()
    refs: list[PiiSpanRef] = []
    for index, redacted_string in enumerate(redacted_strings, start=1):
        page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
        page.insert_text(_TEXT_ORIGIN, redacted_string, fontsize=_TEXT_FONTSIZE)
        refs.append(PiiSpanRef(page_number=index, bbox=_text_bbox(page, redacted_string), text=redacted_string))
    data: bytes = doc.tobytes()
    doc.close()
    return data, refs


def inject_document_javascript(doc: fitz.Document, script: str) -> None:
    """Attach document-level JavaScript via the catalog Names tree and OpenAction.

    Shared by ``make_js_and_embedded_file_pdf`` and the direct strip unit test so both
    inject JS the same way. Sets ``Names/JavaScript`` (without clobbering a sibling
    ``EmbeddedFiles`` name tree) and an ``OpenAction`` JS action.
    """
    catalog = doc.pdf_catalog()
    js_xref = doc.get_new_xref()
    doc.update_object(js_xref, f"<< /S /JavaScript /JS ({script}) >>")
    doc.xref_set_key(catalog, "Names/JavaScript", f"<< /Names [ (JS0) {js_xref} 0 R ] >>")
    doc.xref_set_key(catalog, "OpenAction", f"<< /S /JavaScript /JS ({script}) >>")


def document_has_javascript(doc: fitz.Document) -> bool:
    """True if ``doc``'s catalog carries document-level JavaScript or an OpenAction."""
    catalog = doc.pdf_catalog()
    for key in ("Names/JavaScript", "OpenAction"):
        type_name, _value = doc.xref_get_key(catalog, key)
        if type_name != "null":
            return True
    return False


def make_js_and_embedded_file_pdf(redacted_string: str = DEFAULT_REDACTED_STRING) -> bytes:
    """Clean visible body, but JS + an embedded file + metadata all leak the string.

    Exercises the R5 strip checklist: document-level JavaScript (Names tree + OpenAction),
    an embedded file whose bytes contain the string, docinfo (author), and XMP all carry
    ``redacted_string``. ``apply`` must produce output with none of these.
    """
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    page.insert_image(_IMAGE_RECT, stream=_render_label_image(REDACTED_LABEL))
    doc.set_metadata({"title": "Quarterly Report", "author": redacted_string})
    doc.set_xml_metadata(
        f"<x:xmpmeta xmlns:x='adobe:ns:meta/'><dc:creator>{redacted_string}</dc:creator></x:xmpmeta>"
    )
    doc.embfile_add("payload.txt", redacted_string.encode("utf-8"), filename="payload.txt")
    inject_document_javascript(doc, f"app.alert('{redacted_string}');")
    data: bytes = doc.tobytes()
    doc.close()
    return data


def make_annotated_exif_pdf(redacted_string: str = DEFAULT_REDACTED_STRING) -> bytes:
    """A page with annotations and an EXIF-tagged image (Amendment B regression fixture).

    Carries (a) a highlight annotation plus a text/sticky-note annotation whose content is
    ``redacted_string`` and (b) a JPEG image with an EXIF ``Artist`` tag set to
    ``redacted_string``. Rebuilding from rasterized images must drop both the annotations
    and the EXIF for free -- this fixture pins that behavior structurally, separate from the
    explicit R5 strip calls.
    """
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    page.insert_text(_TEXT_ORIGIN, REDACTED_LABEL, fontsize=_TEXT_FONTSIZE)
    page.add_highlight_annot(fitz.Rect(70, 90, 200, 112))
    text_annot = page.add_text_annot(fitz.Point(220, 96), redacted_string)
    text_annot.update()

    image = Image.new("RGB", (120, 60), "white")
    exif = Image.Exif()
    exif[_EXIF_ARTIST_TAG] = redacted_string
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    page.insert_image(fitz.Rect(250, 20, 370, 80), stream=buffer.getvalue())

    data: bytes = doc.tobytes()
    doc.close()
    return data
