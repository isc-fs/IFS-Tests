from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ifs_tests import cli
from ifs_tests.auth.sessions import create_session
from ifs_tests.db.models import Invite, PasswordReset, User
from ifs_tests.db.models import Session as LoginSession
from ifs_tests.db.session import get_engine, session_factory
from ifs_tests.services import accounts, maintenance
from ifs_tests.settings import get_settings

from ..conftest import Clock

pytestmark = pytest.mark.integration


def test_maintenance_removes_only_stale_rows_and_is_idempotent(db: Session, clock: Clock) -> None:
    admin = accounts.create_first_admin(db, "a@x.com", "Alpha", "pit lane boss 2026", clock.now)
    create_session(db, admin, clock.now - timedelta(days=31))  # past absolute limit
    create_session(db, admin, clock.now - timedelta(hours=13))  # idle too long
    create_session(db, admin, clock.now - timedelta(hours=1))  # fine
    db.commit()
    accounts.create_invite(db, admin, clock.now - timedelta(days=40))  # expired over 30 days ago
    accounts.create_invite(db, admin, clock.now)
    accounts.create_reset(db, admin, admin.id, clock.now - timedelta(days=40))
    accounts.create_reset(db, admin, admin.id, clock.now)

    assert maintenance.run(db, clock.now) == {"sessions": 2, "invites": 1, "resets": 1}
    assert maintenance.run(db, clock.now) == {"sessions": 0, "invites": 0, "resets": 0}
    for model in (LoginSession, Invite, PasswordReset):
        assert db.scalar(select(func.count()).select_from(model)) == 1


@pytest.fixture
def cli_db(db: Session, app_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("IFS_DATABASE_URL", app_engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("IFS_PUBLIC_ORIGIN", "https://quiz.example")
    for cached in (get_settings, get_engine, session_factory):
        cached.cache_clear()
    yield
    for cached in (get_settings, get_engine, session_factory):
        cached.cache_clear()


def run(args: list[str], stdin: str = "") -> str:
    import contextlib

    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.MonkeyPatch.context() as m:
        m.setattr("sys.stdin", io.StringIO(stdin))
        cli.main(args)
    return out.getvalue()


def test_cli_bootstrap_invite_and_reset(cli_db: None, db: Session) -> None:
    with pytest.raises(SystemExit, match="Create an admin first"):
        run(["invite"])
    out = run(
        ["create-admin", "--email", "Boss@X.com", "--name", "Boss", "--password-stdin"],
        "diffuser plank 2026\n",
    )
    assert "Admin Boss created" in out
    with pytest.raises(SystemExit, match="already exists"):
        run(
            ["create-admin", "--email", "b2@x.com", "--name", "Boss Two", "--password-stdin"],
            "diffuser plank 2026\n",
        )

    link = run(["invite", "--role", "reviewer", "--vertical", "Driverless"]).split()[0]
    assert link.startswith("https://quiz.example/invite#")
    invite = db.scalar(select(Invite))
    assert invite is not None and (invite.role, invite.vertical) == ("reviewer", "Driverless")

    assert run(["reset-link", "--email", "boss@x.com"]).startswith("https://quiz.example/reset#")
    with pytest.raises(SystemExit, match="No user"):
        run(["reset-link", "--email", "ghost@x.com"])
    assert "sessions" in run(["maintenance"])
    assert db.scalar(select(func.count()).select_from(User)) == 1
