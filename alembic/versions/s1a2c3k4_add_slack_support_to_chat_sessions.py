"""Add Slack support to chat_sessions

Revision ID: s1a2c3k4
Revises: 9a7c81a8c684
Create Date: 2025-12-27

Adds source and Slack-specific columns to chat_sessions table to support
unified conversation model for both Web and Slack.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "s1a2c3k4"
down_revision: Union[str, Sequence[str], None] = "9a7c81a8c684"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Slack support columns to chat_sessions."""
    # Add source column with default 'web' for existing records
    op.add_column(
        "chat_sessions",
        sa.Column(
            "source",
            sa.Enum("slack", "web", "msteams", name="jobsource", create_type=False),
            nullable=False,
            server_default="web",
        ),
    )

    # Add Slack-specific columns (all nullable for web sessions)
    op.add_column(
        "chat_sessions",
        sa.Column("slack_team_id", sa.String(), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("slack_channel_id", sa.String(), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("slack_thread_ts", sa.String(), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("slack_user_id", sa.String(), nullable=True),
    )

    # Make user_id nullable (Slack users aren't in our users table)
    op.alter_column(
        "chat_sessions",
        "user_id",
        existing_type=sa.String(),
        nullable=True,
    )

    # Add index on source
    op.create_index(
        "idx_chat_sessions_source",
        "chat_sessions",
        ["source"],
    )

    # Add unique partial index for Slack threads
    # This ensures one session per Slack thread
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX idx_chat_sessions_slack_thread
            ON chat_sessions (slack_team_id, slack_channel_id, slack_thread_ts)
            WHERE source = 'slack'
            """
        )
    )


def downgrade() -> None:
    """Remove Slack support from chat_sessions."""
    # Drop the partial unique index
    op.drop_index("idx_chat_sessions_slack_thread", table_name="chat_sessions")

    # Drop the source index
    op.drop_index("idx_chat_sessions_source", table_name="chat_sessions")

    # Make user_id non-nullable again (will fail if any NULL values exist)
    op.alter_column(
        "chat_sessions",
        "user_id",
        existing_type=sa.String(),
        nullable=False,
    )

    # Drop Slack columns
    op.drop_column("chat_sessions", "slack_user_id")
    op.drop_column("chat_sessions", "slack_thread_ts")
    op.drop_column("chat_sessions", "slack_channel_id")
    op.drop_column("chat_sessions", "slack_team_id")
    op.drop_column("chat_sessions", "source")
