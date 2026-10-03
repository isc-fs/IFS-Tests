"""drop users xp: the lifetime XP of the release before ADR 0007 (contract step of 0014)

No deployed release maps users.xp: prod has never run, and the first release (v1.0.0) is the first image
without it.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-01 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("users", "xp")


def downgrade() -> None:
    op.add_column("users", sa.Column("xp", sa.Integer(), server_default="0", nullable=False))
