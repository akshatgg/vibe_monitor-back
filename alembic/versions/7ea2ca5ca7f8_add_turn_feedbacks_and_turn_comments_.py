"""Add turn_feedbacks and turn_comments tables

Revision ID: 7ea2ca5ca7f8
Revises: c1dd6edf73ca
Create Date: 2025-12-30 21:58:17.837586

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM


# revision identifiers, used by Alembic.
revision: str = "7ea2ca5ca7f8"
down_revision: Union[str, Sequence[str], None] = "c1dd6edf73ca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    # Create feedbacksource enum type (idempotent)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE feedbacksource AS ENUM ('web', 'slack');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # ----- turn_feedbacks table -----
    if "turn_feedbacks" not in existing_tables:
        op.create_table(
            "turn_feedbacks",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("turn_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("slack_user_id", sa.String(255), nullable=True),
            sa.Column("is_positive", sa.Boolean(), nullable=False),
            sa.Column(
                "source",
                ENUM("web", "slack", name="feedbacksource", create_type=False),
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
        existing_tables.add("turn_feedbacks")
    else:
        print("  ⊘ Table 'turn_feedbacks' already exists, skipping...")

    # Create indexes for turn_feedbacks
    existing_feedbacks_indexes = {i["name"] for i in inspector.get_indexes("turn_feedbacks")} if "turn_feedbacks" in existing_tables else set()

    feedbacks_indexes = [
        ("idx_turn_feedbacks_turn_id", ["turn_id"]),
        ("idx_turn_feedbacks_user_id", ["user_id"]),
        ("idx_turn_feedbacks_slack_user_id", ["slack_user_id"]),
    ]

    for idx_name, columns in feedbacks_indexes:
        if idx_name not in existing_feedbacks_indexes:
            op.create_index(idx_name, "turn_feedbacks", columns)
            existing_feedbacks_indexes.add(idx_name)
        else:
            print(f"  ⊘ Index '{idx_name}' already exists, skipping...")

    # ----- turn_comments table -----
    if "turn_comments" not in existing_tables:
        op.create_table(
            "turn_comments",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("turn_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("slack_user_id", sa.String(255), nullable=True),
            sa.Column("comment", sa.Text(), nullable=False),
            sa.Column(
                "source",
                ENUM("web", "slack", name="feedbacksource", create_type=False),
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
        existing_tables.add("turn_comments")
    else:
        print("  ⊘ Table 'turn_comments' already exists, skipping...")

    # Create indexes for turn_comments
    existing_comments_indexes = {i["name"] for i in inspector.get_indexes("turn_comments")} if "turn_comments" in existing_tables else set()

    comments_indexes = [
        ("idx_turn_comments_turn_id", ["turn_id"]),
        ("idx_turn_comments_user_id", ["user_id"]),
        ("idx_turn_comments_slack_user_id", ["slack_user_id"]),
        ("idx_turn_comments_created_at", ["created_at"]),
    ]

    for idx_name, columns in comments_indexes:
        if idx_name not in existing_comments_indexes:
            op.create_index(idx_name, "turn_comments", columns)
            existing_comments_indexes.add(idx_name)
        else:
            print(f"  ⊘ Index '{idx_name}' already exists, skipping...")


def downgrade() -> None:
    """Downgrade schema."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    # ----- Drop turn_comments table -----
    if "turn_comments" in existing_tables:
        existing_comments_indexes = {i["name"] for i in inspector.get_indexes("turn_comments")}

        for idx_name in [
            "idx_turn_comments_created_at",
            "idx_turn_comments_slack_user_id",
            "idx_turn_comments_user_id",
            "idx_turn_comments_turn_id",
        ]:
            if idx_name in existing_comments_indexes:
                op.drop_index(idx_name, table_name="turn_comments")

        op.drop_table("turn_comments")
    else:
        print("  ⊘ Table 'turn_comments' does not exist, skipping...")

    # ----- Drop turn_feedbacks table -----
    if "turn_feedbacks" in existing_tables:
        existing_feedbacks_indexes = {i["name"] for i in inspector.get_indexes("turn_feedbacks")}

        for idx_name in [
            "idx_turn_feedbacks_slack_user_id",
            "idx_turn_feedbacks_user_id",
            "idx_turn_feedbacks_turn_id",
        ]:
            if idx_name in existing_feedbacks_indexes:
                op.drop_index(idx_name, table_name="turn_feedbacks")

        op.drop_table("turn_feedbacks")
    else:
        print("  ⊘ Table 'turn_feedbacks' does not exist, skipping...")

    # Drop enum type (if exists)
    op.execute("DROP TYPE IF EXISTS feedbacksource")
