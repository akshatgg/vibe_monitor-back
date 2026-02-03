"""add_subscription_schedule_support

Revision ID: c07a6a7a69ae
Revises: 9055f8216e50
Create Date: 2026-02-03 08:41:33.556281

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

logger = logging.getLogger(__name__)


# revision identifiers, used by Alembic.
revision: str = 'c07a6a7a69ae'
down_revision: Union[str, Sequence[str], None] = '9055f8216e50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add subscription schedule support columns."""

    # Get connection to check column existence
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Check if subscriptions table exists
    if 'subscriptions' in inspector.get_table_names():
        existing_columns = [col['name'] for col in inspector.get_columns('subscriptions')]

        # Add subscription_schedule_id if it doesn't exist
        if 'subscription_schedule_id' not in existing_columns:
            op.add_column('subscriptions',
                sa.Column('subscription_schedule_id', sa.String(255), nullable=True)
            )
            logger.info("Added subscription_schedule_id column")
        else:
            logger.info("subscription_schedule_id column already exists, skipping")

        # Add pending_billable_service_count if it doesn't exist
        if 'pending_billable_service_count' not in existing_columns:
            op.add_column('subscriptions',
                sa.Column('pending_billable_service_count', sa.Integer(), nullable=True)
            )
            logger.info("Added pending_billable_service_count column")
        else:
            logger.info("pending_billable_service_count column already exists, skipping")

        # Add pending_change_date if it doesn't exist
        if 'pending_change_date' not in existing_columns:
            op.add_column('subscriptions',
                sa.Column('pending_change_date', sa.DateTime(timezone=True), nullable=True)
            )
            logger.info("Added pending_change_date column")
        else:
            logger.info("pending_change_date column already exists, skipping")
    else:
        logger.warning("subscriptions table not found, skipping migration")


def downgrade() -> None:
    """Downgrade schema - Remove subscription schedule support columns."""

    # Get connection to check column existence
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'subscriptions' in inspector.get_table_names():
        existing_columns = [col['name'] for col in inspector.get_columns('subscriptions')]

        # Remove columns if they exist
        if 'subscription_schedule_id' in existing_columns:
            op.drop_column('subscriptions', 'subscription_schedule_id')
            logger.info("Removed subscription_schedule_id column")

        if 'pending_billable_service_count' in existing_columns:
            op.drop_column('subscriptions', 'pending_billable_service_count')
            logger.info("Removed pending_billable_service_count column")

        if 'pending_change_date' in existing_columns:
            op.drop_column('subscriptions', 'pending_change_date')
            logger.info("Removed pending_change_date column")
