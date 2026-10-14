from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from ifs_tests import scheduler
from ifs_tests.auth.sessions import create_session
from ifs_tests.db import session as db_session
from ifs_tests.db.models import Attempt, Invite, PasswordReset, Question, User
from ifs_tests.db.models import Session as LoginSession
from ifs_tests.scheduler import Job
from ifs_tests.services import accounts, maintenance
from ifs_tests.settings import get_settings

from ..conftest import Clock
from .conftest import run

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

    quiet = {
        "dailies_closed": 0,
        "dailies_settled": 0,
        "dailies_settle_failed": 0,
        "mock_questions_closed": 0,
        "mock_runs_ended": 0,
        "live_sessions_finished": 0,
        "live_answers_shared": 0,
        "difficulty_changed": 0,
        "ranks_reset": 0,
        "freezes_used": 0,
        "freezes_earned": 0,
        "alumni_deleted": 0,
        "audit_purged": 0,
        "signals_purged": 0,
    }
    assert maintenance.run(db, clock.now) == {"sessions": 2, "invites": 1, "resets": 1, **quiet}
    assert maintenance.run(db, clock.now) == {"sessions": 0, "invites": 0, "resets": 0, **quiet}
    for model in (LoginSession, Invite, PasswordReset):
        assert db.scalar(select(func.count()).select_from(model)) == 1


