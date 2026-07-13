"""add role field to membership

Revision ID: add_role_to_membership
Revises: 2158c52d75b6
Create Date: 2026-01-09 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "add_role_to_membership"
down_revision = "2158c52d75b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add role field to membership table with data migration.

    1. Add role column with default value 'member'
    2. Set first member of each organization to 'owner' role
    3. Ensure all other members have 'member' role
    """
    # Create enum type (for PostgreSQL)
    membership_role_enum = sa.Enum(
        "owner", "admin", "member", name="membership_role", native_enum=False
    )
    membership_role_enum.create(op.get_bind(), checkfirst=True)

    # Add role column with default value
    op.add_column(
        "membership",
        sa.Column(
            "role",
            membership_role_enum,
            nullable=False,
            server_default="member",
        ),
    )

    # Data migration: Set first member of each org to OWNER
    # This query finds the earliest created member per organization
    # and sets their role to 'owner'
    # Uses database-agnostic window functions (SQL:2003 standard) for portability
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE membership
            SET role = 'owner'
            WHERE id IN (
                SELECT id FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY organization_id
                            ORDER BY created_at ASC
                        ) as rn
                    FROM membership
                ) ranked
                WHERE rn = 1
            )
            """
        )
    )


def downgrade() -> None:
    """Remove role field from membership table."""
    op.drop_column("membership", "role")

    # Drop enum type (for PostgreSQL)
    membership_role_enum = sa.Enum(
        "owner", "admin", "member", name="membership_role", native_enum=False
    )
    membership_role_enum.drop(op.get_bind(), checkfirst=True)
