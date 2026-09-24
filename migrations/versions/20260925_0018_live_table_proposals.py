"""live table proposals counter: a proposal wakes only its table's screens

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-25 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("live_tables", sa.Column("proposals", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("live_tables", "proposals")
