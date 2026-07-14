"""Unit tests for the pure (DB-free) core of ``redact_api.services.jobs_service``.

The DB-touching projection query and disposition-batch persistence are exercised
end-to-end in ``tests/integration/test_jobs_api.py``; here we pin the pure pieces:
the DB-row -> ``ApprovedSpan`` coercion (and its 422-on-malformed-shape contract),
the verb -> action mappings, the re-disposition "needs change" diff, and the
request-schema validation (including the ``extra="forbid"`` rejection of a
client-supplied ``reviewer_id``).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from redact_api.models.audit_entry import AuditAction
from redact_api.models.disposition import DispositionAction
from redact_api.services.jobs_service import (
    AUDIT_ACTION_BY_VERB,
    DISPOSITION_ACTION_BY_VERB,
    DispositionBatchRequest,
    EditItem,
    bboxes_differ,
    build_approved_span,
    disposition_needs_change,
)


class TestBuildApprovedSpan:
    def test_coerces_valid_bboxes(self) -> None:
        span = build_approved_span(page_number=1, bboxes=[[1.0, 2.0, 3.0, 4.0]], text="John Doe")
        assert span.page_number == 1
        assert span.bboxes == [(1.0, 2.0, 3.0, 4.0)]
        assert span.text == "John Doe"

    def test_allows_empty_bboxes(self) -> None:
        span = build_approved_span(page_number=2, bboxes=[], text="x")
        assert span.bboxes == []

    def test_coerces_multiple_bboxes(self) -> None:
        span = build_approved_span(page_number=1, bboxes=[[1, 2, 3, 4], [5, 6, 7, 8]], text="y")
        assert span.bboxes == [(1.0, 2.0, 3.0, 4.0), (5.0, 6.0, 7.0, 8.0)]

    def test_wrong_arity_bbox_raises(self) -> None:
        with pytest.raises(ValidationError):
            build_approved_span(page_number=1, bboxes=[[1.0, 2.0, 3.0]], text="x")

    def test_non_numeric_bbox_raises(self) -> None:
        with pytest.raises(ValidationError):
            build_approved_span(page_number=1, bboxes=[["a", "b", "c", "d"]], text="x")

    def test_non_list_bbox_element_raises(self) -> None:
        with pytest.raises(ValidationError):
            build_approved_span(page_number=1, bboxes=["not-a-bbox"], text="x")


class TestVerbActionMappings:
    def test_disposition_actions(self) -> None:
        assert DISPOSITION_ACTION_BY_VERB == {
            "approve": DispositionAction.APPROVED,
            "reject": DispositionAction.REJECTED,
            "edit": DispositionAction.APPROVED,
            "add_manual_span": DispositionAction.APPROVED,
        }

    def test_audit_actions(self) -> None:
        assert AUDIT_ACTION_BY_VERB == {
            "approve": AuditAction.APPROVED,
            "reject": AuditAction.REJECTED,
            "edit": AuditAction.EDITED,
            "add_manual_span": AuditAction.MANUAL_SPAN_ADDED,
        }


class TestDispositionNeedsChange:
    def test_no_existing_disposition_needs_change(self) -> None:
        assert disposition_needs_change(None, DispositionAction.APPROVED) is True

    def test_same_action_is_noop(self) -> None:
        assert disposition_needs_change(DispositionAction.APPROVED, DispositionAction.APPROVED) is False

    def test_different_action_needs_change(self) -> None:
        assert disposition_needs_change(DispositionAction.APPROVED, DispositionAction.REJECTED) is True

    def test_edit_with_same_text_is_noop(self) -> None:
        assert (
            disposition_needs_change(
                DispositionAction.APPROVED,
                DispositionAction.APPROVED,
                is_edit=True,
                current_text="same",
                new_text="same",
            )
            is False
        )

    def test_edit_with_new_text_needs_change(self) -> None:
        assert (
            disposition_needs_change(
                DispositionAction.APPROVED,
                DispositionAction.APPROVED,
                is_edit=True,
                current_text="old",
                new_text="new",
            )
            is True
        )


class TestBboxesDiffer:
    def test_identical_bboxes_no_diff(self) -> None:
        assert bboxes_differ([[1.0, 2.0, 3.0, 4.0]], [(1.0, 2.0, 3.0, 4.0)]) is False

    def test_different_bboxes_diff(self) -> None:
        assert bboxes_differ([[1.0, 2.0, 3.0, 4.0]], [(5.0, 6.0, 7.0, 8.0)]) is True

    def test_different_count_diff(self) -> None:
        assert bboxes_differ([[1.0, 2.0, 3.0, 4.0]], [(1.0, 2.0, 3.0, 4.0), (5.0, 6.0, 7.0, 8.0)]) is True

    def test_empty_vs_empty_no_diff(self) -> None:
        assert bboxes_differ([], []) is False


class TestEditItemSchema:
    def test_bboxes_optional_defaults_to_none(self) -> None:
        item = EditItem.model_validate({"verb": "edit", "span_id": uuid4(), "text": "corrected"})
        assert item.bboxes is None

    def test_accepts_bboxes(self) -> None:
        item = EditItem.model_validate(
            {"verb": "edit", "span_id": uuid4(), "text": "corrected", "bboxes": [[1.0, 2.0, 3.0, 4.0]]}
        )
        assert item.bboxes == [(1.0, 2.0, 3.0, 4.0)]


class TestDispositionBatchRequestSchema:
    def test_parses_all_four_verbs(self) -> None:
        span_id = uuid4()
        request = DispositionBatchRequest.model_validate(
            {
                "items": [
                    {"verb": "approve", "span_id": str(span_id)},
                    {"verb": "reject", "span_id": str(span_id)},
                    {"verb": "edit", "span_id": str(span_id), "text": "corrected"},
                    {
                        "verb": "add_manual_span",
                        "page_number": 1,
                        "bboxes": [[1.0, 2.0, 3.0, 4.0]],
                        "text": "manual",
                        "category": "PERSON",
                    },
                ]
            }
        )
        assert [item.verb for item in request.items] == ["approve", "reject", "edit", "add_manual_span"]

    def test_rejects_client_supplied_reviewer_id(self) -> None:
        with pytest.raises(ValidationError):
            DispositionBatchRequest.model_validate(
                {"items": [{"verb": "approve", "span_id": str(uuid4()), "reviewer_id": str(uuid4())}]}
            )

    def test_edit_requires_text(self) -> None:
        with pytest.raises(ValidationError):
            DispositionBatchRequest.model_validate({"items": [{"verb": "edit", "span_id": str(uuid4())}]})

    def test_add_manual_span_requires_fields(self) -> None:
        with pytest.raises(ValidationError):
            DispositionBatchRequest.model_validate({"items": [{"verb": "add_manual_span", "text": "x"}]})

    def test_unknown_verb_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DispositionBatchRequest.model_validate({"items": [{"verb": "delete", "span_id": str(uuid4())}]})
