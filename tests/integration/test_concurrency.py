"""Races that single-request tests can't see. Each test starts real threads against Postgres."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import AnswerOption, Attempt, DailyQuestion, MockSession, User
from ifs_tests.domain.daily import madrid_day
from ifs_tests.services import accounts, daily, mock
from ifs_tests.services.bank import import_bank

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def race(engine: Engine, *jobs: Callable[[Session], Any]) -> list[Any]:
    """Run jobs at the same moment, each in its own session; return results or exceptions."""
    barrier = threading.Barrier(len(jobs))
    results: list[Any] = [None] * len(jobs)

    def run(i: int) -> None:
        with sessionmaker(engine, expire_on_commit=False)() as db:
            barrier.wait()
            try:
                results[i] = jobs[i](db)
            except Exception as e:  # noqa: BLE001 - the caller inspects what happened
                results[i] = e

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(jobs))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_two_admins_demoting_each_other_leave_one_admin(db: Session, app_engine: Engine) -> None:
    a = accounts.create_first_admin(db, "a@x.com", "Alpha", "pit lane boss 2026", NOW)
    b = User(email="b@x.com", password_hash="x", display_name="Bravo", role="admin")
    db.add(b)
    db.commit()
    results = race(
        app_engine,
        lambda s: accounts.update_user(s, s.get_one(User, a.id), b.id, role="member"),
        lambda s: accounts.update_user(s, s.get_one(User, b.id), a.id, role="member"),
    )
    assert sum(isinstance(r, accounts.AccountError) and r.status == 409 for r in results) == 1
    admins = db.scalar(select(func.count()).where(User.role == "admin", User.status == "active"))
    assert admins == 1


def test_simultaneous_registrations_with_the_same_email_give_one_account_and_one_409(
    db: Session, app_engine: Engine
) -> None:
    admin = accounts.create_first_admin(db, "a@x.com", "Alpha", "pit lane boss 2026", NOW)
    tokens = [accounts.create_invite(db, admin, NOW)[0] for _ in range(2)]
    results = race(
        app_engine,
        *[
            (lambda s, t=t, n=n: accounts.register(s, t, "same@x.com", n, "tractive system 900V!", NOW))
            for t, n in zip(tokens, ["One", "Two"], strict=True)
        ],
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], accounts.AccountError) and errors[0].status == 409
    assert db.scalar(select(func.count()).where(User.email == "same@x.com")) == 1


def test_case_variants_that_lowercase_the_same_in_postgres_are_one_name(db: Session) -> None:
    admin = accounts.create_first_admin(db, "a@x.com", "Ivan", "pit lane boss 2026", NOW)
    token, _ = accounts.create_invite(db, admin, NOW)
    with pytest.raises(accounts.AccountError) as e:
        accounts.register(db, token, "b@x.com", "İvan", "tractive system 900V!", NOW)
    assert e.value.status in (400, 409)


def test_parallel_wrong_current_passwords_cannot_beat_the_lockout(db: Session, app_engine: Engine) -> None:
    admin = accounts.create_first_admin(db, "a@x.com", "Alpha", "pit lane boss 2026", NOW)
    guesses = [
        (
            lambda s, i=i: accounts.change_password(
                s, s.get_one(User, admin.id), f"wrong guess {i}", "new valid pass!", "tok", NOW
            )
        )
        for i in range(20)
    ]
    results = race(app_engine, *guesses)
    statuses = sorted(r.status for r in results if isinstance(r, accounts.AccountError))
    assert len(statuses) == 20 and statuses.count(403) <= 5 and 429 in statuses
    db.expire_all()
    assert db.get_one(User, admin.id).locked_until is not None


@pytest.fixture
def daily_player(db: Session, tmp_path: Path) -> User:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, NOW)
    user = User(email="p@x.com", password_hash="x", display_name="Player")
    db.add(user)
    db.commit()
    return user


def test_many_first_visitors_of_the_day_get_the_same_questions(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    day = madrid_day(NOW)
    results = race(app_engine, *[lambda s: daily.ensure_daily(s, day)] * 6)
    assert all(r == results[0] for r in results), results
    assert db.scalar(select(func.count()).select_from(DailyQuestion)) == 3


def test_a_double_start_gives_one_attempt_and_one_deadline(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    results = race(
        app_engine, *[lambda s: daily.start(s, s.get_one(User, daily_player.id), "mech", NOW)[1]] * 4
    )
    assert len({(a.id, a.deadline_at) for a in results}) == 1, results
    assert db.scalar(select(func.count()).select_from(Attempt)) == 1


def test_a_double_submit_is_graded_once(db: Session, app_engine: Engine, daily_player: User) -> None:
    _, attempt = daily.start(db, daily_player, "rules", NOW)
    options = list(db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == attempt.question_id)))
    later = NOW + timedelta(seconds=10)
    results = race(
        app_engine,
        *[
            (lambda s, o=o: daily.answer(s, s.get_one(User, daily_player.id), attempt.id, [o], None, later))
            for o in options
        ],
    )
    assert len({(r.checked.correct, r.points) for r in results}) == 1, results
    row = db.get_one(Attempt, attempt.id)
    db.refresh(row)
    assert row.submitted_at == later and row.answer["options"][0] in options


def test_a_double_start_of_a_mock_quiz_opens_one_run(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    results = race(app_engine, *[lambda s: mock.start(s, s.get_one(User, daily_player.id), 9002, NOW).id] * 4)
    assert len(set(results)) == 1, results
    assert db.scalar(select(func.count()).select_from(MockSession)) == 1


def test_a_double_submit_in_a_mock_quiz_moves_on_once(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    run = mock.start(db, daily_player, 9002, NOW)
    current = mock.state(db, daily_player, run.id, NOW).current
    assert current is not None
    attempt = current[1].id
    results = race(
        app_engine,
        *[
            lambda s: (
                mock.answer(
                    s, s.get_one(User, daily_player.id), run.id, attempt, [], None, NOW
                ).session.position
            )
        ]
        * 4,
    )
    assert results == [1, 1, 1, 1], results
