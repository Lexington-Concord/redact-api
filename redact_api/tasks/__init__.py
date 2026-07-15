"""Async ingest/detect/apply task package for the redaction pipeline (redact-api#8).

Importing this package registers every ``@broker.task`` with the broker singleton, so
the worker entrypoint (``redact_api.tasks.worker``) and the API seam both trigger
registration simply by importing it.

Deliberately imports the *submodules* (not each submodule's ``@broker.task`` function,
e.g. NOT ``from redact_api.tasks.apply_job import apply_job``): each task module's
top-level name is the same as its task function's name, so re-exporting the function
here would rebind the package attribute ``redact_api.tasks.apply_job`` from the
submodule to the task object -- shadowing the submodule and breaking any direct
submodule access (e.g. ``from redact_api.tasks import apply_job as apply_job_module``
for monkeypatching in tests). Callers that need the task object import it from its
submodule directly (``from redact_api.tasks.apply_job import apply_job``), as
``api/jobs.py`` already does.
"""

from __future__ import annotations

from redact_api.tasks import apply_job, detect_job, ingest_job  # noqa: F401
