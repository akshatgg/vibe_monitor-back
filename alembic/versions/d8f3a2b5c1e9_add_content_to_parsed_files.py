"""add_content_to_parsed_files

Revision ID: d8f3a2b5c1e9
Revises: c07a6a7a69ae
Create Date: 2026-02-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd8f3a2b5c1e9'
down_revision: Union[str, Sequence[str], None] = 'c07a6a7a69ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add content and content_hash columns to parsed_files table."""
    # Add content column for storing full file content
    op.add_column('parsed_files', sa.Column('content', sa.Text(), nullable=True))

    # Add content_hash column for deduplication
    op.add_column('parsed_files', sa.Column('content_hash', sa.String(64), nullable=True))

    # Create index on content_hash for fast lookups
    op.create_index('idx_parsed_files_content_hash', 'parsed_files', ['content_hash'], unique=False)

    # Create composite index for repository + file_path queries
    op.create_index('idx_parsed_files_repo_path', 'parsed_files', ['repository_id', 'file_path'], unique=False)


def downgrade() -> None:
    """Remove content and content_hash columns from parsed_files table."""
    op.drop_index('idx_parsed_files_repo_path', table_name='parsed_files')
    op.drop_index('idx_parsed_files_content_hash', table_name='parsed_files')
    op.drop_column('parsed_files', 'content_hash')
    op.drop_column('parsed_files', 'content')
