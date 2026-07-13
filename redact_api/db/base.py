"""Model imports for SQLModel metadata discovery.

Alembic autogenerate uses SQLModel.metadata. Importing this module registers all
table models by importing their modules, so keep new models listed here.
"""

from redact_api.models.activity_log import ActivityLog, ActivityLogArchive
from redact_api.models.document import Document
from redact_api.models.membership import Membership
from redact_api.models.organization import Organization
from redact_api.models.user import User

__all__ = [
    "ActivityLog",
    "ActivityLogArchive",
    "Document",
    "Membership",
    "Organization",
    "User",
]
