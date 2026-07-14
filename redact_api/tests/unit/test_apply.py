"""Behavioral tests for the irreversible redaction burn-in (``apply``).

Organized by concern following the per-feature test-class convention: model contract,
image-only rebuild (R6), box drawing (R4), metadata/JS/embedded-file strip plus the
Amendment B structural regression (R5), output DPI (R3), input validation, the multi-page
path, real verify-gate integration (R2/R7), and a verify-gate regression guard.

OCR strategy mirrors ``test_verify_gate.py``: the autouse ``_ocr_stub`` fixture stubs
tesseract to empty output, so non-``real_ocr`` tests prove the gate wiring and the
no-text-layer / clean-metadata output without needing the binary. The end-to-end real
recognition path (a burned-in box actually defeats OCR) is proven by the ``real_ocr``
test, which runs for real in CI and is skipped when the binary is absent.
"""

from __future__ import annotations

import io

import fitz
import pytest
from PIL import Image

from redact_api.redaction.apply import _strip_document_javascript, _strip_metadata, apply
from redact_api.redaction.consts import APPLY_OUTPUT_DPI, BOX_PADDING_PTS
from redact_api.redaction.models import (
    ApplyResult,
    ApprovedSpan,
    CheckSummary,
    CheckType,
    VerifyFinding,
    VerifyResult,
    VerifyVerdict,
)
from redact_api.redaction.verify_gate import verify
from redact_api.tests.fixtures.apply_pdfs import (
    DEFAULT_REDACTED_STRING,
    PiiSpanRef,
    document_has_javascript,
    inject_document_javascript,
    make_annotated_exif_pdf,
    make_js_and_embedded_file_pdf,
    make_multi_page_pii_pdf,
    make_pii_source_pdf,
)
from redact_api.tests.fixtures.redaction_pdfs import make_metadata_leak_pdf, make_overlay_only_pdf

# Channel thresholds for classifying a sampled RGB pixel as opaque-black or blank-white.
_BLACK_MAX = 20
_WHITE_MIN = 235


def _span(ref: PiiSpanRef) -> ApprovedSpan:
    """Build the ``ApprovedSpan`` a fixture's ``PiiSpanRef`` describes."""
    return ApprovedSpan(page_number=ref.page_number, bboxes=[ref.bbox], text=ref.text)


