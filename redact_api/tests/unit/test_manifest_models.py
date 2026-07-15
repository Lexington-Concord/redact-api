"""Pure Pydantic round-trip tests for the export-manifest contract (redact-api#9).

No database, no storage -- these exercise ``redact_api.manifest.models`` in isolation:
field presence, canonical-JSON determinism, that a disposition's stored digest is never
the raw text, and that an empty ``lifecycle_events`` list serializes cleanly.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from redact_api.manifest.models import (
    ExportManifest,
    ManifestDisposition,
    ManifestLifecycleEvent,
)
from redact_api.models.audit_entry import AuditAction

JOB_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")
DOCUMENT_ID = UUID("bbbbbbbb-0000-4000-8000-000000000002")
SPAN_ID = UUID("cccccccc-0000-4000-8000-000000000003")
REVIEWER_ID = UUID("dddddddd-0000-4000-8000-000000000004")
FIXED_TS = datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


def _disposition() -> ManifestDisposition:
    return ManifestDisposition(
        span_id=SPAN_ID,
        action=AuditAction.APPROVED,
        category="PERSON",
        text_hash=hashlib.sha256(b"john doe").hexdigest(),
        reviewer_id=REVIEWER_ID,
        sequence=1,
        created_at=FIXED_TS,
    )


def _lifecycle_event(action: AuditAction) -> ManifestLifecycleEvent:
    return ManifestLifecycleEvent(action=action, reviewer_id=REVIEWER_ID, created_at=FIXED_TS)


def _manifest(*, lifecycle_events: list[ManifestLifecycleEvent] | None = None) -> ExportManifest:
    events = [_lifecycle_event(AuditAction.APPLY_STARTED)] if lifecycle_events is None else lifecycle_events
    summary = {"verdict": "pass", "checks": [{"check_type": "text_layer", "passed": True, "pages_checked": 1}]}
    return ExportManifest(
        job_id=JOB_ID,
        document_id=DOCUMENT_ID,
        original_sha256=hashlib.sha256(b"original").hexdigest(),
        redacted_sha256=hashlib.sha256(b"redacted").hexdigest(),
        dispositions=[_disposition()],
        lifecycle_events=events,
        verify_summary=summary,
        entry_count=2,
        audit_chain_head="f" * 64,
        audit_chain_verified=True,
        generated_at=FIXED_TS,
    )


class TestManifestFieldPresence:
    def test_all_top_level_fields_present(self) -> None:
        manifest = _manifest()
        assert manifest.job_id == JOB_ID
        assert manifest.document_id == DOCUMENT_ID
        assert manifest.entry_count == 2
        assert manifest.audit_chain_head == "f" * 64
        assert manifest.audit_chain_verified is True
        assert manifest.generated_at == FIXED_TS
        assert manifest.verify_summary["verdict"] == "pass"

    def test_disposition_and_lifecycle_shapes(self) -> None:
        manifest = _manifest()
        disposition = manifest.dispositions[0]
        assert disposition.span_id == SPAN_ID
        assert disposition.action == AuditAction.APPROVED
        assert manifest.lifecycle_events[0].action == AuditAction.APPLY_STARTED
        assert manifest.lifecycle_events[0].reviewer_id == REVIEWER_ID


class TestCanonicalJson:
    def test_serialization_is_deterministic(self) -> None:
        manifest = _manifest()
        assert manifest.model_dump_json() == manifest.model_dump_json()

    def test_round_trip_preserves_values(self) -> None:
        manifest = _manifest()
        rebuilt = ExportManifest.model_validate_json(manifest.model_dump_json())
        assert rebuilt == manifest

    def test_empty_lifecycle_events_serializes_cleanly(self) -> None:
        manifest = _manifest(lifecycle_events=[])
        rebuilt = ExportManifest.model_validate_json(manifest.model_dump_json())
        assert rebuilt.lifecycle_events == []


class TestNoRawText:
    def test_text_hash_is_a_digest_not_raw_text(self) -> None:
        raw = "John Doe"
        disposition = ManifestDisposition(
            span_id=SPAN_ID,
            action=AuditAction.APPROVED,
            category="PERSON",
            text_hash=hashlib.sha256(raw.encode()).hexdigest(),
            reviewer_id=REVIEWER_ID,
            sequence=1,
            created_at=FIXED_TS,
        )
        assert disposition.text_hash != raw
        assert len(disposition.text_hash) == 64
        assert int(disposition.text_hash, 16) >= 0  # valid hex

    def test_text_hash_may_be_none_for_lifecycle_style_rows(self) -> None:
        disposition = ManifestDisposition(
            span_id=SPAN_ID,
            action=AuditAction.APPROVED,
            category="PERSON",
            text_hash=None,
            reviewer_id=REVIEWER_ID,
            sequence=1,
            created_at=FIXED_TS,
        )
        assert disposition.text_hash is None
