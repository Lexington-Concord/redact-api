"""Confidence-floor tests for Tier-2 detection (detection/tier2.py).

Presidio results scoring below ``TIER2_MIN_CONFIDENCE`` are dropped at detection
time (R4). The floor is inclusive (``>=``): ``PhoneRecognizer``'s base score is
exactly ``TIER2_MIN_CONFIDENCE = 0.4``, so an exclusive floor would silently drop
every base-confidence phone hit. This is asserted deterministically by feeding
canned ``RecognizerResult`` scores through a stubbed batch analyzer, so it is not
subject to model-scoring drift (R8).
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from presidio_analyzer import RecognizerResult

from redact_api.detection import tier2
from redact_api.detection.consts import TIER2_MIN_CONFIDENCE
from redact_api.detection.tier2 import detect_entities
from redact_api.tests.fixtures.detection_pages_tier2 import make_page

_PAGE_TEXT = "one 415-555-0111 two 415-555-0222 three 415-555-0333"


class _StubBatchAnalyzer:
    """Minimal ``BatchAnalyzerEngine`` stand-in returning canned results."""

    def __init__(self, results_per_page: list[list[RecognizerResult]]) -> None:
        self._results_per_page = results_per_page

    def analyze_iterator(
        self,
        texts: Iterable[str],
        language: str,
        entities: list[str] | None = None,
    ) -> list[list[RecognizerResult]]:
        _ = list(texts), language, entities
        return self._results_per_page


def _phone_result(number: str, score: float) -> RecognizerResult:
    start = _PAGE_TEXT.index(number)
    return RecognizerResult(entity_type="PHONE_NUMBER", start=start, end=start + len(number), score=score)


class TestConfidenceFloor:
    def test_below_floor_dropped_at_and_above_floor_kept(self, monkeypatch: pytest.MonkeyPatch) -> None:
        results = [
            [
                _phone_result("415-555-0111", TIER2_MIN_CONFIDENCE - 0.01),
                _phone_result("415-555-0222", TIER2_MIN_CONFIDENCE),
                _phone_result("415-555-0333", TIER2_MIN_CONFIDENCE + 0.01),
            ]
        ]
        monkeypatch.setattr(tier2, "_get_batch_analyzer", lambda: _StubBatchAnalyzer(results))

        spans = detect_entities(make_page(_PAGE_TEXT))

        kept = sorted(span.confidence for span in spans)
        assert kept == [TIER2_MIN_CONFIDENCE, TIER2_MIN_CONFIDENCE + 0.01]

    def test_boundary_score_is_inclusive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        results = [[_phone_result("415-555-0222", TIER2_MIN_CONFIDENCE)]]
        monkeypatch.setattr(tier2, "_get_batch_analyzer", lambda: _StubBatchAnalyzer(results))

        (span,) = detect_entities(make_page(_PAGE_TEXT))

        assert span.confidence == TIER2_MIN_CONFIDENCE
