"""add_subscription_schedule_support

Revision ID: c07a6a7a69ae
Revises: 9055f8216e50
Create Date: 2026-02-03 08:41:33.556281

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c07a6a7a69ae'
down_revision: Union[str, Sequence[str], None] = '9055f8216e50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Add subscription schedule support columns."""

    op.add_column('subscriptions',
        sa.Column('subscription_schedule_id', sa.String(255), nullable=True)
    )
    op.add_column('subscriptions',
        sa.Column('pending_billable_service_count', sa.Integer(), nullable=True)
    )
    op.add_column('subscriptions',
        sa.Column('pending_change_date', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema - Remove subscription schedule support columns."""

    op.drop_column('subscriptions', 'pending_change_date')
    op.drop_column('subscriptions', 'pending_billable_service_count')
    op.drop_column('subscriptions', 'subscription_schedule_id')

