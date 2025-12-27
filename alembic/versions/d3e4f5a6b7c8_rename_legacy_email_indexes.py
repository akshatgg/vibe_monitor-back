"""Rename legacy mailgun email indexes

Revision ID: d3e4f5a6b7c8
Revises: c7d8e9f0a1b2
Create Date: 2025-12-27 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def index_exists(index_name: str, table_name: str) -> bool:
    """Check if an index exists on a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = inspector.get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def constraint_exists(constraint_name: str, table_name: str) -> bool:
    """Check if a constraint exists on a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    constraints = inspector.get_pk_constraint(table_name)
    if constraints and constraints.get("name") == constraint_name:
        return True
    # Also check unique constraints
    unique_constraints = inspector.get_unique_constraints(table_name)
    return any(c["name"] == constraint_name for c in unique_constraints)


def upgrade() -> None:
    """Rename legacy mailgun indexes to neutral email naming."""
    # Rename primary key constraint if it still has the old name
    if constraint_exists("mailgun_emails_pkey", "emails"):
        op.execute(
            "ALTER TABLE emails RENAME CONSTRAINT mailgun_emails_pkey TO emails_pkey"
        )

    # Rename the email_type index if it still has the old name
    if index_exists("idx_mailgun_emails_email_type", "emails"):
        op.execute(
            "ALTER INDEX idx_mailgun_emails_email_type RENAME TO idx_emails_email_type"
        )


def downgrade() -> None:
    """Revert to legacy mailgun index naming."""
    # Rename back to old names
    if constraint_exists("emails_pkey", "emails"):
        op.execute(
            "ALTER TABLE emails RENAME CONSTRAINT emails_pkey TO mailgun_emails_pkey"
        )

    if index_exists("idx_emails_email_type", "emails"):
        op.execute(
            "ALTER INDEX idx_emails_email_type RENAME TO idx_mailgun_emails_email_type"
        )
