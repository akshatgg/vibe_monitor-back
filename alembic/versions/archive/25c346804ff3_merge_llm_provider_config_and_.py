"""merge llm_provider_config and environments migrations

Revision ID: 25c346804ff3
Revises: e1n2v3s4, g1h2i3j4k5l6
Create Date: 2025-12-28 13:08:04.988211

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "25c346804ff3"
down_revision: Union[str, Sequence[str], None] = ("e1n2v3s4", "g1h2i3j4k5l6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
