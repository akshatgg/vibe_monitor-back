"""Add turn_feedbacks and turn_comments tables

Revision ID: 7ea2ca5ca7f8
Revises: c1dd6edf73ca
Create Date: 2025-12-30 21:58:17.837586

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7ea2ca5ca7f8"
down_revision: Union[str, Sequence[str], None] = "c1dd6edf73ca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create feedbacksource enum type (if not exists)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE feedbacksource AS ENUM ('web', 'slack');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Create turn_feedbacks table
    op.create_table(
        "turn_feedbacks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("slack_user_id", sa.String(255), nullable=True),
        sa.Column("is_positive", sa.Boolean(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("web", "slack", name="feedbacksource", create_type=False),
            nullable=False,
            server_default="web",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_id", "user_id", name="uq_turn_feedback_user"),
        sa.UniqueConstraint(
            "turn_id", "slack_user_id", name="uq_turn_feedback_slack_user"
        ),
    )
    op.create_index("idx_turn_feedbacks_turn_id", "turn_feedbacks", ["turn_id"])
    op.create_index("idx_turn_feedbacks_user_id", "turn_feedbacks", ["user_id"])
    op.create_index(
        "idx_turn_feedbacks_slack_user_id", "turn_feedbacks", ["slack_user_id"]
    )

    # Create turn_comments table
    op.create_table(
        "turn_comments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("slack_user_id", sa.String(255), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("web", "slack", name="feedbacksource", create_type=False),
            nullable=False,
            server_default="web",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_turn_comments_turn_id", "turn_comments", ["turn_id"])
    op.create_index("idx_turn_comments_user_id", "turn_comments", ["user_id"])
    op.create_index(
        "idx_turn_comments_slack_user_id", "turn_comments", ["slack_user_id"]
    )
    op.create_index("idx_turn_comments_created_at", "turn_comments", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop turn_comments table
    op.drop_index("idx_turn_comments_created_at", table_name="turn_comments")
    op.drop_index("idx_turn_comments_slack_user_id", table_name="turn_comments")
    op.drop_index("idx_turn_comments_user_id", table_name="turn_comments")
    op.drop_index("idx_turn_comments_turn_id", table_name="turn_comments")
    op.drop_table("turn_comments")

    # Drop turn_feedbacks table
    op.drop_index("idx_turn_feedbacks_slack_user_id", table_name="turn_feedbacks")
    op.drop_index("idx_turn_feedbacks_user_id", table_name="turn_feedbacks")
    op.drop_index("idx_turn_feedbacks_turn_id", table_name="turn_feedbacks")
    op.drop_table("turn_feedbacks")

    # Drop enum type (if exists)
    op.execute("DROP TYPE IF EXISTS feedbacksource")
