from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from ifs_tests.db.models import AuditLog, User
from ifs_tests.db.session import read_only_engine
from ifs_tests.domain import accounts as account_rules
from ifs_tests.domain import integrity as integrity_rules
from ifs_tests.services import integrity, privacy

from ..conftest import migrate
from .conftest import INTEGRITY_SALT, integrity_settings, run, set_integrity_env

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


def test_backup_role_runs_the_integrity_report_read_only(db: str) -> None:
    """The report's whole fetch completes as backup_ro in its read-only snapshot, prints every section on a database
    without plays, and nothing can be written on that connection: not even a temporary view."""
    engine = read_only_engine(as_role(db, "backup_ro"))
    try:
        with Session(engine) as s:
            snap = integrity.fetch(
                s, integrity.Window(date(2026, 9, 1), date(2026, 10, 1)), frozenset(integrity_rules.CHECKS)
            )
            s.rollback()
            out = integrity.report(
                snap, b"x" * 32, frozenset(integrity_rules.CHECKS), integrity.thresholds(integrity_settings())
            )
            for name in (
                "label",
                "permutation",
                "fidelity",
                "follow",
                "upstream",
                "profile",
                "home",
                "people",
            ):
                assert any(h.startswith("## ") and name in h.lower() for h in out.splitlines()), name
            assert "n/a" in out

            for statement in (
                "CREATE TEMP VIEW v AS SELECT 1",
                "INSERT INTO settings VALUES ('k', '{}')",
                "UPDATE users SET display_name = 'x'",
                "DELETE FROM attempts",
            ):
                with pytest.raises(DBAPIError) as e:
                    s.execute(text(statement))
                assert isinstance(e.value.orig, psycopg.errors.ReadOnlySqlTransaction), statement
                s.rollback()  # the transaction is aborted after each
    finally:
        engine.dispose()


def test_a_plain_backup_connection_can_make_a_temp_view_so_the_read_only_transaction_is_what_stops_it(
    db: str,
) -> None:
    """backup_ro holds TEMPORARY on the database (deploy/db/roles.sql): outside a READ ONLY transaction a temporary
    view is allowed, and only the missing INSERT privilege stops a write. docs/security.md says so."""
    with connect(db, "backup_ro") as c:
        c.execute("CREATE TEMP VIEW v AS SELECT 1")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO settings VALUES ('k', '{}')")


def backup_sessions(db: str) -> int:
    with psycopg.connect(
        make_url(db).set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True
    ) as admin:
        row = admin.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE usename = 'backup_ro' AND datname = 'roles_test'"
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_the_cli_runs_as_backup_ro_with_the_password_from_the_environment(
    db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deployed shape: a DSN without a password, PGPASSWORD for the connection, nothing falling back to the
    app's own database settings, and no connection left open when the command ends."""
    server = make_url(db)
    without_password = URL.create(
        "postgresql+psycopg", username="backup_ro", host=server.host, port=server.port, database="roles_test"
    ).render_as_string(hide_password=False)
    assert PASSWORDS["backup_ro"] not in without_password
    set_integrity_env(monkeypatch, without_password)
    args = ["integrity-report", "--until", "2026-10-12", "--checks", "all", "--salt-stdin"]

    monkeypatch.delenv("PGPASSWORD", raising=False)
    with pytest.raises((OperationalError, SystemExit)):
        run(args, INTEGRITY_SALT + "\n")

    monkeypatch.setenv("PGPASSWORD", PASSWORDS["backup_ro"])
    out = run(args, INTEGRITY_SALT + "\n")
    assert out.startswith("# Integrity report") and "n/a" in out
    for _ in range(50):  # the backend takes a moment to go away
        if backup_sessions(db) == 0:
            break
        time.sleep(0.1)
    assert backup_sessions(db) == 0

    monkeypatch.setenv("PGPASSWORD", "not the password")
    with pytest.raises((OperationalError, SystemExit)):
        run(args, INTEGRITY_SALT + "\n")
