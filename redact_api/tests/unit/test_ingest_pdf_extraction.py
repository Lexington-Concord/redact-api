"""Tests for PyMuPDF-based page-model extraction in redact_api.ingest.pdf.

Unit tests -- no database access. Fixture PDFs are built programmatically via
redact_api.tests.fixtures.ingest_pdfs (PyMuPDF only, no second PDF library).
"""

from __future__ import annotations

import itertools

import fitz
import pytest

from redact_api.ingest.consts import RASTER_DPI
from redact_api.ingest.exceptions import UnsupportedPageError
from redact_api.ingest.pdf import extract_pages
from redact_api.tests.fixtures.ingest_pdfs import (
    PAGE_HEIGHT,
    PAGE_WIDTH,
    build_image_only_pdf,
    build_multi_page_pdf,
    build_non_ascii_pdf,
    build_rotated_page_pdf,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _ground_truth_words(pdf_bytes: bytes, page_index: int) -> list[tuple[float, float, float, float, str, int, int, int]]:
    """Independently derive the expected word list via a direct fitz call.

    Deliberately bypasses redact_api.ingest.pdf so the test doesn't just
    re-check production code against itself.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc.load_page(page_index)
        return sorted(page.get_text("words"), key=lambda word: (word[5], word[6], word[7]))
    finally:
        doc.close()


class TestMultiPageExtraction:
    def test_correct_page_count(self) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=3)
        extractions = extract_pages(pdf_bytes)
        assert len(extractions) == 3

    def test_one_based_page_numbers(self) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=3)
        extractions = extract_pages(pdf_bytes)
        assert [extraction.page.page_number for extraction in extractions] == [1, 2, 3]

    def test_non_empty_text(self) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=2)
        extractions = extract_pages(pdf_bytes)
        for extraction in extractions:
            assert extraction.page.text != ""

    def test_word_offsets_round_trip_against_independent_fitz_extraction(self) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=2)
        extractions = extract_pages(pdf_bytes)

        for page_index, extraction in enumerate(extractions):
            expected_words = _ground_truth_words(pdf_bytes, page_index)
            assert len(extraction.page.words) == len(expected_words)
            for word_bbox, raw_word in zip(extraction.page.words, expected_words, strict=True):
                expected_text = raw_word[4]
                assert extraction.page.text[word_bbox.start : word_bbox.end] == expected_text


class TestRotatedPageExtraction:
    def test_rotation_reflected_on_page_model(self) -> None:
        pdf_bytes = build_rotated_page_pdf(rotation=90)
        extractions = extract_pages(pdf_bytes)
        assert extractions[0].page.rotation == 90

    def test_zero_rotation_default(self) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=1)
        extractions = extract_pages(pdf_bytes)
        assert extractions[0].page.rotation == 0

    def test_bbox_coordinates_remain_sane(self) -> None:
        pdf_bytes = build_rotated_page_pdf(rotation=90)
        extractions = extract_pages(pdf_bytes)
        for word_bbox in extractions[0].page.words:
            x0, y0, x1, y1 = word_bbox.bbox
            assert 0 <= x0 < x1 <= PAGE_WIDTH
            assert 0 <= y0 < y1 <= PAGE_HEIGHT

    def test_raster_dimensions_reflect_rotation(self) -> None:
        pdf_bytes = build_rotated_page_pdf(rotation=90)
        extractions = extract_pages(pdf_bytes)
        pixmap = fitz.Pixmap(extractions[0].png_bytes)
        expected_width = round(PAGE_HEIGHT * RASTER_DPI / 72)
        expected_height = round(PAGE_WIDTH * RASTER_DPI / 72)
        assert (pixmap.width, pixmap.height) == (expected_width, expected_height)


class TestNonAsciiExtraction:
    def test_multi_byte_characters_preserved(self) -> None:
        pdf_bytes = build_non_ascii_pdf()
        extractions = extract_pages(pdf_bytes)
        text = extractions[0].page.text
        assert "café" in text
        assert "日本語" in text
        assert "ñ" in text

    def test_offsets_are_character_indices_not_byte_indices(self) -> None:
        pdf_bytes = build_non_ascii_pdf()
        extractions = extract_pages(pdf_bytes)
        page = extractions[0].page

        cjk_word = next(word for word in page.words if page.text[word.start : word.end] == "日本語")
        # "日本語" is 3 Python str characters but 9 UTF-8 bytes; if offsets were
        # byte-based this slice would be wrong (or raise) since the buffer is
        # indexed as a Python str throughout.
        assert cjk_word.end - cjk_word.start == 3
        assert page.text[cjk_word.start : cjk_word.end] == "日本語"

    def test_word_offsets_round_trip_against_independent_fitz_extraction(self) -> None:
        pdf_bytes = build_non_ascii_pdf()
        extractions = extract_pages(pdf_bytes)
        expected_words = _ground_truth_words(pdf_bytes, 0)

        page = extractions[0].page
        assert len(page.words) == len(expected_words)
        for word_bbox, raw_word in zip(page.words, expected_words, strict=True):
            assert page.text[word_bbox.start : word_bbox.end] == raw_word[4]


class TestRasterEncoding:
    def test_pixmap_sized_by_dpi_conversion(self) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=1)
        extractions = extract_pages(pdf_bytes)
        pixmap = fitz.Pixmap(extractions[0].png_bytes)
        expected_width = round(PAGE_WIDTH * RASTER_DPI / 72)
        expected_height = round(PAGE_HEIGHT * RASTER_DPI / 72)
        assert (pixmap.width, pixmap.height) == (expected_width, expected_height)

    def test_raster_bytes_start_with_png_magic_number(self) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=1)
        extractions = extract_pages(pdf_bytes)
        assert extractions[0].png_bytes.startswith(PNG_MAGIC)

    def test_raster_round_trips_through_fitz_pixmap(self) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=1)
        extractions = extract_pages(pdf_bytes)
        pixmap = fitz.Pixmap(extractions[0].png_bytes)
        assert pixmap.width == round(PAGE_WIDTH * RASTER_DPI / 72)
        assert pixmap.height == round(PAGE_HEIGHT * RASTER_DPI / 72)

    def test_bboxes_are_plain_floats_in_pdf_point_units(self) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=1)
        extractions = extract_pages(pdf_bytes)
        for word_bbox in extractions[0].page.words:
            for coordinate in word_bbox.bbox:
                assert isinstance(coordinate, float)
                assert 0 <= coordinate <= max(PAGE_WIDTH, PAGE_HEIGHT)


class TestTextConstruction:
    def test_text_built_solely_from_words_no_gap_or_overlap(self) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=1)
        extractions = extract_pages(pdf_bytes)
        page = extractions[0].page

        assert page.words[0].start == 0
        for word_bbox in page.words:
            assert page.text[word_bbox.start : word_bbox.end] != ""

        for previous_word, next_word in itertools.pairwise(page.words):
            separator = page.text[previous_word.end : next_word.start]
            assert separator in (" ", "\n")

        assert page.words[-1].end == len(page.text)

    def test_same_line_words_joined_by_single_space(self) -> None:
        pdf_bytes = build_multi_page_pdf(page_count=1)
        extractions = extract_pages(pdf_bytes)
        page = extractions[0].page
        expected_words = _ground_truth_words(pdf_bytes, 0)

        for index in range(len(expected_words) - 1):
            current_block, current_line = expected_words[index][5], expected_words[index][6]
            next_block, next_line = expected_words[index + 1][5], expected_words[index + 1][6]
            separator = page.text[page.words[index].end : page.words[index + 1].start]
            if (current_block, current_line) == (next_block, next_line):
                assert separator == " "
            else:
                assert separator == "\n"


class TestImageOnlyPage:
    def test_raises_unsupported_page_error_not_silent_empty_text(self) -> None:
        pdf_bytes = build_image_only_pdf(page_count=1)
        with pytest.raises(UnsupportedPageError) as exc_info:
            extract_pages(pdf_bytes)
        assert exc_info.value.page_numbers == [1]
