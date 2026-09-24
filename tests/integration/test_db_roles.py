from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ifs_tests.db.models import AuditLog, User
from ifs_tests.domain import accounts as account_rules
from ifs_tests.services import privacy

from ..conftest import migrate

pytestmark = pytest.mark.integration

PASSWORDS = {"migrator": "m-secret", "app_rt": "a-secret", "backup_ro": "b-secret"}


def as_role(url: str, role: str) -> str:
    return make_url(url).set(username=role, password=PASSWORDS[role]).render_as_string(hide_password=False)


@pytest.fixture(scope="module")
def db(postgres_url: str) -> str:
    """A database set up exactly like production: roles from deploy/db/roles.sql, migrated as migrator."""
    admin = make_url(postgres_url)
    dbname = "roles_test"
    with psycopg.connect(
        admin.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True
    ) as c:
        c.execute(f"CREATE DATABASE {dbname}")
    url = admin.set(database=dbname).render_as_string(hide_password=False)
    with psycopg.connect(
        make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)
    ) as c:
        c.execute(
            "SELECT set_config('quiz.migrator_password', %s, false), set_config('quiz.app_password', %s, false),"
            " set_config('quiz.backup_password', %s, false)",
            (PASSWORDS["migrator"], PASSWORDS["app_rt"], PASSWORDS["backup_ro"]),
        )
        c.execute(Path("deploy/db/roles.sql").read_text())
    migrate(as_role(url, "migrator"))
    return url


def connect(url: str, role: str) -> psycopg.Connection:
    return psycopg.connect(
        make_url(as_role(url, role)).set(drivername="postgresql").render_as_string(hide_password=False)
    )


def test_app_role_reads_and_writes_data_but_cannot_change_schema(db: str) -> None:
    with connect(db, "app_rt") as c:
        c.execute("INSERT INTO settings VALUES ('k', '{}')")
        assert c.execute("SELECT count(*) FROM settings").fetchone() == (1,)
        c.rollback()
        for ddl in (
            "CREATE TABLE evil (x int)",
            "DROP TABLE settings",
            "ALTER TABLE settings ADD COLUMN x int",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(ddl)
            c.rollback()


def test_app_role_cannot_rewrite_the_audit_log(db: str) -> None:
    with connect(db, "app_rt") as c:
        c.execute("INSERT INTO audit_log (action) VALUES ('probe')")
        for stmt in ("UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(stmt)
            c.rollback()


def test_backup_role_is_read_only(db: str) -> None:
    with connect(db, "backup_ro") as c:
        c.execute("SELECT count(*) FROM audit_log")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO settings VALUES ('k', '{}')")


def test_the_nightly_purge_runs_as_the_app_role(db: str) -> None:
    """Retention deletes year-old alumni and audit entries past their keep, though the app can't otherwise
    delete from the audit log."""
    engine = create_engine(make_url(as_role(db, "app_rt")).set(drivername="postgresql+psycopg"))
    now = datetime.now(UTC)
    with Session(engine) as s:
        gone = User(email="gone@x.com", password_hash="x", display_name="Gone", status="alumni")
        gone.left_at = now - timedelta(days=400)
        s.add(gone)
        s.flush()
        s.add_all(
            [
                AuditLog(actor_id=gone.id, action="user.join", at=now - timedelta(days=500)),
                AuditLog(action="old", at=now - timedelta(days=800)),
                AuditLog(action="recent", at=now - timedelta(days=10)),
            ]
        )
        s.commit()
        counts = privacy.purge(s, now)
        s.commit()
        assert (counts["alumni_deleted"], counts["audit_purged"]) == (1, 1)
        assert s.get(User, gone.id) is None
        left = set(s.scalars(select(AuditLog.action)))
        assert "recent" in left and "old" not in left
        # A later cutoff than the keep allows purges nothing more: the log can't be wiped through it.
        assert s.scalar(text("SELECT purge_audit_log(now() + interval '1 day')")) == 0
        s.commit()
    engine.dispose()
    assert timedelta(days=730) == account_rules.AUDIT_KEEP  # the keep migration 0016's function enforces
