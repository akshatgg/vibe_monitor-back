"""Add Slack support to chat_sessions

Revision ID: s1a2c3k4
Revises: 9a7c81a8c684
Create Date: 2025-12-27
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "s1a2c3k4"
down_revision: Union[str, Sequence[str], None] = "9a7c81a8c684"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------- Upgrade ----------

def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table = "chat_sessions"

    # Fetch existing schema once
    existing_columns = {c["name"] for c in inspector.get_columns(table)}
    existing_indexes = {i["name"] for i in inspector.get_indexes(table)}

    # ----- Columns to add -----
    columns_to_add = [
        (
            "source",
            sa.Column(
                "source",
                sa.Enum("slack", "web", "msteams", name="jobsource", create_type=False),
                nullable=False,
                server_default="web",
            ),
        ),
        ("slack_team_id", sa.Column("slack_team_id", sa.String(), nullable=True)),
        ("slack_channel_id", sa.Column("slack_channel_id", sa.String(), nullable=True)),
        ("slack_thread_ts", sa.Column("slack_thread_ts", sa.String(), nullable=True)),
        ("slack_user_id", sa.Column("slack_user_id", sa.String(), nullable=True)),
    ]

    for name, column in columns_to_add:
        if name not in existing_columns:
            op.add_column(table, column)
            existing_columns.add(name)
        else:
            print(f"  ⊘ Column '{name}' already exists in '{table}', skipping...")

    # ----- Alter user_id -----
    op.alter_column(
        table,
        "user_id",
        existing_type=sa.String(),
        nullable=True,
    )

    # ----- Index on source -----
    source_index = "idx_chat_sessions_source"
    if source_index not in existing_indexes:
        op.create_index(source_index, table, ["source"])
        existing_indexes.add(source_index)
    else:
        print(f"  ⊘ Index '{source_index}' already exists, skipping...")

    # ----- Partial unique index for Slack threads (Postgres) -----
    slack_index = "idx_chat_sessions_slack_thread"
    if slack_index not in existing_indexes:
        op.execute(sa.text("""
            CREATE UNIQUE INDEX idx_chat_sessions_slack_thread
            ON chat_sessions (slack_team_id, slack_channel_id, slack_thread_ts)
            WHERE source = 'slack'
        """))
        existing_indexes.add(slack_index)
    else:
        print(f"  ⊘ Index '{slack_index}' already exists, skipping...")


# ---------- Downgrade ----------

def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table = "chat_sessions"

    existing_columns = {c["name"] for c in inspector.get_columns(table)}
    existing_indexes = {i["name"] for i in inspector.get_indexes(table)}

    # Drop partial index if exists
    slack_index = "idx_chat_sessions_slack_thread"
    if slack_index in existing_indexes:
        op.drop_index(slack_index, table_name=table)

    # Drop source index if exists
    source_index = "idx_chat_sessions_source"
    if source_index in existing_indexes:
        op.drop_index(source_index, table_name=table)

    # Make user_id non-nullable again
    op.alter_column(
        table,
        "user_id",
        existing_type=sa.String(),
        nullable=False,
    )

    # Drop columns safely (reverse order)
    for col in [
        "slack_user_id",
        "slack_thread_ts",
        "slack_channel_id",
        "slack_team_id",
        "source",
    ]:
        if col in existing_columns:
            op.drop_column(table, col)
