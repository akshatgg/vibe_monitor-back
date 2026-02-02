"""Remove feedback columns from chat_turns

Revision ID: 91a2a1e77256
Revises: 7ea2ca5ca7f8
Create Date: 2025-12-30 22:15:00.000000

Makes column drops idempotent - only drops if the column exists.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "91a2a1e77256"
down_revision: Union[str, Sequence[str], None] = "7ea2ca5ca7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove deprecated feedback columns from chat_turns (idempotent)."""
    inspector = sa.inspect(op.get_bind())
    existing_columns = {col["name"] for col in inspector.get_columns("chat_turns")}

    if "feedback_score" in existing_columns:
        op.drop_column("chat_turns", "feedback_score")
    else:
        print("Column 'feedback_score' does not exist in 'chat_turns', skipping.")

    if "feedback_comment" in existing_columns:
        op.drop_column("chat_turns", "feedback_comment")
    else:
        print("Column 'feedback_comment' does not exist in 'chat_turns', skipping.")


def downgrade() -> None:
    """Re-add feedback columns to chat_turns (idempotent)."""
    inspector = sa.inspect(op.get_bind())
    existing_columns = {col["name"] for col in inspector.get_columns("chat_turns")}

    if "feedback_score" not in existing_columns:
        op.add_column(
            "chat_turns", sa.Column("feedback_score", sa.Integer(), nullable=True)
        )
    else:
        print("Column 'feedback_score' already exists in 'chat_turns', skipping.")

    if "feedback_comment" not in existing_columns:
        op.add_column(
            "chat_turns", sa.Column("feedback_comment", sa.Text(), nullable=True)
        )
    else:
        print("Column 'feedback_comment' already exists in 'chat_turns', skipping.")
