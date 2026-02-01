"""Add chat tables and job source column

Revision ID: c1h2a3t4
Revises: a9f8e7d6c5b4
Create Date: 2025-12-22 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c1h2a3t4"
down_revision: Union[str, Sequence[str], None] = "a9f8e7d6c5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------- Upgrade ----------

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())
    existing_columns = {
        "jobs": {c["name"] for c in inspector.get_columns("jobs")} if "jobs" in existing_tables else set(),
        "chat_sessions": {c["name"] for c in inspector.get_columns("chat_sessions")} if "chat_sessions" in existing_tables else set(),
        "chat_turns": {c["name"] for c in inspector.get_columns("chat_turns")} if "chat_turns" in existing_tables else set(),
        "turn_steps": {c["name"] for c in inspector.get_columns("turn_steps")} if "turn_steps" in existing_tables else set(),
    }
    existing_indexes = {
        t: {i["name"] for i in inspector.get_indexes(t)} if t in existing_tables else set()
        for t in ["chat_sessions", "chat_turns", "turn_steps"]
    }

    # ----- Enums (idempotent) -----
    for name, values in {
        "jobsource": "('slack','web','msteams')",
        "turnstatus": "('pending','processing','completed','failed')",
        "steptype": "('tool_call','thinking','status')",
        "stepstatus": "('pending','running','completed','failed')",
    }.items():
        op.execute(sa.text(f"""
            DO $$ BEGIN
                CREATE TYPE {name} AS ENUM {values};
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
        """))

    jobsource_enum = postgresql.ENUM("slack","web","msteams",name="jobsource",create_type=False)
    turnstatus_enum = postgresql.ENUM("pending","processing","completed","failed",name="turnstatus",create_type=False)
    steptype_enum = postgresql.ENUM("tool_call","thinking","status",name="steptype",create_type=False)
    stepstatus_enum = postgresql.ENUM("pending","running","completed","failed",name="stepstatus",create_type=False)

    # ----- jobs.source -----
    if "source" not in existing_columns.get("jobs", set()):
        op.add_column("jobs", sa.Column("source", jobsource_enum, nullable=False, server_default="slack"))

    # ----- chat_sessions -----
    if "chat_sessions" not in existing_tables:
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(255)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        existing_tables.add("chat_sessions")
        existing_indexes["chat_sessions"] = set()

    for name, cols in [
        ("idx_chat_sessions_workspace", ["workspace_id"]),
        ("idx_chat_sessions_user", ["user_id"]),
        ("idx_chat_sessions_workspace_user", ["workspace_id","user_id"]),
        ("idx_chat_sessions_created_at", ["created_at"]),
    ]:
        if name not in existing_indexes["chat_sessions"]:
            op.create_index(name, "chat_sessions", cols)
            existing_indexes["chat_sessions"].add(name)

    # ----- chat_turns -----
    if "chat_turns" not in existing_tables:
        op.create_table(
            "chat_turns",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("user_message", sa.Text(), nullable=False),
            sa.Column("final_response", sa.Text()),
            sa.Column("status", turnstatus_enum, nullable=False, server_default="pending"),
            sa.Column("job_id", sa.String()),
            sa.Column("feedback_score", sa.Integer()),
            sa.Column("feedback_comment", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        existing_tables.add("chat_turns")
        existing_indexes["chat_turns"] = set()

    for name, cols in [
        ("idx_chat_turns_session", ["session_id"]),
        ("idx_chat_turns_job", ["job_id"]),
        ("idx_chat_turns_status", ["status"]),
        ("idx_chat_turns_created_at", ["created_at"]),
    ]:
        if name not in existing_indexes["chat_turns"]:
            op.create_index(name, "chat_turns", cols)
            existing_indexes["chat_turns"].add(name)

    # ----- turn_steps -----
    if "turn_steps" not in existing_tables:
        op.create_table(
            "turn_steps",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("turn_id", sa.String(), nullable=False),
            sa.Column("step_type", steptype_enum, nullable=False),
            sa.Column("tool_name", sa.String(100)),
            sa.Column("content", sa.Text()),
            sa.Column("status", stepstatus_enum, nullable=False, server_default="pending"),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        existing_tables.add("turn_steps")
        existing_indexes["turn_steps"] = set()

    for name, cols in [
        ("idx_turn_steps_turn", ["turn_id"]),
        ("idx_turn_steps_turn_sequence", ["turn_id","sequence"]),
    ]:
        if name not in existing_indexes["turn_steps"]:
            op.create_index(name, "turn_steps", cols)
            existing_indexes["turn_steps"].add(name)


# ---------- Downgrade ----------

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    def drop_indexes(table, names):
        if table in existing_tables:
            existing = {i["name"] for i in inspector.get_indexes(table)}
            for n in names:
                if n in existing:
                    op.drop_index(n, table_name=table)

    drop_indexes("turn_steps", ["idx_turn_steps_turn_sequence","idx_turn_steps_turn"])
    if "turn_steps" in existing_tables:
        op.drop_table("turn_steps")

    drop_indexes("chat_turns", ["idx_chat_turns_created_at","idx_chat_turns_status","idx_chat_turns_job","idx_chat_turns_session"])
    if "chat_turns" in existing_tables:
        op.drop_table("chat_turns")

    drop_indexes("chat_sessions", ["idx_chat_sessions_created_at","idx_chat_sessions_workspace_user","idx_chat_sessions_user","idx_chat_sessions_workspace"])
    if "chat_sessions" in existing_tables:
        op.drop_table("chat_sessions")

    if "jobs" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("jobs")}
        if "source" in cols:
            op.drop_column("jobs", "source")

    for t in ["stepstatus","steptype","turnstatus","jobsource"]:
        op.execute(sa.text(f"DROP TYPE IF EXISTS {t}"))
