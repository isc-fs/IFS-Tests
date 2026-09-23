from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from sqlalchemy.engine import make_url

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
