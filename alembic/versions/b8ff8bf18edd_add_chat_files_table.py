"""add_chat_files_table

Revision ID: b8ff8bf18edd
Revises: 4347b727b544
Create Date: 2026-01-04 23:19:29.081814

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8ff8bf18edd'
down_revision: Union[str, Sequence[str], None] = '4347b727b544'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add chat_files table for S3 file storage."""
    op.create_table(
        'chat_files',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('turn_id', sa.String(), nullable=False),
        sa.Column('s3_bucket', sa.String(), nullable=False),
        sa.Column('s3_key', sa.String(), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('file_type', sa.String(50), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('relative_path', sa.String(500), nullable=True),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('uploaded_by', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['turn_id'], ['chat_turns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('idx_chat_files_turn_id', 'chat_files', ['turn_id'])
    op.create_index('idx_chat_files_uploaded_by', 'chat_files', ['uploaded_by'])
    op.create_index('idx_chat_files_created_at', 'chat_files', ['created_at'])


def downgrade() -> None:
    """Remove chat_files table."""
    op.drop_index('idx_chat_files_created_at', table_name='chat_files')
    op.drop_index('idx_chat_files_uploaded_by', table_name='chat_files')
    op.drop_index('idx_chat_files_turn_id', table_name='chat_files')
    op.drop_table('chat_files')
