"""Add cascade delete to workspace foreign keys

Revision ID: be37ea21eb73
Revises: 4347b727b544
Create Date: 2026-01-02 09:32:47.171431

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "be37ea21eb73"
down_revision: Union[str, Sequence[str], None] = "4347b727b544"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# FK constraints that need ON DELETE CASCADE
FK_CONSTRAINTS = [
    (
        "aws_integrations",
        "aws_integrations_workspace_id_fkey",
        "workspace_id",
        "workspaces",
        "id",
    ),
    (
        "chat_sessions",
        "chat_sessions_workspace_id_fkey",
        "workspace_id",
        "workspaces",
        "id",
    ),
    (
        "datadog_integrations",
        "datadog_integrations_workspace_id_fkey",
        "workspace_id",
        "workspaces",
        "id",
    ),
    (
        "github_integrations",
        "github_integrations_workspace_id_fkey",
        "workspace_id",
        "workspaces",
        "id",
    ),
    (
        "grafana_integrations",
        "grafana_integrations_vm_workspace_id_fkey",
        "vm_workspace_id",
        "workspaces",
        "id",
    ),
    ("jobs", "jobs_vm_workspace_id_fkey", "vm_workspace_id", "workspaces", "id"),
    (
        "memberships",
        "memberships_workspace_id_fkey",
        "workspace_id",
        "workspaces",
        "id",
    ),
    (
        "newrelic_integrations",
        "newrelic_integrations_workspace_id_fkey",
        "workspace_id",
        "workspaces",
        "id",
    ),
    (
        "rate_limit_tracking",
        "rate_limit_tracking_workspace_id_fkey",
        "workspace_id",
        "workspaces",
        "id",
    ),
    (
        "security_events",
        "security_events_workspace_id_fkey",
        "workspace_id",
        "workspaces",
        "id",
    ),
    (
        "slack_installations",
        "slack_installations_workspace_id_fkey",
        "workspace_id",
        "workspaces",
        "id",
    ),
]


def upgrade() -> None:
    """Add ON DELETE CASCADE to workspace foreign keys."""
    for table, constraint, column, ref_table, ref_column in FK_CONSTRAINTS:
        # Drop existing constraint
        op.drop_constraint(constraint, table, type_="foreignkey")
        # Recreate with ON DELETE CASCADE
        op.create_foreign_key(
            constraint,
            table,
            ref_table,
            [column],
            [ref_column],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """Remove ON DELETE CASCADE from workspace foreign keys."""
    for table, constraint, column, ref_table, ref_column in FK_CONSTRAINTS:
        # Drop CASCADE constraint
        op.drop_constraint(constraint, table, type_="foreignkey")
        # Recreate without CASCADE (NO ACTION is default)
        op.create_foreign_key(
            constraint,
            table,
            ref_table,
            [column],
            [ref_column],
        )
