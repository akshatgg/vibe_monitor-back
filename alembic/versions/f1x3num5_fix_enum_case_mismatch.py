"""Fix enum case mismatch - rename uppercase to lowercase

Revision ID: f1x3num5
Revises: 2623c4d56e6e
Create Date: 2025-12-28

Makes enum value renames idempotent - only renames if the uppercase value exists.
This handles cases where enums were created with lowercase values from the start.
"""

from alembic import op
from sqlalchemy import text


revision = "f1x3num5"
down_revision = "2623c4d56e6e"
branch_labels = None
depends_on = None


def rename_enum_value_if_exists(enum_name: str, old_value: str, new_value: str) -> None:
    """Rename an enum value only if the old value exists.

    This makes the migration idempotent for databases where the enum
    was already created with lowercase values.
    """
    op.execute(
        text(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    WHERE t.typname = '{enum_name}' AND e.enumlabel = '{old_value}'
                ) THEN
                    ALTER TYPE {enum_name} RENAME VALUE '{old_value}' TO '{new_value}';
                END IF;
            END $$;
        """)
    )


def upgrade():
    """Rename enum values from UPPERCASE to lowercase (idempotent)."""

    # turnstatus (may already be lowercase)
    rename_enum_value_if_exists("turnstatus", "PENDING", "pending")
    rename_enum_value_if_exists("turnstatus", "PROCESSING", "processing")
    rename_enum_value_if_exists("turnstatus", "COMPLETED", "completed")
    rename_enum_value_if_exists("turnstatus", "FAILED", "failed")

    # stepstatus (may already be lowercase)
    rename_enum_value_if_exists("stepstatus", "PENDING", "pending")
    rename_enum_value_if_exists("stepstatus", "RUNNING", "running")
    rename_enum_value_if_exists("stepstatus", "COMPLETED", "completed")
    rename_enum_value_if_exists("stepstatus", "FAILED", "failed")

    # steptype (may already be lowercase)
    rename_enum_value_if_exists("steptype", "TOOL_CALL", "tool_call")
    rename_enum_value_if_exists("steptype", "THINKING", "thinking")
    rename_enum_value_if_exists("steptype", "STATUS", "status")

    # jobstatus
    rename_enum_value_if_exists("jobstatus", "QUEUED", "queued")
    rename_enum_value_if_exists("jobstatus", "RUNNING", "running")
    rename_enum_value_if_exists("jobstatus", "WAITING_INPUT", "waiting_input")
    rename_enum_value_if_exists("jobstatus", "COMPLETED", "completed")
    rename_enum_value_if_exists("jobstatus", "FAILED", "failed")

    # role (MEMBER -> user, not member)
    rename_enum_value_if_exists("role", "OWNER", "owner")
    rename_enum_value_if_exists("role", "MEMBER", "user")

    # securityeventtype
    rename_enum_value_if_exists(
        "securityeventtype", "PROMPT_INJECTION", "prompt_injection"
    )
    rename_enum_value_if_exists("securityeventtype", "GUARD_DEGRADED", "guard_degraded")


def downgrade():
    """Revert to UPPERCASE enum values (idempotent)."""

    # turnstatus
    rename_enum_value_if_exists("turnstatus", "pending", "PENDING")
    rename_enum_value_if_exists("turnstatus", "processing", "PROCESSING")
    rename_enum_value_if_exists("turnstatus", "completed", "COMPLETED")
    rename_enum_value_if_exists("turnstatus", "failed", "FAILED")

    # stepstatus
    rename_enum_value_if_exists("stepstatus", "pending", "PENDING")
    rename_enum_value_if_exists("stepstatus", "running", "RUNNING")
    rename_enum_value_if_exists("stepstatus", "completed", "COMPLETED")
    rename_enum_value_if_exists("stepstatus", "failed", "FAILED")

    # steptype
    rename_enum_value_if_exists("steptype", "tool_call", "TOOL_CALL")
    rename_enum_value_if_exists("steptype", "thinking", "THINKING")
    rename_enum_value_if_exists("steptype", "status", "STATUS")

    # jobstatus
    rename_enum_value_if_exists("jobstatus", "queued", "QUEUED")
    rename_enum_value_if_exists("jobstatus", "running", "RUNNING")
    rename_enum_value_if_exists("jobstatus", "waiting_input", "WAITING_INPUT")
    rename_enum_value_if_exists("jobstatus", "completed", "COMPLETED")
    rename_enum_value_if_exists("jobstatus", "failed", "FAILED")

    # role
    rename_enum_value_if_exists("role", "owner", "OWNER")
    rename_enum_value_if_exists("role", "user", "MEMBER")

    # securityeventtype
    rename_enum_value_if_exists(
        "securityeventtype", "prompt_injection", "PROMPT_INJECTION"
    )
    rename_enum_value_if_exists("securityeventtype", "guard_degraded", "GUARD_DEGRADED")
