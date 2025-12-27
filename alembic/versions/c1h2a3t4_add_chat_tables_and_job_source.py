"""Add chat tables and job source column

Revision ID: c1h2a3t4
Revises: a9f8e7d6c5b4
Create Date: 2025-12-22 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c1h2a3t4"
down_revision: Union[str, Sequence[str], None] = "a9f8e7d6c5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add chat tables and job source column."""
    # Create enums using raw SQL with DO block to handle "already exists" gracefully
    # This is more robust than checkfirst=True for handling partial migrations
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE jobsource AS ENUM ('slack', 'web', 'msteams');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE turnstatus AS ENUM ('pending', 'processing', 'completed', 'failed');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE steptype AS ENUM ('tool_call', 'thinking', 'status');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE stepstatus AS ENUM ('pending', 'running', 'completed', 'failed');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)

    # Define enum types for column definitions (create_type=False since we created them above)
    jobsource_enum = postgresql.ENUM(
        "slack", "web", "msteams", name="jobsource", create_type=False
    )
    turnstatus_enum = postgresql.ENUM(
        "pending",
        "processing",
        "completed",
        "failed",
        name="turnstatus",
        create_type=False,
    )
    steptype_enum = postgresql.ENUM(
        "tool_call", "thinking", "status", name="steptype", create_type=False
    )
    stepstatus_enum = postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "failed",
        name="stepstatus",
        create_type=False,
    )

    # Add source column to jobs table
    op.add_column(
        "jobs",
        sa.Column(
            "source",
            jobsource_enum,
            nullable=False,
            server_default="slack",  # Default to slack for backward compatibility
        ),
    )

    # Create chat_sessions table
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for chat_sessions
    op.create_index("idx_chat_sessions_workspace", "chat_sessions", ["workspace_id"])
    op.create_index("idx_chat_sessions_user", "chat_sessions", ["user_id"])
    op.create_index(
        "idx_chat_sessions_workspace_user", "chat_sessions", ["workspace_id", "user_id"]
    )
    op.create_index("idx_chat_sessions_created_at", "chat_sessions", ["created_at"])

    # Create chat_turns table
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("final_response", sa.Text(), nullable=True),
        sa.Column(
            "status",
            turnstatus_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("feedback_score", sa.Integer(), nullable=True),
        sa.Column("feedback_comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for chat_turns
    op.create_index("idx_chat_turns_session", "chat_turns", ["session_id"])
    op.create_index("idx_chat_turns_job", "chat_turns", ["job_id"])
    op.create_index("idx_chat_turns_status", "chat_turns", ["status"])
    op.create_index("idx_chat_turns_created_at", "chat_turns", ["created_at"])

    # Create turn_steps table
    op.create_table(
        "turn_steps",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("step_type", steptype_enum, nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column(
            "status",
            stepstatus_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for turn_steps
    op.create_index("idx_turn_steps_turn", "turn_steps", ["turn_id"])
    op.create_index(
        "idx_turn_steps_turn_sequence", "turn_steps", ["turn_id", "sequence"]
    )


def downgrade() -> None:
    """Remove chat tables and job source column."""
    # Drop turn_steps indexes and table
    op.drop_index("idx_turn_steps_turn_sequence", table_name="turn_steps")
    op.drop_index("idx_turn_steps_turn", table_name="turn_steps")
    op.drop_table("turn_steps")

    # Drop chat_turns indexes and table
    op.drop_index("idx_chat_turns_created_at", table_name="chat_turns")
    op.drop_index("idx_chat_turns_status", table_name="chat_turns")
    op.drop_index("idx_chat_turns_job", table_name="chat_turns")
    op.drop_index("idx_chat_turns_session", table_name="chat_turns")
    op.drop_table("chat_turns")

    # Drop chat_sessions indexes and table
    op.drop_index("idx_chat_sessions_created_at", table_name="chat_sessions")
    op.drop_index("idx_chat_sessions_workspace_user", table_name="chat_sessions")
    op.drop_index("idx_chat_sessions_user", table_name="chat_sessions")
    op.drop_index("idx_chat_sessions_workspace", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    # Drop source column from jobs
    op.drop_column("jobs", "source")

    # Drop enums (using IF EXISTS for safety)
    op.execute("DROP TYPE IF EXISTS stepstatus")
    op.execute("DROP TYPE IF EXISTS steptype")
    op.execute("DROP TYPE IF EXISTS turnstatus")
    op.execute("DROP TYPE IF EXISTS jobsource")
