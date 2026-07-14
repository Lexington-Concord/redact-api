"""Model imports for SQLModel metadata discovery.

Alembic autogenerate uses SQLModel.metadata. Importing this module registers all
table models by importing their modules, so keep new models listed here.
"""

from redact_api.models.activity_log import ActivityLog, ActivityLogArchive
from redact_api.models.audit_entry import AuditEntry
from redact_api.models.disposition import Disposition
from redact_api.models.document import Document
from redact_api.models.membership import Membership
from redact_api.models.organization import Organization
from redact_api.models.page import Page
from redact_api.models.redaction_job import RedactionJob
from redact_api.models.span import Span
from redact_api.models.user import User

__all__ = [
    "ActivityLog",
    "ActivityLogArchive",
    "AuditEntry",
    "Disposition",
    "Document",
    "Membership",
    "Organization",
    "Page",
    "RedactionJob",
    "Span",
    "User",
]
