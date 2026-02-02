"""merge github_user_oauth and chat_files heads

Revision ID: 886ef6687692
Revises: 0df147135007, b8ff8bf18edd
Create Date: 2026-01-10 11:14:49.695987

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "886ef6687692"
down_revision: Union[str, Sequence[str], None] = ("0df147135007", "b8ff8bf18edd")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
