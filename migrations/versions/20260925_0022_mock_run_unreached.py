"""mock run unreached: a finished run keeps how many questions it didn't reach, so upstream deletions don't
rewrite its summary

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-25 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mock_sessions", sa.Column("unreached", sa.SmallInteger(), nullable=True))
    op.add_column("mock_sessions", sa.Column("unreached_graded", sa.SmallInteger(), nullable=True))
    # Finished runs: what they didn't reach, as the bank stands now.
    op.execute(
        """
        UPDATE mock_sessions s SET unreached = u.n, unreached_graded = u.graded
        FROM (
            SELECT s2.id, count(q.id) AS n, count(q.id) FILTER (WHERE q.graded) AS graded
            FROM mock_sessions s2
            LEFT JOIN quiz_questions qq ON qq.quiz_id = s2.quiz_id
            LEFT JOIN questions q ON q.id = qq.question_id AND q.playable
                AND NOT EXISTS (SELECT 1 FROM attempts a WHERE a.session_id = s2.id AND a.question_id = q.id)
            WHERE s2.finished_at IS NOT NULL
            GROUP BY s2.id
        ) u
        WHERE s.id = u.id
        """
    )


def downgrade() -> None:
    op.drop_column("mock_sessions", "unreached_graded")
    op.drop_column("mock_sessions", "unreached")
