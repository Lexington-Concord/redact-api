"""Tier-2 PII detection: Presidio + spaCy NER over raw page text (redact-api#5).

Wraps Microsoft Presidio (spaCy ``en_core_web_lg`` backend) to emit
``CandidateSpan`` objects stamped ``SourceTier.TIER_2`` for name / organization /
location, plus overlapping coverage of phone / email / ssn. The shape mirrors
``tier1.py``: synchronous, pure, no DB/API, one ``_to_candidate`` builder, and
module-private helpers.

Rules that hold across this module:

* Detection runs over the **raw** ``PageModel.text`` -- ``normalize_text`` is never
  applied, so Presidio's character offsets line up with ``WordBBox`` offsets and
  map to bboxes via ``resolve_span_bboxes`` (R7).
* ``detect_entities_batch`` is the *only* spaCy entrypoint: it drives
  ``BatchAnalyzerEngine`` (``nlp.pipe`` under the hood), and single-page
  ``detect_entities`` is a thin wrapper over it, so batching is exercised even for
  one page (R9). The module stays synchronous.
* Results scoring below ``TIER2_MIN_CONFIDENCE`` are dropped inclusively (R4), and
  only the six entity types in ``PRESIDIO_ENTITY_TO_CATEGORY`` become spans;
  everything else Presidio can emit is dropped (R5).

Why the custom ``nlp_configuration``: Presidio's shipped ``default.yaml`` lists
``ORGANIZATION`` in ``labels_to_ignore``, so a bare ``AnalyzerEngine()`` would
silently drop every organization -- contradicting R1/R5. The configuration here
supplies ``labels_to_ignore: []`` (with the full spaCy-label entity mapping) so
organizations survive. The analyzer/batch-analyzer are cached module singletons
(``lru_cache``) because loading ``en_core_web_lg`` is multi-second and ~400MB;
nothing else in this codebase loads a comparably expensive persistent resource.
"""

from __future__ import annotations

from functools import lru_cache

from presidio_analyzer import AnalyzerEngine, BatchAnalyzerEngine, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider

from redact_api.detection.base import resolve_span_bboxes
from redact_api.detection.consts import (
    PRESIDIO_ENTITY_TO_CATEGORY,
    TIER2_MIN_CONFIDENCE,
)
from redact_api.detection.models import CandidateSpan
from redact_api.ingest.models import PageModel
from redact_api.models.span import SourceTier

# Presidio analyzes English text with the CPU-only large spaCy model (R3).
_PRESIDIO_LANGUAGE = "en"
_SPACY_MODEL = "en_core_web_lg"
# Documented-but-unwired future config value (R3): a transformer-backed model
# trades V1's CPU-only latency for higher NER accuracy. Do not install
# spacy-transformers or wire a second code path until that tradeoff is
# actually needed -- this constant exists only so the decision has a home.
_SPACY_MODEL_TRANSFORMER_FUTURE = "en_core_web_trf"

# spaCy NER label -> Presidio entity type. Copied from Presidio's shipped
# ``default.yaml`` so overriding ``labels_to_ignore`` does not also drop the
# label mapping. ``labels_to_ignore`` is emptied so ORGANIZATION survives (R1/R5).
_MODEL_TO_PRESIDIO_ENTITY: dict[str, str] = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "NORP": "NRP",
    "FAC": "LOCATION",
    "LOC": "LOCATION",
    "GPE": "LOCATION",
    "LOCATION": "LOCATION",
    "ORG": "ORGANIZATION",
    "ORGANIZATION": "ORGANIZATION",
    "DATE": "DATE_TIME",
    "TIME": "DATE_TIME",
}

_NLP_CONFIGURATION: dict[str, object] = {
    "nlp_engine_name": "spacy",
    "models": [{"lang_code": _PRESIDIO_LANGUAGE, "model_name": _SPACY_MODEL}],
    "ner_model_configuration": {
        "model_to_presidio_entity_mapping": _MODEL_TO_PRESIDIO_ENTITY,
        # Presidio's own per-entity rescoring knob -- independent of
        # TIER2_MIN_CONFIDENCE (consts.py), which is this module's separate
        # detection-time emit floor. Same value (0.4) here is coincidental;
        # do not assume the two must move together.
        "low_confidence_score_multiplier": 0.4,
        "low_score_entity_names": [],
        "labels_to_ignore": [],
    },
}

