"""Migrate AWS integration to STS role-based authentication

Revision ID: abc123def456
Revises: iqx5rixmd6xw
Create Date: 2025-10-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd963cf8403c6'
down_revision: Union[str, Sequence[str], None] = 'iqx5rixmd6xw'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to use STS role-based authentication."""

    # Step 1: Add new columns (nullable first to allow existing rows)
    op.add_column('aws_integrations', sa.Column('role_arn', sa.String(), nullable=True))
    op.add_column('aws_integrations', sa.Column('external_id', sa.String(), nullable=True))
    op.add_column('aws_integrations', sa.Column('session_token', sa.String(), nullable=True))
    op.add_column('aws_integrations', sa.Column('credentials_expiration', sa.DateTime(timezone=True), nullable=True))

    # Step 2: Delete all existing AWS integrations (since we're changing the auth model completely)
    # Users will need to re-add their AWS integrations with the new role-based method
    op.execute('DELETE FROM aws_integrations')

    # Step 3: Rename old columns to keep them temporarily
    op.alter_column('aws_integrations', 'aws_access_key_id',
                    new_column_name='old_aws_access_key_id')
    op.alter_column('aws_integrations', 'aws_secret_access_key',
                    new_column_name='old_aws_secret_access_key')

    # Step 4: Add new columns with same names
    op.add_column('aws_integrations', sa.Column('access_key_id', sa.String(), nullable=True))
    op.add_column('aws_integrations', sa.Column('secret_access_key', sa.String(), nullable=True))

    # Step 5: Now make required columns non-nullable (safe since table is empty)
    op.alter_column('aws_integrations', 'role_arn', nullable=False)
    op.alter_column('aws_integrations', 'access_key_id', nullable=False)
    op.alter_column('aws_integrations', 'secret_access_key', nullable=False)
    op.alter_column('aws_integrations', 'session_token', nullable=False)
    op.alter_column('aws_integrations', 'credentials_expiration', nullable=False)

    # Step 6: Drop old columns
    op.drop_column('aws_integrations', 'old_aws_access_key_id')
    op.drop_column('aws_integrations', 'old_aws_secret_access_key')


def downgrade() -> None:
    """Downgrade schema back to access key-based authentication."""

    # This will delete all data since the auth models are incompatible
    op.execute('DELETE FROM aws_integrations')

    # Remove new columns
    op.drop_column('aws_integrations', 'credentials_expiration')
    op.drop_column('aws_integrations', 'session_token')
    op.drop_column('aws_integrations', 'external_id')
    op.drop_column('aws_integrations', 'role_arn')

    # Rename back
    op.alter_column('aws_integrations', 'access_key_id',
                    new_column_name='aws_access_key_id')
    op.alter_column('aws_integrations', 'secret_access_key',
                    new_column_name='aws_secret_access_key')
