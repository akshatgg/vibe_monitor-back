"""Normalize ALL enum values to UPPERCASE - FINAL PAST-AWARE MIGRATION

Revision ID: u1p2p3e4r5
Revises: b612ffbe12b8
Create Date: 2026-01-30

This is the LAST migration that handles historical enum inconsistencies.
After this point, all code and future migrations assume UPPERCASE enums.

Behavior:
- Renames lowercase enum labels to UPPERCASE (idempotent)
- Handles mixed state (some uppercase, some lowercase)
- Safe to run multiple times
- Does NOT create/drop enum types
"""

from alembic import op
from sqlalchemy import text

revision = "u1p2p3e4r5"
down_revision = "b612ffbe12b8"
branch_labels = None
depends_on = None


def rename_if_exists(enum_name: str, old_val: str, new_val: str) -> None:
    """Rename enum value only if old_val exists (idempotent)."""
    op.execute(text(f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_enum e
                JOIN pg_type t ON t.oid = e.enumtypid
                WHERE t.typname = '{enum_name}' AND e.enumlabel = '{old_val}'
            ) THEN
                ALTER TYPE {enum_name} RENAME VALUE '{old_val}' TO '{new_val}';
            END IF;
        END $$;
    """))


def upgrade():
    """Convert all lowercase enum values to UPPERCASE."""

    # role
    rename_if_exists("role", "owner", "OWNER")
    rename_if_exists("role", "user", "USER")
    rename_if_exists("role", "member", "USER")  # Legacy value

    # jobstatus
    rename_if_exists("jobstatus", "queued", "QUEUED")
    rename_if_exists("jobstatus", "running", "RUNNING")
    rename_if_exists("jobstatus", "waiting_input", "WAITING_INPUT")
    rename_if_exists("jobstatus", "completed", "COMPLETED")
    rename_if_exists("jobstatus", "failed", "FAILED")

    # jobsource
    rename_if_exists("jobsource", "slack", "SLACK")
    rename_if_exists("jobsource", "web", "WEB")
    rename_if_exists("jobsource", "msteams", "MSTEAMS")

    # feedbacksource
    rename_if_exists("feedbacksource", "web", "WEB")
    rename_if_exists("feedbacksource", "slack", "SLACK")

    # turnstatus
    rename_if_exists("turnstatus", "pending", "PENDING")
    rename_if_exists("turnstatus", "processing", "PROCESSING")
    rename_if_exists("turnstatus", "completed", "COMPLETED")
    rename_if_exists("turnstatus", "failed", "FAILED")

    # steptype
    rename_if_exists("steptype", "tool_call", "TOOL_CALL")
    rename_if_exists("steptype", "thinking", "THINKING")
    rename_if_exists("steptype", "status", "STATUS")

    # stepstatus
    rename_if_exists("stepstatus", "pending", "PENDING")
    rename_if_exists("stepstatus", "running", "RUNNING")
    rename_if_exists("stepstatus", "completed", "COMPLETED")
    rename_if_exists("stepstatus", "failed", "FAILED")

    # invitationstatus
    rename_if_exists("invitationstatus", "pending", "PENDING")
    rename_if_exists("invitationstatus", "accepted", "ACCEPTED")
    rename_if_exists("invitationstatus", "declined", "DECLINED")
    rename_if_exists("invitationstatus", "expired", "EXPIRED")

    # deploymentstatus
    rename_if_exists("deploymentstatus", "pending", "PENDING")
    rename_if_exists("deploymentstatus", "in_progress", "IN_PROGRESS")
    rename_if_exists("deploymentstatus", "success", "SUCCESS")
    rename_if_exists("deploymentstatus", "failed", "FAILED")
    rename_if_exists("deploymentstatus", "cancelled", "CANCELLED")

    # deploymentsource
    rename_if_exists("deploymentsource", "manual", "MANUAL")
    rename_if_exists("deploymentsource", "webhook", "WEBHOOK")
    rename_if_exists("deploymentsource", "github_actions", "GITHUB_ACTIONS")
    rename_if_exists("deploymentsource", "github_deployments", "GITHUB_DEPLOYMENTS")
    rename_if_exists("deploymentsource", "argocd", "ARGOCD")
    rename_if_exists("deploymentsource", "jenkins", "JENKINS")

    # llmprovider
    rename_if_exists("llmprovider", "vibemonitor", "VIBEMONITOR")
    rename_if_exists("llmprovider", "openai", "OPENAI")
    rename_if_exists("llmprovider", "azure_openai", "AZURE_OPENAI")
    rename_if_exists("llmprovider", "gemini", "GEMINI")

    # llmconfigstatus
    rename_if_exists("llmconfigstatus", "active", "ACTIVE")
    rename_if_exists("llmconfigstatus", "error", "ERROR")
    rename_if_exists("llmconfigstatus", "unconfigured", "UNCONFIGURED")

    # securityeventtype
    rename_if_exists("securityeventtype", "prompt_injection", "PROMPT_INJECTION")
    rename_if_exists("securityeventtype", "guard_degraded", "GUARD_DEGRADED")

    # plantype
    rename_if_exists("plantype", "free", "FREE")
    rename_if_exists("plantype", "pro", "PRO")

    # subscriptionstatus
    rename_if_exists("subscriptionstatus", "active", "ACTIVE")
    rename_if_exists("subscriptionstatus", "past_due", "PAST_DUE")
    rename_if_exists("subscriptionstatus", "canceled", "CANCELED")
    rename_if_exists("subscriptionstatus", "incomplete", "INCOMPLETE")
    rename_if_exists("subscriptionstatus", "trialing", "TRIALING")


def downgrade():
    """Revert to lowercase enum values (not recommended)."""
    # Reverse all renames - UPPERCASE back to lowercase
    # ... (reverse of upgrade)
    pass  # Downgrade intentionally minimal - going back is not desired
