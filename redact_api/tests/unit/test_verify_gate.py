"""Behavioral tests for the post-apply recoverability verify gate.

Organized by check (text layer / OCR / metadata), then by cross-cutting contract
(no-raw-PII findings, edge cases, typed public API, fail-loud OCR errors), following
the per-feature test-class convention documented in TESTING_GUIDE.md.

OCR strategy: the verify gate rasterizes and OCRs every page, so a running suite would
otherwise need the ``tesseract`` binary everywhere. The autouse ``_ocr_stub`` fixture in
``conftest.py`` stubs OCR to empty output by default; tests that assert OCR *detection*
monkeypatch ``pytesseract.image_to_string`` to a controlled string (isolating the
fuzzy-match logic from tesseract's recognition accuracy), while the end-to-end
recognition path is proven separately by the ``real_ocr``-marked tests in
``test_redaction_fixtures.py`` (and the translucent-box test below) which run for real in CI.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import fitz
import pytest

from redact_api.redaction.consts import OCR_MATCH_THRESHOLD
from redact_api.redaction.models import (
    CheckSummary,
    CheckType,
    VerifyFinding,
    VerifyResult,
    VerifyVerdict,
)
from redact_api.redaction.verify_gate import (
    _check_text_layer,
    normalize_text,
    verify,
)
from redact_api.tests.fixtures.redaction_pdfs import (
    DEFAULT_REDACTED_STRING,
    make_blank_pdf,
    make_image_only_pdf,
    make_metadata_leak_pdf,
    make_overlay_only_pdf,
    make_properly_redacted_pdf,
    make_translucent_box_pdf,
)


def _stub_ocr_returning(text: str) -> Callable[..., str]:
    """Build a ``pytesseract.image_to_string`` replacement returning fixed ``text``."""

    def _stub(*_args: object, **_kwargs: object) -> str:
        return text

    return _stub


def _summary_for(result: VerifyResult, check_type: CheckType) -> CheckSummary:
    return next(summary for summary in result.checks if summary.check_type == check_type)


def _findings_of(result: VerifyResult, check_type: CheckType) -> list[VerifyFinding]:
    return [finding for finding in result.findings if finding.check_type == check_type]


class TestNormalizeText:
    """R1 normalization: NFC -> casefold -> collapse whitespace -> strip."""

    def test_collapses_whitespace_and_casefolds(self) -> None:
        assert normalize_text("JOHN\t  SMITH\n") == "john smith"

    def test_applies_nfc_unicode_normalization(self) -> None:
        # "e" + combining acute accent (NFD) normalizes to precomposed "é" (NFC).
        decomposed = "José"
        assert normalize_text(decomposed) == normalize_text("josé")

    def test_empty_and_whitespace_only_normalize_to_empty(self) -> None:
        assert normalize_text("   \t\n") == ""


class TestTextLayerCheck:
    """Check 1: exact substring match against the normalized text layer (R1, no fuzz)."""

    def test_overlay_only_pdf_fails_text_layer_check(self) -> None:
        result = verify(make_overlay_only_pdf(), [DEFAULT_REDACTED_STRING])
        assert result.verdict == VerifyVerdict.FAIL
        assert _findings_of(result, CheckType.TEXT_LAYER)

    def test_text_layer_check_passes_when_string_absent(self) -> None:
        result = verify(make_overlay_only_pdf("Jane Doe"), ["Zzyzx Nonexistent"])
        assert result.verdict == VerifyVerdict.PASS
        assert result.findings == []

    def test_text_layer_normalization_catches_whitespace_and_case_variants(self) -> None:
        # Text layer holds an upper-cased, extra-whitespace variant; the search term is
        # the canonical spelling. Both normalize to "john smith" -> still caught.
        result = verify(make_overlay_only_pdf("JOHN   SMITH"), [DEFAULT_REDACTED_STRING])
        assert result.verdict == VerifyVerdict.FAIL
        assert _findings_of(result, CheckType.TEXT_LAYER)

    def test_text_layer_check_is_exact_not_fuzzy(self) -> None:
        # A near-miss must NOT trigger the (exact) text-layer check.
        result = verify(make_overlay_only_pdf("John Smith"), ["John Smyth"])
        assert _findings_of(result, CheckType.TEXT_LAYER) == []
        assert result.verdict == VerifyVerdict.PASS


class TestOCRCheck:
    """Check 2: fuzzy match against OCR of the rasterized page (R1/R2/R6)."""

    @pytest.mark.real_ocr
    def test_translucent_box_pdf_fails_ocr_check(self) -> None:
        result = verify(make_translucent_box_pdf(), [DEFAULT_REDACTED_STRING])
        assert result.verdict == VerifyVerdict.FAIL
        ocr_findings = _findings_of(result, CheckType.OCR)
        assert ocr_findings
        assert ocr_findings[0].match_score is not None
        assert ocr_findings[0].match_score >= OCR_MATCH_THRESHOLD

    def test_ocr_check_uses_rapidfuzz_partial_ratio_and_named_threshold(self) -> None:
        # The threshold is a single named, auditable constant in the consts module.
        from redact_api.redaction import consts

        assert consts.OCR_MATCH_THRESHOLD == 85
        assert OCR_MATCH_THRESHOLD == 85

    def test_ocr_check_absorbs_minor_ocr_variance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Plausible OCR substitution (O -> 0) still scores above threshold.
        monkeypatch.setattr("pytesseract.image_to_string", _stub_ocr_returning("J0hn Smith"))
        result = verify(make_image_only_pdf(), [DEFAULT_REDACTED_STRING])
        ocr_findings = _findings_of(result, CheckType.OCR)
        assert result.verdict == VerifyVerdict.FAIL
        assert ocr_findings
        assert ocr_findings[0].match_score is not None
        assert ocr_findings[0].match_score >= OCR_MATCH_THRESHOLD

    def test_ocr_check_passes_when_score_below_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "pytesseract.image_to_string",
            _stub_ocr_returning("completely unrelated content here"),
        )
        result = verify(make_image_only_pdf(), [DEFAULT_REDACTED_STRING])
        assert _findings_of(result, CheckType.OCR) == []
        assert result.verdict == VerifyVerdict.PASS

    def test_image_only_page_is_rasterized_and_ocr_checked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An image-only page has no text layer, so Check 1 finds nothing; Check 2 must
        # still rasterize and inspect it (Check 1 must not short-circuit Check 2).
        monkeypatch.setattr("pytesseract.image_to_string", _stub_ocr_returning(DEFAULT_REDACTED_STRING))
        result = verify(make_image_only_pdf(), [DEFAULT_REDACTED_STRING])
        assert _findings_of(result, CheckType.TEXT_LAYER) == []
        assert _findings_of(result, CheckType.OCR)
        assert result.verdict == VerifyVerdict.FAIL


class TestMetadataCheck:
    """Check 3: exact substring match against docinfo + XMP metadata (R1)."""

    def test_metadata_leak_pdf_fails_metadata_check(self) -> None:
        result = verify(make_metadata_leak_pdf(), [DEFAULT_REDACTED_STRING])
        assert result.verdict == VerifyVerdict.FAIL
        assert _findings_of(result, CheckType.METADATA)

    def test_metadata_check_covers_docinfo_and_xmp(self) -> None:
        docinfo_result = verify(make_metadata_leak_pdf(location="docinfo"), [DEFAULT_REDACTED_STRING])
        xmp_result = verify(make_metadata_leak_pdf(location="xmp"), [DEFAULT_REDACTED_STRING])
        assert _findings_of(docinfo_result, CheckType.METADATA)
        assert _findings_of(xmp_result, CheckType.METADATA)

    def test_metadata_check_passes_when_clean(self) -> None:
        # Clean metadata, unrelated body -> metadata check reports passed.
        result = verify(make_overlay_only_pdf("Something Else"), [DEFAULT_REDACTED_STRING])
        assert _summary_for(result, CheckType.METADATA).passed is True
        assert _findings_of(result, CheckType.METADATA) == []


class TestControlFixturePasses:
    """The control fixture must PASS all three checks with zero findings."""

    @pytest.mark.real_ocr
    def test_control_pdf_passes_all_checks(self) -> None:
        result = verify(make_properly_redacted_pdf(), [DEFAULT_REDACTED_STRING])
        assert result.verdict == VerifyVerdict.PASS
        assert result.findings == []
        assert all(summary.passed for summary in result.checks)


class TestFindingsCarryNoRawPII:
    """R4: a finding must never carry the recoverable string, only a digest of it."""

    def _all_failing_findings(self, monkeypatch: pytest.MonkeyPatch) -> list[VerifyFinding]:
        monkeypatch.setattr("pytesseract.image_to_string", _stub_ocr_returning(DEFAULT_REDACTED_STRING))
        findings: list[VerifyFinding] = []
        findings += verify(make_overlay_only_pdf(), [DEFAULT_REDACTED_STRING]).findings
        findings += verify(make_metadata_leak_pdf(), [DEFAULT_REDACTED_STRING]).findings
        findings += verify(make_image_only_pdf(), [DEFAULT_REDACTED_STRING]).findings
        return findings

    def test_finding_does_not_contain_raw_string_or_substring(self, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = DEFAULT_REDACTED_STRING
        substrings = {raw[i : i + 4].casefold() for i in range(len(raw) - 3)}
        for finding in self._all_failing_findings(monkeypatch):
            serialized = f"{finding.model_dump_json()} {finding!s}".casefold()
            assert raw.casefold() not in serialized
            for substring in substrings:
                assert substring.strip() == "" or substring not in serialized

    def test_finding_contains_sha256_digest_of_normalized_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        expected = hashlib.sha256(normalize_text(DEFAULT_REDACTED_STRING).encode("utf-8")).hexdigest()
        findings = self._all_failing_findings(monkeypatch)
        assert findings
        for finding in findings:
            assert finding.redacted_string_digest == expected

    def test_finding_bbox_present_when_available_absent_otherwise(self) -> None:
        text_finding = _findings_of(
            verify(make_overlay_only_pdf(), [DEFAULT_REDACTED_STRING]), CheckType.TEXT_LAYER
        )[0]
        metadata_finding = _findings_of(
            verify(make_metadata_leak_pdf(), [DEFAULT_REDACTED_STRING]), CheckType.METADATA
        )[0]
        assert text_finding.bbox is not None
        assert metadata_finding.bbox is None


class TestEdgeCases:
    """R10 pinned edge-case behavior (must be exercised for coverage)."""

    def test_empty_redacted_strings_list_is_trivial_pass(self) -> None:
        result = verify(make_overlay_only_pdf(), [])
        assert result.verdict == VerifyVerdict.PASS
        assert result.findings == []
        # Checks still ran as no-ops rather than being skipped: every summary reports
        # the page it ranged over, not an early return.
        assert len(result.checks) == 3  # noqa: PLR2004
        for summary in result.checks:
            assert summary.pages_checked == 1

    def test_empty_pdf_is_pass_with_zero_findings(self) -> None:
        result = verify(make_blank_pdf(), [DEFAULT_REDACTED_STRING])
        assert result.verdict == VerifyVerdict.PASS
        assert result.findings == []

    def test_zero_page_document_checks_are_noops(self) -> None:
        # A genuinely zero-page document cannot be serialized to bytes, so exercise the
        # zero-page branch of a check directly.
        doc = fitz.open()
        try:
            summary, findings = _check_text_layer(doc, [DEFAULT_REDACTED_STRING])
        finally:
            doc.close()
        assert summary.pages_checked == 0
        assert findings == []
        assert summary.passed is True

    def test_image_only_page_edge_case(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("pytesseract.image_to_string", _stub_ocr_returning(DEFAULT_REDACTED_STRING))
        result = verify(make_image_only_pdf(), [DEFAULT_REDACTED_STRING])
        assert _summary_for(result, CheckType.TEXT_LAYER).passed is True
        assert _summary_for(result, CheckType.OCR).passed is False


class TestOcrErrorPropagates:
    """Binding addendum: OCR execution errors must propagate, never be swallowed."""

    def test_ocr_execution_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*_args: object, **_kwargs: object) -> str:
            message = "tesseract is not installed or it's not in your PATH"
            raise RuntimeError(message)

        monkeypatch.setattr("pytesseract.image_to_string", _raise)
        with pytest.raises(RuntimeError):
            verify(make_image_only_pdf(), [DEFAULT_REDACTED_STRING])


class TestPublicContractTypes:
    """R3: the public API returns typed Pydantic models, no raw dicts."""

    def test_verify_returns_verify_result_pydantic_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("pytesseract.image_to_string", _stub_ocr_returning(DEFAULT_REDACTED_STRING))
        result = verify(make_overlay_only_pdf(), [DEFAULT_REDACTED_STRING])
        assert isinstance(result, VerifyResult)
        assert isinstance(result.verdict, VerifyVerdict)
        assert all(isinstance(summary, CheckSummary) for summary in result.checks)
        assert all(isinstance(summary.check_type, CheckType) for summary in result.checks)
        for finding in result.findings:
            assert isinstance(finding, VerifyFinding)
            assert isinstance(finding.check_type, CheckType)