@pytest.fixture
def cli_db(db: Session, app_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("IFS_DATABASE_URL", app_engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("IFS_PUBLIC_ORIGIN", "https://quiz.example")
    get_settings.cache_clear()
    db_session.reset()
    yield
    get_settings.cache_clear()
    db_session.reset()


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


def test_cli_push_loads_the_sample_bank_once(
    cli_db: None, db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IFS_MEDIA_DIR", str(tmp_path))
    get_settings.cache_clear()
    assert "added=12" in run(["push", "--sample"])
    assert "unchanged=12" in run(["push", "--sample"])
    assert len(list(tmp_path.glob("*.webp"))) == 1
    with pytest.raises(SystemExit, match="not found"):
        run(["--data", str(tmp_path / "nowhere"), "push"])


def test_the_scheduler_settles_the_days_results_at_00_01(
    cli_db: None, db: Session, daily_player: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, list[Job]] = {}
    monkeypatch.setattr(
        "ifs_tests.scheduler.run_forever", lambda jobs, ping, poll_seconds=30: captured.update(jobs=jobs)
    )
    run(["scheduler"])
    jobs = {j.name: j for j in captured["jobs"]}
    names = list(jobs)
    assert names.index("daily") < names.index("settle") < names.index("maintenance")
    assert jobs["settle"].at == clock_time(0, 1)

    qid = db.scalars(select(Question.id).where(Question.area == "mech", Question.graded)).first()
    assert qid is not None
    day, answered = date(2026, 10, 1), datetime(2026, 10, 1, 10, 1, tzinfo=UTC)
    db.add(
        Attempt(
            user_id=daily_player.id,
            question_id=qid,
            mode="daily",
            answer={"options": [], "value": None, "unsure": False},
            correct=True,
            late=False,
            created_at=answered - timedelta(minutes=1),
            submitted_at=answered,
            deadline_at=answered + timedelta(minutes=1),
            day=day,
            area="mech",
            released_at=datetime(2026, 10, 1, 22, tzinfo=UTC),
        )
    )
    db.commit()
    night = datetime(2026, 10, 1, 22, 1, tzinfo=UTC)  # 00:01 on the 2nd in Madrid
    assert jobs["settle"].run(night) == {"dailies_settled": 1, "dailies_settle_failed": 0}
    assert jobs["settle"].run(night) == {"dailies_settled": 0, "dailies_settle_failed": 0}
    db.expire_all()
    row = db.scalars(select(Attempt)).one()
    assert row.settled_at == night and row.xp > 0 and row.lp > 0
    assert db.get_one(User, daily_player.id).xp == row.xp


def waiting_daily(db: Session, player: User, area: str = "mech", day: date = date(2026, 10, 1)) -> int:
    """A right daily answered at 10:01 on `day` on a per-player day: stored and graded, not granted."""
    qid = db.scalars(select(Question.id).where(Question.area == area, Question.graded)).first()
    assert qid is not None
    answered = datetime(day.year, day.month, day.day, 10, 1, tzinfo=UTC)
    a = Attempt(
        user_id=player.id,
        question_id=qid,
        mode="daily",
        answer={"options": [], "value": None, "unsure": False},
        correct=True,
        late=False,
        created_at=answered - timedelta(minutes=1),
        submitted_at=answered,
        deadline_at=answered + timedelta(minutes=1),
        day=day,
        area=area,
        released_at=datetime(day.year, day.month, day.day, 22, tzinfo=UTC),
    )
    db.add(a)
    db.commit()
    return a.id


def test_cli_settle_grants_what_is_due_prints_the_counts_and_is_idempotent(
    cli_db: None, db: Session, daily_player: User
) -> None:
    """Usable from the new image while the previous release serves, and after a rollback to it: the way to
    empty the waiting results (runbook, rollback)."""
    first = waiting_daily(db, daily_player, "mech")
    second = waiting_daily(db, daily_player, "elec")
    before = datetime(2026, 10, 1, 21, 59, 59, tzinfo=UTC)
    out = run(["settle", "--now", before.isoformat()])
    assert re.search(r"settled\w*\D+0\b", out), out  # nothing is due a second before the midnight
    db.expire_all()
    assert db.get_one(Attempt, first).settled_at is None and db.get_one(User, daily_player.id).xp == 0

    night = datetime(2026, 10, 1, 22, 0, 30, tzinfo=UTC)
    out = run(["settle", "--now", night.isoformat()])
    assert re.search(r"settled\w*\D+2\b", out), out
    assert re.search(r"failed\w*\D+0\b", out), out
    db.expire_all()
    rows = [db.get_one(Attempt, i) for i in (first, second)]
    assert all(a.settled_at == night and a.xp > 0 and a.lp > 0 for a in rows)
    assert db.get_one(User, daily_player.id).xp == sum(a.xp for a in rows)

    again = run(["settle", "--now", night.isoformat()])
    assert re.search(r"settled\w*\D+0\b", again), again
    db.expire_all()
    assert db.get_one(User, daily_player.id).xp == sum(a.xp for a in rows)  # nothing is granted twice


def test_cli_settle_without_a_clock_uses_the_present_and_settles_nothing_that_is_not_due(
    cli_db: None, db: Session, daily_player: User
) -> None:
    far = date.today() + timedelta(days=2)
    waiting = waiting_daily(db, daily_player, "mech", far)
    out = run(["settle"])
    assert "settled" in out
    db.expire_all()
    assert db.get_one(Attempt, waiting).settled_at is None  # its midnight is in the future


@pytest.mark.parametrize("bad", ["2026-10-01T22:00:30", "future"])
def test_cli_settle_refuses_a_naive_or_future_clock_that_would_reveal_results_early(
    cli_db: None, db: Session, daily_player: User, bad: str
) -> None:
    waiting = waiting_daily(db, daily_player, "mech", date.today() + timedelta(days=2))
    now = bad if bad != "future" else (datetime.now(UTC) + timedelta(days=3)).isoformat()
    with pytest.raises(SystemExit) as stopped:
        run(["settle", "--now", now])
    assert stopped.value.code == 2
    db.expire_all()
    assert db.get_one(Attempt, waiting).settled_at is None and db.get_one(User, daily_player.id).xp == 0


def test_cli_settle_counts_the_results_still_pending_and_drained_exits_while_there_are_any(
    cli_db: None, db: Session, daily_player: User
) -> None:
    """The gate before a rollback (runbook 5.8): a result whose midnight is still to come is not failed, but it is
    not drained either."""
    waiting_daily(db, daily_player, "mech", date.today() + timedelta(days=2))
    due = waiting_daily(db, daily_player, "elec")
    out = run(["settle"])
    assert re.search(r"'dailies_settled': 1\b", out) and re.search(r"'dailies_pending': 1\b", out), out
    db.expire_all()
    assert db.get_one(Attempt, due).settled_at is not None
    with pytest.raises(SystemExit) as stopped:
        run(["settle", "--drained"])
    assert stopped.value.code == 1
    db.execute(update(Attempt).where(Attempt.settled_at.is_(None)).values(settled_at=datetime.now(UTC)))
    db.commit()
    assert re.search(r"'dailies_pending': 0\b", run(["settle", "--drained"]))


def test_the_scheduler_job_reports_a_failure_without_stopping_and_tries_it_again(
    cli_db: None,
    db: Session,
    daily_player: User,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A result that cannot be granted does not stop the others. The job logs its counts and then fails, so the
    scheduler writes `settle failed` (the line the runbook greps for) and the health check goes red."""
    from ifs_tests.services import xp

    captured: dict[str, list[Job]] = {}
    monkeypatch.setattr(
        "ifs_tests.scheduler.run_forever", lambda jobs, ping, poll_seconds=30: captured.update(jobs=jobs)
    )
    run(["scheduler"])
    job = {j.name: j for j in captured["jobs"]}["settle"]
    other = User(email="q@x.com", password_hash="x", display_name="Other")
    db.add(other)
    db.commit()
    broken, fine = waiting_daily(db, daily_player, "mech"), waiting_daily(db, other, "mech")
    fault = [True]

    def crit(_db: Session, user: int, _question: int, _moment: datetime) -> bool:
        if fault[0] and user == daily_player.id:
            raise RuntimeError("boom")
        return False

    monkeypatch.setattr(xp, "_crit", crit)
    night = datetime(2026, 10, 1, 22, 1, tzinfo=UTC)
    with caplog.at_level(logging.INFO):
        with pytest.raises(RuntimeError, match=r"1 daily result"):
            job.run(night)
        seen = caplog.text + capsys.readouterr().out
        assert re.search(r"dailies_settled\W+1\b", seen) and re.search(r"dailies_settle_failed\W+1\b", seen)
        scheduler.tick([job], {}, night)  # and the scheduler carries on, writing the line to grep for
    assert "settle failed" in caplog.text
    db.expire_all()
    assert db.get_one(Attempt, fine).settled_at == night and db.get_one(Attempt, broken).settled_at is None
    fault[0] = False
    assert job.run(night) == {"dailies_settled": 1, "dailies_settle_failed": 0}  # the job tries it again
    db.expire_all()
    assert db.get_one(Attempt, broken).settled_at == night