def _render_page(pdf_bytes: bytes, page_index: int = 0, dpi: int = APPLY_OUTPUT_DPI) -> Image.Image:
    """Rasterize one output page to an RGB PIL image for pixel sampling."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pixmap = doc[page_index].get_pixmap(dpi=dpi)
        return Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
    finally:
        doc.close()


def _pixel_at_point(
    image: Image.Image, x_pts: float, y_pts: float, dpi: int = APPLY_OUTPUT_DPI
) -> tuple[int, int, int]:
    """Sample the pixel at a PDF-point coordinate on a ``dpi``-rendered page image."""
    scale = dpi / 72.0
    px = min(image.width - 1, max(0, round(x_pts * scale)))
    py = min(image.height - 1, max(0, round(y_pts * scale)))
    return image.getpixel((px, py))  # type: ignore[return-value]


def _is_black(pixel: tuple[int, int, int]) -> bool:
    return all(channel <= _BLACK_MAX for channel in pixel)


def _is_white(pixel: tuple[int, int, int]) -> bool:
    return all(channel >= _WHITE_MIN for channel in pixel)


def _image_exifs(pdf_bytes: bytes) -> list[dict[int, object]]:
    """Return the EXIF dict of every image embedded in every page of ``pdf_bytes``."""
    exifs: list[dict[int, object]] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page in doc:
            for xref in (info[0] for info in page.get_images()):
                image = Image.open(io.BytesIO(doc.extract_image(xref)["image"]))
                exifs.append(dict(image.getexif()))
    finally:
        doc.close()
    return exifs


class TestApprovedSpanAndApplyResultContract:
    """R1/R2 model contract: span fields and the ApplyResult.passed verdict mirror."""

    def test_approved_span_holds_page_bboxes_and_text(self) -> None:
        span = ApprovedSpan(page_number=1, bboxes=[(1.0, 2.0, 3.0, 4.0)], text="secret")
        assert span.page_number == 1
        assert span.bboxes == [(1.0, 2.0, 3.0, 4.0)]
        assert span.text == "secret"

    def test_approved_span_holds_multiple_bboxes(self) -> None:
        # R1: bboxes is a list because one logical span (e.g. text wrapping across
        # lines) can cover more than one bbox on the same page.
        span = ApprovedSpan(
            page_number=1, bboxes=[(1.0, 2.0, 3.0, 4.0), (1.0, 5.0, 3.0, 7.0)], text="secret"
        )
        assert span.bboxes == [(1.0, 2.0, 3.0, 4.0), (1.0, 5.0, 3.0, 7.0)]

    def test_apply_result_passed_true_when_verdict_pass(self) -> None:
        verify_result = VerifyResult(verdict=VerifyVerdict.PASS, checks=[], findings=[])
        assert ApplyResult(pdf_bytes=b"%PDF-", verify_result=verify_result).passed is True

    def test_apply_result_passed_false_when_verdict_fail(self) -> None:
        finding = VerifyFinding(redacted_string_digest="abc", check_type=CheckType.TEXT_LAYER, page_number=1)
        summary = CheckSummary(check_type=CheckType.TEXT_LAYER, passed=False, pages_checked=1)
        verify_result = VerifyResult(verdict=VerifyVerdict.FAIL, checks=[summary], findings=[finding])
        assert ApplyResult(pdf_bytes=b"%PDF-", verify_result=verify_result).passed is False


class TestApplyRebuildProperties:
    """R6: the output is image-only -- no surviving text layer on any page."""

    def test_output_has_no_extractable_text(self) -> None:
        pdf_bytes, ref = make_pii_source_pdf()
        result = apply(pdf_bytes, [_span(ref)])
        doc = fitz.open(stream=result.pdf_bytes, filetype="pdf")
        try:
            for page in doc:
                assert page.get_text().strip() == ""
                assert page.get_text("words") == []
        finally:
            doc.close()

    def test_output_is_valid_pdf_with_same_page_count(self) -> None:
        pdf_bytes, ref = make_pii_source_pdf()
        result = apply(pdf_bytes, [_span(ref)])
        doc = fitz.open(stream=result.pdf_bytes, filetype="pdf")
        try:
            assert doc.page_count == 1
            assert doc[0].get_images()  # rebuilt from an image
        finally:
            doc.close()


class TestApplyBoxDrawing:
    """R4: an opaque black box, inflated by BOX_PADDING_PTS, covers each span's bbox."""

    def test_span_region_is_opaque_black(self) -> None:
        pdf_bytes, ref = make_pii_source_pdf()
        result = apply(pdf_bytes, [_span(ref)])
        image = _render_page(result.pdf_bytes)
        x0, y0, x1, y1 = ref.bbox
        center = _pixel_at_point(image, (x0 + x1) / 2, (y0 + y1) / 2)
        assert _is_black(center)

    def test_region_far_from_span_is_untouched(self) -> None:
        pdf_bytes, ref = make_pii_source_pdf()
        result = apply(pdf_bytes, [_span(ref)])
        image = _render_page(result.pdf_bytes)
        # A corner well clear of the redacted text stays blank white.
        assert _is_white(_pixel_at_point(image, 5.0, 5.0))

    def test_padding_extends_box_beyond_raw_bbox(self) -> None:
        pdf_bytes, ref = make_pii_source_pdf()
        result = apply(pdf_bytes, [_span(ref)])
        image = _render_page(result.pdf_bytes)
        _x0, y0, x1, y1 = ref.bbox
        y_mid = (y0 + y1) / 2
        # Just past the glyph edge but within the padding band -> still covered (black);
        # well past the padded edge -> uncovered (white). Proves the inflation is applied.
        assert _is_black(_pixel_at_point(image, x1 + BOX_PADDING_PTS * 0.5, y_mid))
        assert _is_white(_pixel_at_point(image, x1 + BOX_PADDING_PTS * 4, y_mid))

    def test_span_bbox_overflowing_page_is_clamped(self) -> None:
        # A padded bbox exceeding the page bounds must be clamped, not crash, and still
        # paint the top-left corner black (exercises both clamp branches).
        pdf_bytes, _ref = make_pii_source_pdf()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_rect = doc[0].rect
        doc.close()
        overflowing = ApprovedSpan(
            page_number=1,
            bboxes=[(0.0, 0.0, page_rect.width + 100, page_rect.height + 100)],
            text=DEFAULT_REDACTED_STRING,
        )
        result = apply(pdf_bytes, [overflowing])
        image = _render_page(result.pdf_bytes)
        assert _is_black(_pixel_at_point(image, 1.0, 1.0))

    def test_span_with_multiple_bboxes_blacks_out_every_region(self) -> None:
        # R1: a single span's bboxes can cover more than one region (e.g. wrapped text).
        # Regression guard for the exact defect the bboxes-plural fix addressed -- if
        # _draw_boxes only painted the first bbox in the list, this test would catch it.
        pdf_bytes, _ref = make_pii_source_pdf()
        bbox_a = (10.0, 10.0, 50.0, 30.0)
        bbox_b = (300.0, 160.0, 340.0, 180.0)
        span = ApprovedSpan(page_number=1, bboxes=[bbox_a, bbox_b], text=DEFAULT_REDACTED_STRING)
        result = apply(pdf_bytes, [span])
        image = _render_page(result.pdf_bytes)
        for x0, y0, x1, y1 in (bbox_a, bbox_b):
            assert _is_black(_pixel_at_point(image, (x0 + x1) / 2, (y0 + y1) / 2))
        assert _is_white(_pixel_at_point(image, 200.0, 150.0))


