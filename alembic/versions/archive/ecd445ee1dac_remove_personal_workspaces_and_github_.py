"""remove_personal_workspaces_and_github_user_oauth

Revision ID: ecd445ee1dac
Revises: 1e2c84c6db99
Create Date: 2026-01-20 05:42:25.159436

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ecd445ee1dac'
down_revision: Union[str, Sequence[str], None] = '1e2c84c6db99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove 'type' column from workspaces and github_user_oauth table."""
    from sqlalchemy import text

    # Get inspector to check what exists
    inspector = sa.inspect(op.get_bind())

    # Step 1: Drop the 'type' column from workspaces table if it exists
    workspace_columns = [col["name"] for col in inspector.get_columns("workspaces")]
    if "type" in workspace_columns:
        print("  → Dropping 'type' column from workspaces table...")
        op.drop_column("workspaces", "type")
    else:
        print("  ⊘ Column 'type' does not exist in 'workspaces' table, skipping...")

    # Step 3: Drop the WorkspaceType enum if it exists
    # Check if the enum type exists in PostgreSQL
    result = op.get_bind().execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'workspacetype')")
    )
    enum_exists = result.scalar()

    if enum_exists:
        print("  → Dropping WorkspaceType enum...")
        op.execute(text("DROP TYPE workspacetype"))
    else:
        print("  ⊘ Enum 'workspacetype' does not exist, skipping...")

    # Step 4: Drop github_user_oauth table if it exists
    table_name = "github_user_oauth"
    existing_tables = set(inspector.get_table_names())

    # Drop index if it exists
    if table_name in existing_tables:
        existing_indexes = {i["name"] for i in inspector.get_indexes(table_name)}
        idx_name = "idx_github_user_oauth_user"
        if idx_name in existing_indexes:
            print(f"  → Dropping index '{idx_name}'...")
            op.drop_index(idx_name, table_name=table_name)
        else:
            print(f"  ⊘ Index '{idx_name}' does not exist, skipping...")

    # Drop table if it exists
    if table_name in existing_tables:
        print(f"  → Dropping table '{table_name}'...")
        op.drop_table(table_name)
    else:
        print(f"  ⊘ Table '{table_name}' does not exist, skipping...")


def downgrade() -> None:
    """Restore 'type' column to workspaces and github_user_oauth table schema."""
    from sqlalchemy import text

    # Get inspector to check what exists
    inspector = sa.inspect(op.get_bind())

    # Step 1: Recreate github_user_oauth table if it doesn't exist
    table_name = "github_user_oauth"
    existing_tables = set(inspector.get_table_names())

    if table_name not in existing_tables:
        print(f"  → Creating table '{table_name}'...")
        op.create_table(
            table_name,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("github_user_id", sa.String(), nullable=False),
            sa.Column("github_username", sa.String(), nullable=False),
            sa.Column("access_token", sa.String(), nullable=False),
            sa.Column("scopes", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create index
        idx_name = "idx_github_user_oauth_user"
        print(f"  → Creating index '{idx_name}'...")
        op.create_index(idx_name, table_name, ["user_id"], unique=True)
    else:
        print(f"  ⊘ Table '{table_name}' already exists, skipping...")

    # Step 2: Create the WorkspaceType enum if it doesn't exist
    result = op.get_bind().execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'workspacetype')")
    )
    enum_exists = result.scalar()

    if not enum_exists:
        print("  → Creating WorkspaceType enum...")
        workspacetype_enum = sa.Enum("personal", "team", name="workspacetype")
        workspacetype_enum.create(op.get_bind(), checkfirst=True)
    else:
        print("  ⊘ Enum 'workspacetype' already exists, skipping...")

    # Step 3: Add 'type' column back to workspaces with default 'team'
    workspace_columns = [col["name"] for col in inspector.get_columns("workspaces")]

    if "type" not in workspace_columns:
        print("  → Adding 'type' column to workspaces table...")
        op.add_column(
            "workspaces",
            sa.Column(
                "type",
                sa.Enum("personal", "team", name="workspacetype", create_type=False),
                nullable=False,
                server_default="team",
            ),
        )
    else:
        print("  ⊘ Column 'type' already exists in 'workspaces' table, skipping...")
