"""Unit tests for the TaskIQ pipeline metrics (redact-api#8).

The label shapes must match the worker template's metrics_mw contract so the two
services' dashboards line up: lifecycle counters carry (environment, task_name);
the duration histogram and the in-progress gauge carry task_name only.
"""

from __future__ import annotations

from redact_api.core.metrics import (
    task_duration_seconds,
    tasks_completed_total,
    tasks_failed_total,
    tasks_in_progress,
    tasks_started_total,
)


class TestTaskiqMetricLabels:
    def test_lifecycle_counters_carry_environment_and_task_name(self) -> None:
        for counter in (tasks_started_total, tasks_completed_total, tasks_failed_total):
            assert counter._labelnames == ("environment", "task_name")

    def test_duration_histogram_carries_task_name_only(self) -> None:
        assert task_duration_seconds._labelnames == ("task_name",)

    def test_in_progress_gauge_carries_task_name_only(self) -> None:
        assert tasks_in_progress._labelnames == ("task_name",)

    def test_counters_are_incrementable(self) -> None:
        # Smoke: labelling with the documented dimensions produces a usable child.
        tasks_started_total.labels(environment="test", task_name="ingest_job").inc()
        tasks_in_progress.labels(task_name="ingest_job").inc()
        tasks_in_progress.labels(task_name="ingest_job").dec()
        task_duration_seconds.labels(task_name="ingest_job").observe(0.01)
