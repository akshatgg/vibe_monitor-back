"""Initial schema baseline

Revision ID: b0f53cfcf12a
Revises:
Create Date: 2025-10-17 15:01:57.512019

This migration creates all base tables from SQLAlchemy models.
Checks if each table exists before creating it.
"""

from typing import Sequence, Union
from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "b0f53cfcf12a"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all base tables from SQLAlchemy models."""
    from app.models import Base

    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # Get all tables in dependency order (respects foreign keys)
    sorted_tables = Base.metadata.sorted_tables

    print(f"\n=== Baseline Migration: Creating tables from models ===")

    for table in sorted_tables:
        if table.name in existing_tables:
            print(f"  ⊘ Table '{table.name}' already exists, skipping...")
        else:
            print(f"  ✓ Creating table '{table.name}'...")
            table.create(bind, checkfirst=True)

    print(f"=== Baseline migration complete ===\n")


def downgrade() -> None:
    """Drop all tables."""
    from app.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
