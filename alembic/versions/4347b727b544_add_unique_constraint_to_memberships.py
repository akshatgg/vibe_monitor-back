"""Add unique constraint to memberships

Revision ID: 4347b727b544
Revises: 91a2a1e77256
Create Date: 2025-12-31 01:31:22.640074

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4347b727b544"
down_revision: Union[str, Sequence[str], None] = "91a2a1e77256"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema (idempotent)."""
    inspector = sa.inspect(op.get_bind())
    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("memberships")}

    if "uq_membership_user_workspace" not in existing_constraints:
        op.create_unique_constraint(
            "uq_membership_user_workspace", "memberships", ["user_id", "workspace_id"]
        )
    else:
        print(
            "Unique constraint 'uq_membership_user_workspace' already exists on 'memberships' table. Skipping."
        )


def downgrade() -> None:
    """Downgrade schema (idempotent)."""
    inspector = sa.inspect(op.get_bind())
    existing_constraints = {c["name"] for c in inspector.get_unique_constraints("memberships")}

    if "uq_membership_user_workspace" in existing_constraints:
        op.drop_constraint("uq_membership_user_workspace", "memberships", type_="unique")
    else:
        print(
            "Unique constraint 'uq_membership_user_workspace' does not exist on 'memberships' table. Skipping."
        )