class TestApplyMetadataStrip:
    """R5: explicit docinfo/XMP/embedded-file/JS strip, plus Amendment B structural regression."""

    def test_output_has_no_embedded_files(self) -> None:
        result = apply(make_js_and_embedded_file_pdf(), [])
        doc = fitz.open(stream=result.pdf_bytes, filetype="pdf")
        try:
            assert doc.embfile_names() == []
        finally:
            doc.close()

    def test_output_has_no_xml_metadata(self) -> None:
        result = apply(make_js_and_embedded_file_pdf(), [])
        doc = fitz.open(stream=result.pdf_bytes, filetype="pdf")
        try:
            assert not doc.get_xml_metadata()
        finally:
            doc.close()

    def test_output_docinfo_carries_no_leak(self) -> None:
        result = apply(make_js_and_embedded_file_pdf(), [])
        doc = fitz.open(stream=result.pdf_bytes, filetype="pdf")
        try:
            leaked = [value for value in doc.metadata.values() if value and DEFAULT_REDACTED_STRING in value]
            assert leaked == []
        finally:
            doc.close()

    def test_output_has_no_document_javascript(self) -> None:
        result = apply(make_js_and_embedded_file_pdf(), [])
        doc = fitz.open(stream=result.pdf_bytes, filetype="pdf")
        try:
            assert document_has_javascript(doc) is False
        finally:
            doc.close()

    def test_strip_document_javascript_removes_js_directly(self) -> None:
        # Direct unit test of the private helper: it must actually remove JS from a doc
        # that has it (apply's rebuilt doc is JS-free, so this exercises the removal path).
        doc = fitz.open()
        doc.new_page()
        inject_document_javascript(doc, "app.alert('x');")
        try:
            assert document_has_javascript(doc) is True
            _strip_document_javascript(doc)
            assert document_has_javascript(doc) is False
        finally:
            doc.close()

    def test_strip_metadata_removes_embedded_files_and_docinfo_directly(self) -> None:
        # Direct unit test of the R5 checklist against a doc that actually carries an
        # embedded file, docinfo, and XMP -- apply's rebuilt image-only doc has none, so
        # this exercises the strip calls (the convenience-copy guard) they otherwise skip.
        doc = fitz.open()
        doc.new_page()
        doc.set_metadata({"author": DEFAULT_REDACTED_STRING})
        doc.set_xml_metadata(f"<x:xmpmeta xmlns:x='adobe:ns:meta/'>{DEFAULT_REDACTED_STRING}</x:xmpmeta>")
        doc.embfile_add("payload.txt", DEFAULT_REDACTED_STRING.encode("utf-8"), filename="payload.txt")
        try:
            assert doc.embfile_names() == ["payload.txt"]
            _strip_metadata(doc)
            assert doc.embfile_names() == []
            assert not doc.get_xml_metadata()
            assert [value for value in doc.metadata.values() if value and DEFAULT_REDACTED_STRING in value] == []
        finally:
            doc.close()

    def test_rebuild_strips_annotations_and_exif(self) -> None:
        # Amendment B structural regression: rebuild-from-rasterized-images drops
        # annotations and image EXIF for free, distinct from the explicit strip calls above.
        source_bytes = make_annotated_exif_pdf()

        # Positive control: confirm the source fixture actually carries annotations and
        # EXIF, so the strip assertions below can't pass vacuously against an empty input.
        source_doc = fitz.open(stream=source_bytes, filetype="pdf")
        try:
            assert list(source_doc[0].annots()) != []
        finally:
            source_doc.close()
        assert any(exif for exif in _image_exifs(source_bytes))

        result = apply(source_bytes, [])
        doc = fitz.open(stream=result.pdf_bytes, filetype="pdf")
        try:
            for page in doc:
                assert list(page.annots()) == []
        finally:
            doc.close()
        for exif in _image_exifs(result.pdf_bytes):
            assert exif == {}


