"""Races that single-request tests can't see. Each test starts real threads against Postgres."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from ifs_tests.auth.passwords import hash_password
from ifs_tests.bank import images
from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import AnswerOption, Attempt, DailyQuestion, MockSession, Question, User
from ifs_tests.domain import rank as rank_rules
from ifs_tests.domain import xp as xp_rules
from ifs_tests.domain.daily import madrid_day
from ifs_tests.services import accounts, daily, live, mock, practice, privacy, review, streaks
from ifs_tests.services import bank as bank_service
from ifs_tests.services import xp as xp_service
from ifs_tests.services.bank import import_bank
from ifs_tests.services.errors import UserError

from ..api.helpers import right_answer
from .conftest import NOW

pytestmark = pytest.mark.integration


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
    # The second to take the admin lock is no admin any more (ACC-01).
    assert sum(isinstance(r, accounts.AccountError) and r.status == 403 for r in results) == 1
    admins = db.scalar(select(func.count()).where(User.role == "admin", User.status == "active"))
    assert admins == 1


def test_two_admins_deleting_their_accounts_at_once_leave_one_admin(db: Session, app_engine: Engine) -> None:
    a = accounts.create_first_admin(db, "a@x.com", "Alpha", "pit lane boss 2026", NOW)
    b = User(
        email="b@x.com", password_hash=hash_password("pit lane boss 2026"), display_name="Bravo", role="admin"
    )
    db.add(b)
    db.commit()
    results = race(
        app_engine,
        *[
            (lambda s, u=u: privacy.delete_self(s, s.get_one(User, u), "pit lane boss 2026", NOW))
            for u in (a.id, b.id)
        ],
    )
    assert sum(isinstance(r, accounts.AccountError) and r.status == 409 for r in results) == 1
    assert sum(r is None for r in results) == 1
    assert db.scalar(select(func.count()).where(User.role == "admin")) == 1


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
    # Right or wrong, an answer moves LP, so a double grant would show in the rank.
    daily_player.position, daily_player.rank_points = "member", 900.0
    db.commit()
    _, attempt = daily.start(db, daily_player, "rules", NOW)
    q = db.get_one(Question, attempt.question_id)
    options = list(db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == q.id)))
    later = NOW + timedelta(seconds=10)
    results = race(
        app_engine,
        *[
            (lambda s, o=o: daily.answer(s, s.get_one(User, daily_player.id), attempt.id, [o], None, later))
            for o in options
        ],
    )
    assert len({(r.checked.correct, r.xp, r.lp) for r in results}) == 1, results
    row = db.get_one(Attempt, attempt.id)
    db.refresh(row)
    assert row.submitted_at == later and row.answer["options"][0] in options
    assert row.correct is not None
    expected = rank_rules.lp_award(
        row.correct, 900, 3, "daily", area=q.area, answer_kind=q.answer_kind, options=len(options)
    )
    assert row.lp == pytest.approx(expected.amount) != 0
    assert row.xp == xp_rules.xp_award(row.correct, 3, "daily", first_win=row.correct).amount
    db.refresh(daily_player)
    assert (daily_player.xp, daily_player.rank_points) == pytest.approx((row.xp, 900 + row.lp))


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
    first = xp_rules.xp_award(True, 3, "practice", first_win=True).amount
    assert sorted(r.score.xp for r in results) == [0, 0, 0, first], results
    db.refresh(daily_player)
    placed = rank_rules.placement("mingo")  # created before placement: placed on the first answer
    assert (daily_player.xp, daily_player.rank_points, daily_player.combo) == pytest.approx(
        (first, placed, 1)
    )


def _practise_at_once(engine: Engine, player: User, answers: list[tuple[int, dict[str, Any]]]) -> list[Any]:
    """One player answering several practice questions in parallel tabs; returns each answer's score."""
    return race(
        engine,
        *[
            (
                lambda s, q=q, b=b: (
                    practice.answer(
                        s, s.get_one(User, player.id), q, b.get("options"), b.get("value"), NOW
                    ).score
                )
            )
            for q, b in answers
        ],
    )


