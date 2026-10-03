"""audit log purge function

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-24 16:10:00

The app role can't delete from the audit log (0002), so the nightly retention purge failed on the server.
This function, owned by the migrating role, deletes only entries older than the keep (ADR 0006): whatever
cutoff the app passes, nothing younger than two years can go.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION purge_audit_log(before timestamptz) RETURNS integer
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
            WITH gone AS (
                DELETE FROM audit_log WHERE at < LEAST(before, now() - interval '730 days') RETURNING 1
            )
            SELECT count(*)::integer FROM gone
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION purge_audit_log(timestamptz) FROM PUBLIC")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_rt') THEN "
        "GRANT EXECUTE ON FUNCTION purge_audit_log(timestamptz) TO app_rt; END IF; END $$"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION purge_audit_log(timestamptz)")
