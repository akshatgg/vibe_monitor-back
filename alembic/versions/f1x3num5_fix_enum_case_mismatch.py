"""Fix enum case mismatch - rename uppercase to lowercase

Revision ID: f1x3num5
Revises: 2623c4d56e6e
Create Date: 2025-12-28
"""

from alembic import op


revision = "f1x3num5"
down_revision = "2623c4d56e6e"
branch_labels = None
depends_on = None


def upgrade():
    """Rename enum values from UPPERCASE to lowercase."""

    # turnstatus
    op.execute("ALTER TYPE turnstatus RENAME VALUE 'PENDING' TO 'pending'")
    op.execute("ALTER TYPE turnstatus RENAME VALUE 'PROCESSING' TO 'processing'")
    op.execute("ALTER TYPE turnstatus RENAME VALUE 'COMPLETED' TO 'completed'")
    op.execute("ALTER TYPE turnstatus RENAME VALUE 'FAILED' TO 'failed'")

    # stepstatus
    op.execute("ALTER TYPE stepstatus RENAME VALUE 'PENDING' TO 'pending'")
    op.execute("ALTER TYPE stepstatus RENAME VALUE 'RUNNING' TO 'running'")
    op.execute("ALTER TYPE stepstatus RENAME VALUE 'COMPLETED' TO 'completed'")
    op.execute("ALTER TYPE stepstatus RENAME VALUE 'FAILED' TO 'failed'")

    # steptype
    op.execute("ALTER TYPE steptype RENAME VALUE 'TOOL_CALL' TO 'tool_call'")
    op.execute("ALTER TYPE steptype RENAME VALUE 'THINKING' TO 'thinking'")
    op.execute("ALTER TYPE steptype RENAME VALUE 'STATUS' TO 'status'")

    # jobstatus
    op.execute("ALTER TYPE jobstatus RENAME VALUE 'QUEUED' TO 'queued'")
    op.execute("ALTER TYPE jobstatus RENAME VALUE 'RUNNING' TO 'running'")
    op.execute("ALTER TYPE jobstatus RENAME VALUE 'WAITING_INPUT' TO 'waiting_input'")
    op.execute("ALTER TYPE jobstatus RENAME VALUE 'COMPLETED' TO 'completed'")
    op.execute("ALTER TYPE jobstatus RENAME VALUE 'FAILED' TO 'failed'")

    # role (MEMBER -> user, not member)
    op.execute("ALTER TYPE role RENAME VALUE 'OWNER' TO 'owner'")
    op.execute("ALTER TYPE role RENAME VALUE 'MEMBER' TO 'user'")

    # securityeventtype
    op.execute(
        "ALTER TYPE securityeventtype RENAME VALUE 'PROMPT_INJECTION' TO 'prompt_injection'"
    )
    op.execute(
        "ALTER TYPE securityeventtype RENAME VALUE 'GUARD_DEGRADED' TO 'guard_degraded'"
    )


def downgrade():
    """Revert to UPPERCASE enum values."""

    # turnstatus
    op.execute("ALTER TYPE turnstatus RENAME VALUE 'pending' TO 'PENDING'")
    op.execute("ALTER TYPE turnstatus RENAME VALUE 'processing' TO 'PROCESSING'")
    op.execute("ALTER TYPE turnstatus RENAME VALUE 'completed' TO 'COMPLETED'")
    op.execute("ALTER TYPE turnstatus RENAME VALUE 'failed' TO 'FAILED'")

    # stepstatus
    op.execute("ALTER TYPE stepstatus RENAME VALUE 'pending' TO 'PENDING'")
    op.execute("ALTER TYPE stepstatus RENAME VALUE 'running' TO 'RUNNING'")
    op.execute("ALTER TYPE stepstatus RENAME VALUE 'completed' TO 'COMPLETED'")
    op.execute("ALTER TYPE stepstatus RENAME VALUE 'failed' TO 'FAILED'")

    # steptype
    op.execute("ALTER TYPE steptype RENAME VALUE 'tool_call' TO 'TOOL_CALL'")
    op.execute("ALTER TYPE steptype RENAME VALUE 'thinking' TO 'THINKING'")
    op.execute("ALTER TYPE steptype RENAME VALUE 'status' TO 'STATUS'")

    # jobstatus
    op.execute("ALTER TYPE jobstatus RENAME VALUE 'queued' TO 'QUEUED'")
    op.execute("ALTER TYPE jobstatus RENAME VALUE 'running' TO 'RUNNING'")
    op.execute("ALTER TYPE jobstatus RENAME VALUE 'waiting_input' TO 'WAITING_INPUT'")
    op.execute("ALTER TYPE jobstatus RENAME VALUE 'completed' TO 'COMPLETED'")
    op.execute("ALTER TYPE jobstatus RENAME VALUE 'failed' TO 'FAILED'")

    # role
    op.execute("ALTER TYPE role RENAME VALUE 'owner' TO 'OWNER'")
    op.execute("ALTER TYPE role RENAME VALUE 'user' TO 'MEMBER'")

    # securityeventtype
    op.execute(
        "ALTER TYPE securityeventtype RENAME VALUE 'prompt_injection' TO 'PROMPT_INJECTION'"
    )
    op.execute(
        "ALTER TYPE securityeventtype RENAME VALUE 'guard_degraded' TO 'GUARD_DEGRADED'"
    )
