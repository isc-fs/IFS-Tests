"""position lifts: what a raise of position gave, so a correction takes back only that

Revision ID: 0022
Revises: 0018
Create Date: 2026-09-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("position_lifts", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "position_lifts")