# The Presidio entity types this service requests and maps to categories (R5).
_PRESIDIO_ENTITIES = tuple(PRESIDIO_ENTITY_TO_CATEGORY)


@lru_cache(maxsize=1)
def _get_analyzer() -> AnalyzerEngine:
    """Build (once) the Presidio analyzer with the custom spaCy NLP engine."""
    nlp_engine = NlpEngineProvider(nlp_configuration=_NLP_CONFIGURATION).create_engine()
    return AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=[_PRESIDIO_LANGUAGE])


@lru_cache(maxsize=1)
def _get_batch_analyzer() -> BatchAnalyzerEngine:
    """Build (once) the batch analyzer -- the sole spaCy entrypoint (R9)."""
    return BatchAnalyzerEngine(analyzer_engine=_get_analyzer())


def _to_candidate(page: PageModel, result: RecognizerResult) -> CandidateSpan | None:
    """Map one Presidio result to a ``CandidateSpan``; ``None`` if unmapped (R5)."""
    category = PRESIDIO_ENTITY_TO_CATEGORY.get(result.entity_type)
    if category is None:
        return None
    start, end = result.start, result.end
    return CandidateSpan(
        page_number=page.page_number,
        start=start,
        end=end,
        bboxes=resolve_span_bboxes(page, start, end),
        text=page.text[start:end],
        category=category,
        source_tier=SourceTier.TIER_2,
        confidence=result.score,
    )


def _page_spans(page: PageModel, results: list[RecognizerResult]) -> list[CandidateSpan]:
    """Apply the confidence floor (inclusive) and entity mapping to one page."""
    spans: list[CandidateSpan] = []
    for result in results:
        if result.score < TIER2_MIN_CONFIDENCE:
            continue
        candidate = _to_candidate(page, result)
        if candidate is not None:
            spans.append(candidate)
    return spans


def detect_entities_batch(pages: list[PageModel]) -> list[list[CandidateSpan]]:
    """Detect Tier-2 entities across ``pages``, one result list per page, in order.

    The sole spaCy entrypoint: all pages' raw text is fed through
    ``BatchAnalyzerEngine`` (``nlp.pipe``) in a single call, so batching is always
    exercised (R9). Per-page results preserve input order.
    """
    if not pages:
        return []
    analyzer = _get_batch_analyzer()
    texts = [page.text for page in pages]
    results_per_page = analyzer.analyze_iterator(
        texts, language=_PRESIDIO_LANGUAGE, entities=list(_PRESIDIO_ENTITIES)
    )
    return [_page_spans(page, results) for page, results in zip(pages, results_per_page, strict=True)]


def detect_entities(page: PageModel) -> list[CandidateSpan]:
    """Detect Tier-2 entities on a single ``page`` (thin wrapper over the batch API)."""
    return detect_entities_batch([page])[0]


def _spans_overlap(tier1_span: CandidateSpan, tier2_span: CandidateSpan) -> bool:
    """True when two spans share page + category and their char ranges overlap.

    The char-range predicate is the half-open any-overlap test
    ``resolve_span_bboxes`` uses (``a.start < b.end and b.start < a.end``),
    guarded by same ``page_number`` and same ``category`` so a Tier-2 span only
    merges into a Tier-1 span that covers the same PII on the same page.
    """
    return (
        tier1_span.page_number == tier2_span.page_number
        and tier1_span.category == tier2_span.category
        and tier1_span.start < tier2_span.end
        and tier2_span.start < tier1_span.end
    )


def _merge_group(
    page: PageModel,
    tier1_group: list[CandidateSpan],
    tier2_group: list[CandidateSpan],
) -> CandidateSpan:
    """Fold one connected component of overlapping spans into a single survivor.

    ``tier1_group`` is always non-empty here (only Tier-1-anchored components
    reach this helper) and is in input order, so ``tier1_group[0]`` is the
    earliest-input-order Tier-1 span; it supplies ``source_tier``/``confidence``
    (Tier 1 wins, R6). The survivor's range becomes the union
    ``[min(starts), max(ends))`` across every span in the component -- all of
    ``tier1_group`` plus every Tier-2 span that transitively overlaps any of
    them -- so two Tier-1 spans that both overlap one Tier-2 span fold into one
    canonical survivor instead of leaving the second Tier-1 span an unmerged
    duplicate. ``bboxes``/``text`` are recomputed over that union range via
    ``resolve_span_bboxes`` (one bbox per contributing word, never a hand-built
    union rectangle). When the union equals the primary span's own range the
    merge is a no-op and the original span is returned unchanged.
    """
    primary = tier1_group[0]
    all_spans = [*tier1_group, *tier2_group]
    merged_start = min(span.start for span in all_spans)
    merged_end = max(span.end for span in all_spans)
    if merged_start == primary.start and merged_end == primary.end:
        return primary
    return primary.model_copy(
        update={
            "start": merged_start,
            "end": merged_end,
            "bboxes": resolve_span_bboxes(page, merged_start, merged_end),
            "text": page.text[merged_start:merged_end],
        }
    )


