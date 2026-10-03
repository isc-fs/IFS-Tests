"""stable answer options and upstream removal notes

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-24 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Expand only: the next `ifs-tests push` fills `answer_options.fsquiz_id`."""
    op.add_column("answer_options", sa.Column("fsquiz_id", sa.Integer(), nullable=True))
    op.add_column(
        "answer_options", sa.Column("retired", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("questions", sa.Column("upstream_note", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("questions", "upstream_note")
    op.drop_column("answer_options", "retired")
    op.drop_column("answer_options", "fsquiz_id")
