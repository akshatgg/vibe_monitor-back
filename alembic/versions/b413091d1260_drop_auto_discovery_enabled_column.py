"""drop_auto_discovery_enabled_column

Revision ID: b413091d1260
Revises: f8f458133678
Create Date: 2026-01-04 11:33:11.171425

Removes the auto_discovery_enabled column from environments table.
This feature was never implemented and is being removed to simplify the schema.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b413091d1260"
down_revision: Union[str, Sequence[str], None] = "f8f458133678"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop auto_discovery_enabled column from environments table."""
    inspector = sa.inspect(op.get_bind())
    table_name = "environments"

    # Check if column exists before dropping
    if table_name in inspector.get_table_names():
        existing_columns = {c["name"] for c in inspector.get_columns(table_name)}
        if "auto_discovery_enabled" in existing_columns:
            op.drop_column(table_name, "auto_discovery_enabled")
        else:
            print(f"  ⊘ Column 'auto_discovery_enabled' does not exist in '{table_name}', skipping...")
    else:
        print(f"  ⊘ Table '{table_name}' does not exist, skipping...")


def downgrade() -> None:
    """Re-add auto_discovery_enabled column to environments table."""
    inspector = sa.inspect(op.get_bind())
    table_name = "environments"

    # Check if column already exists before adding
    if table_name in inspector.get_table_names():
        existing_columns = {c["name"] for c in inspector.get_columns(table_name)}
        if "auto_discovery_enabled" not in existing_columns:
            op.add_column(
                table_name,
                sa.Column(
                    "auto_discovery_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default="true",
                ),
            )
        else:
            print(f"  ⊘ Column 'auto_discovery_enabled' already exists in '{table_name}', skipping...")
    else:
        print(f"  ⊘ Table '{table_name}' does not exist, skipping...")
