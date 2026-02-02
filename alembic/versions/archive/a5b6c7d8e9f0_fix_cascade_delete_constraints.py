"""Fix cascade delete constraints for slack_integration and user foreign keys

Revision ID: a5b6c7d8e9f0
Revises: 1dc79f90d2d4
Create Date: 2026-01-28 12:00:00.000000

Updates foreign key constraints to use ON DELETE CASCADE for:
- jobs.slack_integration_id -> slack_installations.id
- security_events.slack_integration_id -> slack_installations.id
- memberships.user_id -> users.id
- workspace_invitations.inviter_id -> users.id
- workspace_invitations.invitee_id -> users.id
- chat_files.uploaded_by -> users.id

This enables workspace and user deletion to cascade properly without FK violations.
"""

from typing import Sequence, Union

from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, Sequence[str], None] = "1dc79f90d2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# FK constraints to update: (table, constraint_name, column, ref_table, ref_column)
CASCADE_FKS = [
    (
        "jobs",
        "jobs_slack_integration_id_fkey",
        "slack_integration_id",
        "slack_installations",
        "id",
    ),
    (
        "security_events",
        "security_events_slack_integration_id_fkey",
        "slack_integration_id",
        "slack_installations",
        "id",
    ),
    ("memberships", "memberships_user_id_fkey", "user_id", "users", "id"),
    ("workspace_invitations", "fk_invitation_inviter", "inviter_id", "users", "id"),
    ("workspace_invitations", "fk_invitation_invitee", "invitee_id", "users", "id"),
    ("chat_files", "chat_files_uploaded_by_fkey", "uploaded_by", "users", "id"),
]


def constraint_exists(constraint_name: str, table_name: str) -> bool:
    """Check if a constraint exists on a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    foreign_keys = inspector.get_foreign_keys(table_name)
    return any(fk["name"] == constraint_name for fk in foreign_keys)


def upgrade() -> None:
    """Update FK constraints to use ON DELETE CASCADE."""
    for table, constraint, column, ref_table, ref_column in CASCADE_FKS:
        if constraint_exists(constraint, table):
            op.drop_constraint(constraint, table, type_="foreignkey")
            print(f"  ✓ Dropped constraint '{constraint}' from '{table}'")
        else:
            print(
                f"  ⊘ Constraint '{constraint}' does not exist on '{table}', skipping drop..."
            )

        op.create_foreign_key(
            constraint,
            table,
            ref_table,
            [column],
            [ref_column],
            ondelete="CASCADE",
        )
        print(
            f"  ✓ Created constraint '{constraint}' on '{table}' with ON DELETE CASCADE"
        )


def downgrade() -> None:
    """Revert FK constraints to NO ACTION (default)."""
    for table, constraint, column, ref_table, ref_column in CASCADE_FKS:
        if constraint_exists(constraint, table):
            op.drop_constraint(constraint, table, type_="foreignkey")
            print(f"  ✓ Dropped constraint '{constraint}' from '{table}'")
        else:
            print(
                f"  ⊘ Constraint '{constraint}' does not exist on '{table}', skipping drop..."
            )

        op.create_foreign_key(
            constraint,
            table,
            ref_table,
            [column],
            [ref_column],
        )
        print(
            f"  ✓ Created constraint '{constraint}' on '{table}' with default (NO ACTION)"
        )
