"""ranked signals: per-attempt aggregates the page reports in ranked play, and the AI canary's decoy option (ADR 0010)

Expand only: every column is nullable, the previous release ignores them.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-12 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attempts", sa.Column("away_declared_s", sa.Integer(), nullable=True))
    op.add_column("attempts", sa.Column("away_undeclared_s", sa.Integer(), nullable=True))
    op.add_column("attempts", sa.Column("pasted", sa.Boolean(), nullable=True))
    op.add_column("attempts", sa.Column("long_copies", sa.SmallInteger(), nullable=True))
    op.add_column("attempts", sa.Column("resumes", sa.SmallInteger(), nullable=True))
    op.add_column("attempts", sa.Column("decoy_option_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_attempts_decoy_option_id_answer_options"),
        "attempts",
        "answer_options",
        ["decoy_option_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_attempts_decoy_option_id"),
        "attempts",
        ["decoy_option_id"],
        unique=False,
        postgresql_where=sa.text("decoy_option_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_attempts_decoy_option_id"),
        table_name="attempts",
        postgresql_where=sa.text("decoy_option_id IS NOT NULL"),
    )
    op.drop_constraint(op.f("fk_attempts_decoy_option_id_answer_options"), "attempts", type_="foreignkey")
    for col in (
        "decoy_option_id",
        "resumes",
        "long_copies",
        "pasted",
        "away_undeclared_s",
        "away_declared_s",
    ):
        op.drop_column("attempts", col)
