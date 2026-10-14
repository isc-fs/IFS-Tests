"""questions.keep_order: a reviewer can keep one question's options in bank order on the daily;
daily_questions.first_drawn_at: when the day was first drawn, which a redraw never moves

Expand only: a NOT NULL column with a constant default (metadata only on PostgreSQL 11+) and a nullable one,
which the previous release ignores.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-13 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "questions", sa.Column("keep_order", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("daily_questions", sa.Column("first_drawn_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("daily_questions", "first_drawn_at")
    op.drop_column("questions", "keep_order")
