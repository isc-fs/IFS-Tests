"""daily day index: the per-player draw and the withheld set count one day's daily attempts; and what a mock
run skipped because it was someone's daily question

Expand only: an index and a nullable column, which the previous release ignores. The index blocks writes to
attempts while it builds, which is milliseconds at this size (see 0019).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-12 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_attempts_daily_day",
        "attempts",
        ["day", "question_id"],
        postgresql_where=sa.text("mode = 'daily'"),
    )
    op.add_column("mock_sessions", sa.Column("skipped", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("mock_sessions", "skipped")
    op.drop_index("ix_attempts_daily_day", table_name="attempts", postgresql_where=sa.text("mode = 'daily'"))
