"""attempts results at day close: when a per-player daily's result is revealed, when its XP and LP were granted,
and what the grant paid on top

Expand only: three nullable columns (a metadata-only ADD COLUMN, no backfill) and a partial index that stays
empty until the season 1b date; its build blocks writes to attempts for milliseconds (see 0019 and 0026). The
previous release ignores all three. `released_at` is written when a per-player daily is started, so every older
row reads as revealed.

Rollback rule: the previous release has no settle and would show a pending daily's right or wrong at once. Roll
back before the first per-player day, or after running `ifs-tests settle` from this release's image once the last
pending result is due. The downgrade refuses while any result is still pending.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-13 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PENDING = "mode = 'daily' AND released_at IS NOT NULL AND submitted_at IS NOT NULL AND settled_at IS NULL"


def upgrade() -> None:
    op.add_column("attempts", sa.Column("released_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("attempts", sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("attempts", sa.Column("reward", postgresql.JSONB(), nullable=True))
    op.create_index(
        "ix_attempts_daily_pending",
        "attempts",
        ["user_id", "released_at"],
        postgresql_where=sa.text(PENDING),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text(f"SELECT 1 FROM attempts WHERE {PENDING} LIMIT 1")).first():  # noqa: S608
        raise RuntimeError("pending daily results exist: run `ifs-tests settle` after midnight first")
    op.drop_index("ix_attempts_daily_pending", table_name="attempts", postgresql_where=sa.text(PENDING))
    op.drop_column("attempts", "reward")
    op.drop_column("attempts", "settled_at")
    op.drop_column("attempts", "released_at")
