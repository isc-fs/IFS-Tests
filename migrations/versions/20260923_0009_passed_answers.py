"""passed answers

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-23 21:10:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attempts", sa.Column("passed", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("attempts", "passed")
