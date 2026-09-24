"""Races that single-request tests can't see. Each test starts real threads against Postgres."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from ifs_tests.bank import images
from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import AnswerOption, Attempt, DailyQuestion, MockSession, Question, User
from ifs_tests.domain.daily import madrid_day
from ifs_tests.domain.xp import award, floor_for, level_for
from ifs_tests.services import accounts, daily, live, mock, practice, review
from ifs_tests.services import bank as bank_service
from ifs_tests.services import xp as xp_service
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
    db.execute(update(Question).values(difficulty=3))
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
    # A returning member well above their floor, so a wrong answer costs XP too and a double grant shows.
    start = floor_for("member") + 1000
    daily_player.position, daily_player.xp = "member", start
    db.commit()
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
    assert len({(r.checked.correct, r.xp) for r in results}) == 1, results
    row = db.get_one(Attempt, attempt.id)
    db.refresh(row)
    assert row.submitted_at == later and row.answer["options"][0] in options
    assert row.xp == award(row.correct, 3, "daily", level_for(start)) != 0
    db.refresh(daily_player)
    assert daily_player.xp == start + row.xp


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


def test_hiding_a_question_during_an_import_sticks(
    db: Session, app_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The import pauses right as it writes the question; the reviewer hides it at that moment."""
    bank = load_bank(SAMPLE_DIR)
    empty = tmp_path / "no-images"
    empty.mkdir()
    import_bank(db, bank, empty, tmp_path / "media", NOW)  # the beam figure is missing: 90006 not playable
    reviewer = User(email="r@x.com", password_hash="x", display_name="Rev", role="reviewer")
    db.add(reviewer)
    db.commit()
    beam = db.scalars(select(Question.id).where(Question.fsquiz_id == 90006)).one()

    paused, resume = threading.Event(), threading.Event()
    real = images.to_media

    def slow_media(source: Path, media_dir: Path) -> str:
        paused.set()
        resume.wait(5)
        return real(source, media_dir)

    monkeypatch.setattr(bank_service, "to_media", slow_media)
    make = sessionmaker(app_engine, expire_on_commit=False)

    def run_import() -> None:
        with make() as s:
            import_bank(s, bank, SAMPLE_DIR / "img", tmp_path / "media", NOW)

    def hide() -> None:
        with make() as s:
            review.update(s, s.get_one(User, reviewer.id), beam, {"excluded": True}, NOW)

    importer = threading.Thread(target=run_import)
    importer.start()
    assert paused.wait(5)
    hider = threading.Thread(target=hide)
    hider.start()
    hider.join(0.5)  # with the row lock it waits for the import; without it, it commits now
    resume.set()
    importer.join()
    hider.join()
    q = db.get_one(Question, beam)
    db.refresh(q)
    assert (q.excluded, q.images_missing, q.playable) == (True, False, False)


def test_two_tabs_cannot_both_score_the_first_right_answer(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    qid = db.scalars(select(Question.id).where(Question.answer_kind == "choice-one")).first()
    assert qid is not None
    right = list(db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == qid).limit(1)))
    results = race(
        app_engine,
        *[lambda s: practice.answer(s, s.get_one(User, daily_player.id), qid, right, None, NOW)] * 4,
    )
    assert sorted(r.xp for r in results) == [0, 0, 0, award(True, 3, "practice", 0)], results
    db.refresh(daily_player)
    assert daily_player.xp == award(True, 3, "practice", 0)


def test_closing_abandoned_dailies_never_deadlocks_with_a_late_answer(
    db: Session, app_engine: Engine, daily_player: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The nightly job holds one abandoned attempt and the player's row while the player answers another late.
    daily_player.position, daily_player.xp = "member", floor_for("member") + 1000
    db.commit()
    started = [daily.start(db, daily_player, area, NOW)[1].id for area in ("mech", "elec")]
    later = NOW + timedelta(hours=1)
    job_holds, player_waits = threading.Event(), threading.Event()
    grant = xp_service.grant

    def slow_grant(s: Session, user_id: int, question: Question, *args: Any, **kwargs: Any) -> Any:
        granted = grant(s, user_id, question, *args, **kwargs)
        if threading.current_thread().name == "job" and not job_holds.is_set():
            job_holds.set()
            player_waits.wait(5)
            time.sleep(0.5)  # the player's request locks its attempt and queues for the player's row
        return granted

    monkeypatch.setattr(xp_service, "grant", slow_grant)
    results: dict[str, Any] = {}

    def job() -> None:
        with sessionmaker(app_engine, expire_on_commit=False)() as s:
            try:
                results["job"] = daily.close_expired(s, later)
            except Exception as e:  # noqa: BLE001
                results["job"] = e

    def player() -> None:
        job_holds.wait(5)
        with sessionmaker(app_engine, expire_on_commit=False)() as s:
            player_waits.set()
            try:
                results["player"] = daily.answer(
                    s, s.get_one(User, daily_player.id), started[1], [], None, later
                )
            except Exception as e:  # noqa: BLE001
                results["player"] = e

    threads = [threading.Thread(target=job, name="job"), threading.Thread(target=player)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not any(isinstance(r, Exception) for r in results.values()), results
    rows = db.scalars(
        select(Attempt).where(Attempt.id.in_(started)).execution_options(populate_existing=True)
    )
    assert all(a.submitted_at == later and a.late for a in rows)


def _live_room(db: Session, daily_player: User) -> tuple[str, User, list[User]]:
    """A TD host, and daily_player captaining a table of three."""
    host = User(email="td@x.com", password_hash="x", display_name="Host", position="technical_director")
    mates = [User(email=f"m{i}@x.com", password_hash="x", display_name=f"Mate {i}") for i in range(2)]
    db.add_all([host, *mates])
    db.commit()
    s = live.create(
        db,
        host,
        {
            "questions": "areas",
            "areas": ["rules"],
            "count": 1,
            "timing": "fixed",
            "seconds": 60,
            "feedback": "each",
            "routing": "all",
            "speed_points": False,
        },
        NOW,
    )
    for u in (daily_player, *mates):
        live.join(db, u, s.code, NOW)
    live.seat(
        db,
        host,
        s.code,
        [
            {
                "name": "T",
                "member_ids": [daily_player.id, *(m.id for m in mates)],
                "captain_id": daily_player.id,
            }
        ],
    )
    live.advance(db, host, s.code, NOW)
    return s.code, host, [daily_player, *mates]


def test_a_captain_double_submitting_sends_one_answer_and_shares_xp_once(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    code, _, table = _live_room(db, daily_player)
    results = race(
        app_engine,
        *[lambda s: live.answer(s, s.get_one(User, daily_player.id), code, [], None, False, NOW)] * 4,
    )
    assert sum(r is None for r in results) == 1, results  # the rest are "already answered"
    rows = db.scalars(select(Attempt).where(Attempt.mode == "live")).all()
    assert sorted(a.user_id for a in rows) == sorted(u.id for u in table)


def test_closing_a_question_while_the_captain_answers_never_loses_or_doubles_it(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    code, host, table = _live_room(db, daily_player)
    results = race(
        app_engine,
        lambda s: live.advance(s, s.get_one(User, host.id), code, NOW),
        lambda s: live.answer(s, s.get_one(User, daily_player.id), code, [], None, False, NOW),
    )
    answered = results[1] is None
    rows = db.scalars(select(Attempt).where(Attempt.mode == "live")).all()
    assert len(rows) == (len(table) if answered else 0), results