def test_parallel_right_answers_by_one_player_build_the_combo_one_at_a_time(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    daily_player.rank_points, daily_player.combo = 500.0, 2
    db.commit()
    qids = list(db.scalars(select(Question.id).where(Question.graded, Question.playable).limit(4)))
    results = _practise_at_once(app_engine, daily_player, [(q, right_answer(db, q)) for q in qids])
    assert not any(isinstance(r, Exception) for r in results), results
    # Scored one after another: each saw the previous one's combo, points and first wins.
    assert sorted(g.combo for g in results) == [3, 4, 5, 6], results
    assert sum("first_win" in g.bonuses for g in results) == xp_rules.FIRST_WINS
    assert len({g.xp for g in results}) > 1
    db.refresh(daily_player)
    assert (daily_player.combo, daily_player.xp) == (6, sum(g.xp for g in results))
    assert daily_player.rank_points == 500  # practice earns XP only
    stored = db.scalars(select(Attempt.lp).where(Attempt.user_id == daily_player.id)).all()
    assert sorted(stored) == pytest.approx(sorted(g.lp for g in results))


def test_parallel_wrong_answers_by_one_player_count_the_bad_run_one_at_a_time(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    daily_player.rank_points, daily_player.miss_streak, daily_player.combo = 500.0, 2, 3
    db.commit()
    started = [daily.start(db, daily_player, area, NOW)[1].id for area in ("mech", "elec", "rules")]
    db.commit()
    results = race(
        app_engine,
        *[
            (
                lambda s, a=a: (
                    daily.answer(s, s.get_one(User, daily_player.id), a, None, "-1", NOW).checked.score
                )
            )
            for a in started
        ],
    )
    assert not any(isinstance(r, Exception) for r in results), results
    # Wrong daily answers 3, 4 and 5 in a row: only the two scored with three misses behind them are cushioned.
    assert sum(g.cushioned for g in results) == 2, results
    assert all(g.lp < 0 and g.combo == 0 for g in results), results
    db.refresh(daily_player)
    assert (daily_player.miss_streak, daily_player.combo) == (5, 0)
    assert daily_player.rank_points == pytest.approx(500 + sum(g.lp for g in results))


def test_closing_abandoned_dailies_never_deadlocks_with_a_late_answer(
    db: Session, app_engine: Engine, daily_player: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The nightly job holds one abandoned attempt and the player's row while the player answers another late.
    daily_player.position, daily_player.rank_points = "member", 900.0
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


LIVE_CONFIG = {
    "questions": "areas",
    "areas": ["rules"],
    "count": 1,
    "timing": "fixed",
    "seconds": 60,
    "feedback": "each",
    "routing": "all",
    "speed_points": False,
}


def _live_room(db: Session, daily_player: User) -> tuple[str, User, list[User]]:
    """A TD host, and daily_player captaining a table of three."""
    host = User(email="td@x.com", password_hash="x", display_name="Host", position="technical_director")
    mates = [User(email=f"m{i}@x.com", password_hash="x", display_name=f"Mate {i}") for i in range(2)]
    db.add_all([host, *mates])
    db.commit()
    s = live.create(db, host, LIVE_CONFIG, NOW)
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


def _then_share(db: Session, session_id: int) -> int:
    """What the routes do after responding to a live action that may close a question."""
    live.share(db, session_id, NOW)
    return session_id


def test_a_closing_answer_the_host_advancing_and_the_streams_sharing_at_once_grant_xp_once(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    """Sharing runs after the response, from the captain's request, the host's and each worker's event
    streams, all at once: every member still gets the question's XP exactly once."""
    host = User(email="td@x.com", password_hash="x", display_name="Host", position="technical_director")
    people = [User(email=f"t{i}@x.com", password_hash="x", display_name=f"T{i}") for i in range(8)]
    db.add_all([host, *people])
    db.commit()
    tables = [[daily_player, *people[:2]], people[2:5], people[5:]]
    config = {**LIVE_CONFIG, "count": 2}
    s = live.create(db, host, config, NOW)
    for u in (daily_player, *people):
        live.join(db, u, s.code, NOW)
    live.seat(
        db,
        host,
        s.code,
        [
            {"name": f"T{i}", "member_ids": [u.id for u in t], "captain_id": t[0].id}
            for i, t in enumerate(tables)
        ],
    )
    live.advance(db, host, s.code, NOW)
    for t in tables[:2]:
        live.answer(db, db.get_one(User, t[0].id), s.code, [], None, False, NOW)
    last = tables[2][0]
    results = race(
        app_engine,
        lambda x: _then_share(x, live.answer(x, x.get_one(User, last.id), s.code, [], None, False, NOW)),
        lambda x: _then_share(x, live.advance(x, x.get_one(User, host.id), s.code, NOW)),
        *[lambda x: live.share(x, s.id, NOW)] * 3,
    )
    assert not [r for r in results if isinstance(r, Exception) and not isinstance(r, UserError)], results
    live.share(db, s.id, NOW)
    rows = db.execute(select(Attempt.user_id, Attempt.xp).where(Attempt.mode == "live")).tuples().all()
    answered = isinstance(results[0], int)
    members = [u.id for t in (tables if answered else tables[:2]) for u in t]
    assert sorted(uid for uid, _ in rows) == sorted(members), results
    xp = dict(db.execute(select(User.id, User.xp).where(User.id.in_(members))).tuples().all())
    assert all(xp[uid] == earned for uid, earned in rows)  # granted once: the balance is the one attempt's XP


def test_a_captain_double_submitting_sends_one_answer_and_shares_xp_once(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    code, _, table = _live_room(db, daily_player)
    results = race(
        app_engine,
        *[
            lambda s: _then_share(
                s, live.answer(s, s.get_one(User, daily_player.id), code, [], None, False, NOW)
            )
        ]
        * 4,
    )
    assert sum(isinstance(r, int) for r in results) == 1, results  # the rest are "already answered"
    rows = db.scalars(select(Attempt).where(Attempt.mode == "live")).all()
    assert sorted(a.user_id for a in rows) == sorted(u.id for u in table)
    assert all(a.lp == 0 for a in rows)  # a table's answer never moves anyone's rank


def test_closing_a_question_while_the_captain_answers_never_loses_or_doubles_it(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    code, host, table = _live_room(db, daily_player)
    results = race(
        app_engine,
        lambda s: _then_share(s, live.advance(s, s.get_one(User, host.id), code, NOW)),
        lambda s: _then_share(
            s, live.answer(s, s.get_one(User, daily_player.id), code, [], None, False, NOW)
        ),
    )
    answered = isinstance(results[1], int)
    rows = db.scalars(select(Attempt).where(Attempt.mode == "live")).all()
    assert len(rows) == (len(table) if answered else 0), results


def test_a_rehearsal_sharing_xp_never_deadlocks_with_the_nightly_streak_job(
    db: Session, app_engine: Engine, daily_player: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = User(email="td@x.com", password_hash="x", display_name="Host", position="technical_director")
    players = [
        User(email=f"u{i}@x.com", password_hash="x", display_name=f"U{i}", streak_freezes=1) for i in range(4)
    ]
    db.add_all([host, *players])
    db.commit()
    low, high = players[:2], players[2:]
    config = {
        "questions": "areas",
        "areas": ["rules"],
        "count": 1,
        "timing": "fixed",
        "seconds": 60,
        "feedback": "end",
        "routing": "all",
        "speed_points": False,
    }
    s = live.create(db, host, config, NOW)
    for p in players:
        live.join(db, p, s.code, NOW)
    live.seat(
        db,
        host,
        s.code,
        [
            {"name": "High", "member_ids": [p.id for p in high], "captain_id": high[0].id},
            {"name": "Low", "member_ids": [p.id for p in low], "captain_id": low[0].id},
        ],
    )
    live.advance(db, host, s.code, NOW)
    for captain in (high[0], low[0]):  # the table with the higher ids answers first
        live.answer(db, db.get_one(User, captain.id), s.code, [], None, False, NOW)
    halfway = threading.Event()
    grant = xp_service.grant

    def slow_grant(session: Session, uid: int, *args: Any, **kwargs: Any) -> Any:
        granted = grant(session, uid, *args, **kwargs)
        if uid == high[-1].id:
            halfway.set()
            time.sleep(1.0)
        return granted

    monkeypatch.setattr(xp_service, "grant", slow_grant)

    def nightly(session: Session) -> dict[str, int]:
        halfway.wait(10)
        return streaks.nightly(session, NOW)

    results = race(
        app_engine,
        lambda session: _then_share(session, live.end(session, session.get_one(User, host.id), s.code, NOW)),
        nightly,
    )
    assert not any(isinstance(r, Exception) for r in results), results
