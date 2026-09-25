"""daily drawn at: when the day's question was drawn, so only mock answers hidden after that count as hidden

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-25 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("daily_questions", sa.Column("drawn_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("daily_questions", "drawn_at")
