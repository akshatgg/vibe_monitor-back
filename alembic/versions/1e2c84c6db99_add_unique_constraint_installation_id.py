"""add_unique_constraint_installation_id

Revision ID: 1e2c84c6db99
Revises: 886ef6687692
Create Date: 2026-01-14 15:27:19.867452

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = "1e2c84c6db99"
down_revision: Union[str, Sequence[str], None] = "886ef6687692"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add unique constraint on github_integrations.installation_id.

    First removes any duplicate rows (keeping most recent by created_at),
    then adds the unique constraint to prevent future duplicates.
    """
    conn = op.get_bind()

    # Find and log duplicates
    duplicates_check = conn.execute(
        text("""
            SELECT installation_id, COUNT(*) as count,
                   array_agg(id ORDER BY created_at DESC) as ids,
                   array_agg(workspace_id) as workspace_ids,
                   array_agg(github_username) as usernames,
                   array_agg(created_at::text ORDER BY created_at DESC) as created_dates
            FROM github_integrations
            GROUP BY installation_id
            HAVING COUNT(*) > 1
        """)
    )

    duplicates = duplicates_check.fetchall()
    if duplicates:
        print(f"\nFound {len(duplicates)} installation_ids with duplicates:")
        for row in duplicates:
            print(
                f"  installation_id={row[0]}: {row[1]} rows\n"
                f"    Workspaces: {row[3]}\n"
                f"    GitHub users: {row[4]}\n"
                f"    Created dates: {row[5][:2]}... (keeping first/newest)"
            )

    # Delete duplicates using window function (safer)
    # Keeps the row with the most recent created_at for each installation_id
    result = conn.execute(
        text("""
            WITH duplicates AS (
                SELECT id,
                       installation_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY installation_id
                           ORDER BY created_at DESC
                       ) as rn
                FROM github_integrations
            )
            DELETE FROM github_integrations
            WHERE id IN (
                SELECT id FROM duplicates WHERE rn > 1
            )
        """)
    )

    # Get affected rows count from result
    affected_rows = result.rowcount if hasattr(result, "rowcount") else 0
    if affected_rows > 0:
        print(
            f"Deleted {affected_rows} duplicate row(s), keeping newest for each installation_id"
        )
    else:
        print("No duplicates found to delete")

    # Add unique constraint on installation_id (if it doesn't already exist)
    constraint_exists = conn.execute(
        text("""
            SELECT 1 FROM pg_constraint
            WHERE conname = 'uq_github_integrations_installation_id'
        """)
    ).fetchone()

    if constraint_exists:
        print(
            "Unique constraint uq_github_integrations_installation_id already exists, skipping"
        )
    else:
        op.create_unique_constraint(
            "uq_github_integrations_installation_id",
            "github_integrations",
            ["installation_id"],
        )
        print("Added unique constraint on github_integrations.installation_id")


def downgrade() -> None:
    """Remove unique constraint on github_integrations.installation_id."""
    op.drop_constraint(
        "uq_github_integrations_installation_id", "github_integrations", type_="unique"
    )
