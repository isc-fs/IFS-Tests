"""attempts lp day index: the leaderboards read a period's answers, not the whole history

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Only an index, so the previous release keeps running unchanged. It blocks writes to attempts while it
    # builds: 35 ms for three seasons of play (310k answers).
    op.create_index(
        "ix_attempts_lp_day",
        "attempts",
        ["user_id", sa.text("coalesce(day, date(timezone('Europe/Madrid', created_at)))")],
        postgresql_where=sa.text("lp != 0 AND mode IN ('daily', 'practice')"),
    )


def downgrade() -> None:
    op.drop_index("ix_attempts_lp_day", table_name="attempts")