class _UnionFind:
    """Minimal disjoint-set structure over ``range(size)``, path-compressed."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, index: int) -> int:
        while self._parent[index] != index:
            self._parent[index] = self._parent[self._parent[index]]
            index = self._parent[index]
        return index

    def union(self, first: int, second: int) -> None:
        root_first, root_second = self.find(first), self.find(second)
        if root_first != root_second:
            self._parent[root_second] = root_first


def _group_overlapping_spans(
    tier1_spans: list[CandidateSpan],
    tier2_spans: list[CandidateSpan],
) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
    """Union-find same-page/same-category overlapping spans into components.

    Edges only ever run between a Tier-1 and a Tier-2 span (via
    ``_spans_overlap``), but a component can still chain through multiple
    spans on either side -- e.g. two Tier-1 spans that both overlap one
    shared Tier-2 span end up in the same component. Returns
    ``(tier1_groups, tier2_groups)``, each mapping a component's root index to
    the (0-based, per-list) indices of its members; ``tier2_groups`` only
    contains components that also touch at least one Tier-1 span.
    """
    tier2_offset = len(tier1_spans)
    union_find = _UnionFind(tier2_offset + len(tier2_spans))
    for tier1_index, tier1_span in enumerate(tier1_spans):
        for tier2_index, tier2_span in enumerate(tier2_spans):
            if _spans_overlap(tier1_span, tier2_span):
                union_find.union(tier1_index, tier2_offset + tier2_index)

    tier1_groups: dict[int, list[int]] = {}
    for tier1_index in range(len(tier1_spans)):
        tier1_groups.setdefault(union_find.find(tier1_index), []).append(tier1_index)

    tier2_groups: dict[int, list[int]] = {}
    for tier2_index in range(len(tier2_spans)):
        root = union_find.find(tier2_offset + tier2_index)
        if root in tier1_groups:
            tier2_groups.setdefault(root, []).append(tier2_index)

    return tier1_groups, tier2_groups


def dedupe_tier2_against_tier1(
    page: PageModel,
    tier1_spans: list[CandidateSpan],
    tier2_spans: list[CandidateSpan],
) -> list[CandidateSpan]:
    """Merge overlapping Tier-2 spans into their Tier-1 counterparts (R6).

    Pure function over in-memory values -- no Presidio/spaCy call. Every
    connected component (see ``_group_overlapping_spans``) touching at least
    one Tier-1 span is folded into a single survivor via ``_merge_group`` --
    not just the first Tier-1 span to claim a shared Tier-2 span, so if two
    same-category Tier-1 spans both overlap one Tier-2 span (e.g. two adjacent
    Tier-1 regex hits under one wider NER span), both merge into one canonical
    survivor rather than leaving the second an unmerged duplicate. Tier-2
    spans with no Tier-1 overlap pass through unchanged, still stamped
    ``SourceTier.TIER_2``. Output order: (possibly-merged) Tier-1-anchored
    survivors first, ordered by the earliest-input-order Tier-1 span in their
    component, then the surviving (unconsumed) Tier-2 spans in input order.
    """
    tier1_groups, tier2_groups = _group_overlapping_spans(tier1_spans, tier2_spans)
    consumed_tier2 = {index for indices in tier2_groups.values() for index in indices}

    survivor_roots = sorted(tier1_groups, key=lambda root: min(tier1_groups[root]))
    result = [
        _merge_group(
            page,
            [tier1_spans[index] for index in tier1_groups[root]],
            [tier2_spans[index] for index in tier2_groups.get(root, [])],
        )
        for root in survivor_roots
    ]
    result.extend(tier2_spans[index] for index in range(len(tier2_spans)) if index not in consumed_tier2)
    return result
