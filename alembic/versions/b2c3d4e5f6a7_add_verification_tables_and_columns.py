"""add_verification_tables_and_columns

Add codebase_contexts and code_facts tables for the verification system.
Add verification columns (gap_fingerprint, resolution_status, verification_verdict,
verification_evidence) to review_logging_gaps and review_metrics_gaps.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    gap_resolution_status = sa.Enum(
        "OPEN", "RESOLVED", "ACKNOWLEDGED", name="gapresolutionstatus"
    )
    verification_verdict = sa.Enum(
        "GENUINE", "FALSE_ALARM", "COVERED_GLOBALLY", name="verificationverdict"
    )
    gap_resolution_status.create(op.get_bind(), checkfirst=True)
    verification_verdict.create(op.get_bind(), checkfirst=True)

    # ========== codebase_contexts table ==========
    op.create_table(
        "codebase_contexts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("repo_full_name", sa.String(255), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("infrastructure_files", sa.JSON(), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_codebase_contexts_workspace", "codebase_contexts", ["workspace_id"]
    )
    op.create_index(
        "idx_codebase_contexts_repo", "codebase_contexts", ["repo_full_name"]
    )
    op.create_index(
        "idx_codebase_contexts_workspace_repo",
        "codebase_contexts",
        ["workspace_id", "repo_full_name"],
    )

    # ========== code_facts table ==========
    op.create_table(
        "code_facts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("repository_id", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("facts_json", sa.JSON(), nullable=False),
        sa.Column("language", sa.String(50), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["parsed_repositories.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_code_facts_repository", "code_facts", ["repository_id"])
    op.create_index(
        "idx_code_facts_repo_path", "code_facts", ["repository_id", "file_path"]
    )
    op.create_index(
        "idx_code_facts_content_hash",
        "code_facts",
        ["repository_id", "content_hash"],
    )

    # ========== Add service_id to parsed_repositories for cascade delete ==========
    op.add_column(
        "parsed_repositories",
        sa.Column("service_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_parsed_repositories_service",
        "parsed_repositories",
        "services",
        ["service_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "idx_parsed_repositories_service", "parsed_repositories", ["service_id"]
    )

    # ========== Add verification columns to review_logging_gaps ==========
    op.add_column(
        "review_logging_gaps",
        sa.Column("gap_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "review_logging_gaps",
        sa.Column("resolution_status", gap_resolution_status, nullable=True),
    )
    op.add_column(
        "review_logging_gaps",
        sa.Column("resolved_in_review_id", sa.String(), nullable=True),
    )
    op.add_column(
        "review_logging_gaps",
        sa.Column("verification_verdict", verification_verdict, nullable=True),
    )
    op.add_column(
        "review_logging_gaps",
        sa.Column("verification_evidence", sa.JSON(), nullable=True),
    )
    op.create_foreign_key(
        "fk_logging_gaps_resolved_review",
        "review_logging_gaps",
        "service_reviews",
        ["resolved_in_review_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_review_logging_gaps_fingerprint",
        "review_logging_gaps",
        ["gap_fingerprint"],
    )
    op.create_index(
        "idx_review_logging_gaps_resolution",
        "review_logging_gaps",
        ["resolution_status"],
    )

    # ========== Add verification columns to review_metrics_gaps ==========
    op.add_column(
        "review_metrics_gaps",
        sa.Column("gap_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "review_metrics_gaps",
        sa.Column("resolution_status", gap_resolution_status, nullable=True),
    )
    op.add_column(
        "review_metrics_gaps",
        sa.Column("resolved_in_review_id", sa.String(), nullable=True),
    )
    op.add_column(
        "review_metrics_gaps",
        sa.Column("verification_verdict", verification_verdict, nullable=True),
    )
    op.add_column(
        "review_metrics_gaps",
        sa.Column("verification_evidence", sa.JSON(), nullable=True),
    )
    op.create_foreign_key(
        "fk_metrics_gaps_resolved_review",
        "review_metrics_gaps",
        "service_reviews",
        ["resolved_in_review_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_review_metrics_gaps_fingerprint",
        "review_metrics_gaps",
        ["gap_fingerprint"],
    )
    op.create_index(
        "idx_review_metrics_gaps_resolution",
        "review_metrics_gaps",
        ["resolution_status"],
    )


def downgrade() -> None:
    # Drop indexes and columns from review_metrics_gaps
    op.drop_index("idx_review_metrics_gaps_resolution", table_name="review_metrics_gaps")
    op.drop_index("idx_review_metrics_gaps_fingerprint", table_name="review_metrics_gaps")
    op.drop_constraint("fk_metrics_gaps_resolved_review", "review_metrics_gaps", type_="foreignkey")
    op.drop_column("review_metrics_gaps", "verification_evidence")
    op.drop_column("review_metrics_gaps", "verification_verdict")
    op.drop_column("review_metrics_gaps", "resolved_in_review_id")
    op.drop_column("review_metrics_gaps", "resolution_status")
    op.drop_column("review_metrics_gaps", "gap_fingerprint")

    # Drop indexes and columns from review_logging_gaps
    op.drop_index("idx_review_logging_gaps_resolution", table_name="review_logging_gaps")
    op.drop_index("idx_review_logging_gaps_fingerprint", table_name="review_logging_gaps")
    op.drop_constraint("fk_logging_gaps_resolved_review", "review_logging_gaps", type_="foreignkey")
    op.drop_column("review_logging_gaps", "verification_evidence")
    op.drop_column("review_logging_gaps", "verification_verdict")
    op.drop_column("review_logging_gaps", "resolved_in_review_id")
    op.drop_column("review_logging_gaps", "resolution_status")
    op.drop_column("review_logging_gaps", "gap_fingerprint")

    # Drop service_id from parsed_repositories
    op.drop_index("idx_parsed_repositories_service", table_name="parsed_repositories")
    op.drop_constraint("fk_parsed_repositories_service", "parsed_repositories", type_="foreignkey")
    op.drop_column("parsed_repositories", "service_id")

    # Drop tables
    op.drop_table("code_facts")
    op.drop_table("codebase_contexts")

    # Drop enum types
    sa.Enum(name="verificationverdict").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="gapresolutionstatus").drop(op.get_bind(), checkfirst=True)
