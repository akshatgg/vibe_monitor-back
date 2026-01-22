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
    inspector = sa.inspect(op.get_bind())
    table_name = "chat_files"

    existing_tables = set(inspector.get_table_names())
    existing_indexes = {i["name"] for i in inspector.get_indexes(table_name)} if table_name in existing_tables else set()

    # Create table if it doesn't exist
    if table_name not in existing_tables:
        op.create_table(
            table_name,
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
        existing_indexes = set()
    else:
        print(f"  ⊘ Table '{table_name}' already exists, skipping...")

    # Create indexes if they don't exist
    indexes_to_create = [
        ('idx_chat_files_turn_id', ['turn_id']),
        ('idx_chat_files_uploaded_by', ['uploaded_by']),
        ('idx_chat_files_created_at', ['created_at']),
    ]

    for idx_name, columns in indexes_to_create:
        if idx_name not in existing_indexes:
            op.create_index(idx_name, table_name, columns)
            existing_indexes.add(idx_name)
        else:
            print(f"  ⊘ Index '{idx_name}' already exists, skipping...")


def downgrade() -> None:
    """Remove chat_files table."""
    inspector = sa.inspect(op.get_bind())
    table_name = "chat_files"

    existing_tables = set(inspector.get_table_names())
    existing_indexes = {i["name"] for i in inspector.get_indexes(table_name)} if table_name in existing_tables else set()

    # Drop indexes if they exist
    for idx_name in [
        'idx_chat_files_created_at',
        'idx_chat_files_uploaded_by',
        'idx_chat_files_turn_id',
    ]:
        if idx_name in existing_indexes:
            op.drop_index(idx_name, table_name=table_name)

    # Drop table if it exists
    if table_name in existing_tables:
        op.drop_table(table_name)
    else:
        print(f"  ⊘ Table '{table_name}' does not exist, skipping...")
