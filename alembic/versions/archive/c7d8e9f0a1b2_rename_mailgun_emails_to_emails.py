"""Rename mailgun_emails table to emails

Revision ID: c7d8e9f0a1b2
Revises: a9f8e7d6c5b4
Create Date: 2025-12-26 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "a9f8e7d6c5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def index_exists(index_name: str, table_name: str) -> bool:
    """Check if an index exists on a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = inspector.get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def upgrade() -> None:
    """Rename mailgun_emails table and indexes to neutral 'emails' naming."""
    # Skip if already renamed (emails exists) or source table doesn't exist
    if table_exists("emails") or not table_exists("mailgun_emails"):
        return

    # Drop old indexes first if they exist (PostgreSQL requires this before table rename)
    if index_exists("idx_mailgun_emails_status", "mailgun_emails"):
        op.drop_index("idx_mailgun_emails_status", table_name="mailgun_emails")
    if index_exists("idx_mailgun_emails_sent_at", "mailgun_emails"):
        op.drop_index("idx_mailgun_emails_sent_at", table_name="mailgun_emails")
    if index_exists("idx_mailgun_emails_user", "mailgun_emails"):
        op.drop_index("idx_mailgun_emails_user", table_name="mailgun_emails")

    # Rename the table
    op.rename_table("mailgun_emails", "emails")

    # Create new indexes with neutral naming (if they don't exist)
    if not index_exists("idx_emails_user", "emails"):
        op.create_index("idx_emails_user", "emails", ["user_id"], unique=False)
    if not index_exists("idx_emails_sent_at", "emails"):
        op.create_index("idx_emails_sent_at", "emails", ["sent_at"], unique=False)
    if not index_exists("idx_emails_status", "emails"):
        op.create_index("idx_emails_status", "emails", ["status"], unique=False)


def downgrade() -> None:
    """Revert to mailgun_emails table naming."""
    # Drop new indexes
    op.drop_index("idx_emails_status", table_name="emails")
    op.drop_index("idx_emails_sent_at", table_name="emails")
    op.drop_index("idx_emails_user", table_name="emails")

    # Rename table back
    op.rename_table("emails", "mailgun_emails")

    # Recreate old indexes
    op.create_index(
        "idx_mailgun_emails_user", "mailgun_emails", ["user_id"], unique=False
    )
    op.create_index(
        "idx_mailgun_emails_sent_at", "mailgun_emails", ["sent_at"], unique=False
    )
    op.create_index(
        "idx_mailgun_emails_status", "mailgun_emails", ["status"], unique=False
    )
