"""graded hash and upstream changes: a new solution or wording keeps a reviewer's correction, and quizzes
FS-Quiz deleted are retired

Revision ID: 0020
Revises: 0018
Create Date: 2026-09-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Expand only: the previous release ignores the new columns, and the next `ifs-tests push` fills
    `graded_hash`."""
    op.add_column("questions", sa.Column("graded_hash", sa.String(length=64), nullable=True))
    op.add_column("questions", sa.Column("upstream_change", sa.String(length=16), nullable=True))
    op.add_column("quizzes", sa.Column("retired", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("quizzes", "retired")
    op.drop_column("questions", "upstream_change")
    op.drop_column("questions", "graded_hash")
