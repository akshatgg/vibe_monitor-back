"""Fix enum case mismatch - SUPERSEDED

Revision ID: f1x3num5
Revises: 2623c4d56e6e

SUPERSEDED: This migration converted UPPERCASE to lowercase.
That direction is no longer desired. This is now a documented no-op.
The final normalization migration (u1p2p3e4r5) handles all enum casing.
"""


revision = "f1x3num5"
down_revision = "2623c4d56e6e"
branch_labels = None
depends_on = None


def upgrade():
    # NO-OP: Superseded by u1p2p3e4r5_normalize_enums_to_uppercase.py
    # Original behavior: Converted UPPERCASE enum values to lowercase
    # This is no longer executed to prevent conflicts with final normalization
    pass


def downgrade():
    # NO-OP: Superseded by u1p2p3e4r5_normalize_enums_to_uppercase.py
    pass
