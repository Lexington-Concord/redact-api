"""add kratos_identity_id to app_user

Revision ID: ffac4fcfdc07
Revises: add_role_to_membership
Create Date: 2026-01-25 22:39:30.352069

"""
import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'ffac4fcfdc07'
down_revision = 'add_role_to_membership'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add kratos_identity_id column (nullable initially for existing users)
    op.add_column(
        'app_user',
        sa.Column('kratos_identity_id', postgresql.UUID(as_uuid=True), nullable=True)
    )

    # Create unique constraint to ensure one-to-one mapping
    op.create_unique_constraint(
        'uq_app_user_kratos_identity_id',
        'app_user',
        ['kratos_identity_id']
    )

    # Create index for faster lookups by kratos_identity_id
    op.create_index(
        'idx_app_user_kratos_identity_id',
        'app_user',
        ['kratos_identity_id']
    )


def downgrade() -> None:
    # Drop index first
    op.drop_index('idx_app_user_kratos_identity_id', table_name='app_user')

    # Drop unique constraint
    op.drop_constraint('uq_app_user_kratos_identity_id', 'app_user', type_='unique')

    # Drop column
    op.drop_column('app_user', 'kratos_identity_id')