class TestApplyOutputDPI:
    """R3: pages are rasterized at APPLY_OUTPUT_DPI before rebuild."""

    def test_output_image_resolution_matches_apply_output_dpi(self) -> None:
        pdf_bytes, ref = make_pii_source_pdf()
        result = apply(pdf_bytes, [_span(ref)])
        doc = fitz.open(stream=result.pdf_bytes, filetype="pdf")
        try:
            page = doc[0]
            xref = page.get_images()[0][0]
            image = Image.open(io.BytesIO(doc.extract_image(xref)["image"]))
            effective_dpi = image.width / (page.rect.width / 72.0)
        finally:
            doc.close()
        assert abs(effective_dpi - APPLY_OUTPUT_DPI) <= 2


class TestApplyValidation:
    """Out-of-range span page numbers raise ValueError (Adopted Assumption 2)."""

    @pytest.mark.parametrize("page_number", [0, -1, 2, 99])
    def test_out_of_range_page_number_raises(self, page_number: int) -> None:
        pdf_bytes, ref = make_pii_source_pdf()  # single-page document
        span = ApprovedSpan(page_number=page_number, bboxes=[ref.bbox], text=ref.text)
        with pytest.raises(ValueError, match="page number"):
            apply(pdf_bytes, [span])


class TestApplyMultiPage:
    """The multi-page path: every page is rebuilt image-only; only targeted pages get boxes."""

    def test_redacts_targeted_pages_and_rebuilds_all(self) -> None:
        pdf_bytes, refs = make_multi_page_pii_pdf(["Alice Alpha", "Bob Beta", "Cara Gamma"])
        # Redact only page 2, leaving pages 1 and 3 boxless (but still image-only rebuilt).
        target = refs[1]
        result = apply(pdf_bytes, [_span(target)])
        doc = fitz.open(stream=result.pdf_bytes, filetype="pdf")
        try:
            assert doc.page_count == 3
            for page in doc:
                assert page.get_text().strip() == ""
        finally:
            doc.close()
        image = _render_page(result.pdf_bytes, page_index=1)
        x0, y0, x1, y1 = target.bbox
        assert _is_black(_pixel_at_point(image, (x0 + x1) / 2, (y0 + y1) / 2))

    def test_redacts_all_pages_when_all_targeted(self) -> None:
        pdf_bytes, refs = make_multi_page_pii_pdf(["Alice Alpha", "Bob Beta"])
        result = apply(pdf_bytes, [_span(ref) for ref in refs])
        for page_index, ref in enumerate(refs):
            image = _render_page(result.pdf_bytes, page_index=page_index)
            x0, y0, x1, y1 = ref.bbox
            assert _is_black(_pixel_at_point(image, (x0 + x1) / 2, (y0 + y1) / 2))


class TestApplyRealVerifyGateIntegration:
    """R2/R7: apply runs the real verify gate on its own output before returning."""

    def test_returns_apply_result_with_output_bytes(self) -> None:
        pdf_bytes, ref = make_pii_source_pdf()
        result = apply(pdf_bytes, [_span(ref)])
        assert isinstance(result, ApplyResult)
        assert result.pdf_bytes.startswith(b"%PDF")
        assert isinstance(result.verify_result, VerifyResult)

    def test_clean_apply_passes_gate(self) -> None:
        # OCR is stubbed empty here; the output has no text layer and clean metadata, so
        # the gate must PASS and ApplyResult.passed must mirror that.
        pdf_bytes, ref = make_pii_source_pdf()
        result = apply(pdf_bytes, [_span(ref)])
        assert result.verify_result.verdict == VerifyVerdict.PASS
        assert result.passed is True

    @pytest.mark.real_ocr
    def test_clean_apply_passes_real_gate(self) -> None:
        # With the real tesseract engine, the burned-in box must actually defeat OCR: the
        # redacted string is not recoverable, so the real gate PASSes.
        pdf_bytes, ref = make_pii_source_pdf()
        result = apply(pdf_bytes, [_span(ref)])
        assert result.passed is True
        assert result.verify_result.verdict == VerifyVerdict.PASS


class TestVerifyGateRegressionGuard:
    """R7: apply forwards to the real gate -- the gate still FAILs on known-bad fixtures."""

    def test_gate_still_fails_on_overlay_only(self) -> None:
        result = verify(make_overlay_only_pdf(), [DEFAULT_REDACTED_STRING])
        assert result.verdict == VerifyVerdict.FAIL

    def test_gate_still_fails_on_metadata_leak(self) -> None:
        result = verify(make_metadata_leak_pdf(), [DEFAULT_REDACTED_STRING])
        assert result.verdict == VerifyVerdict.FAIL
