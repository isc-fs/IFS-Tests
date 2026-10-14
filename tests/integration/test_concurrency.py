"""Races that single-request tests can't see. Each test starts real threads against Postgres."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from ifs_tests.auth.passwords import hash_password
from ifs_tests.bank import images
from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import AnswerOption, Attempt, DailyQuestion, LiveSession, MockSession, Question, User
from ifs_tests.domain import rank as rank_rules
from ifs_tests.domain import xp as xp_rules
from ifs_tests.domain.daily import madrid_day
from ifs_tests.domain.signals import OFF, Policy, Signals
from ifs_tests.services import accounts, daily, leaderboard, live, mock, practice, privacy, review, streaks
from ifs_tests.services import bank as bank_service
from ifs_tests.services import signals as signal_service
from ifs_tests.services import xp as xp_service
from ifs_tests.services.bank import import_bank
from ifs_tests.services.errors import UserError

from ..api.helpers import right_answer, set_daily
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
    results = race(app_engine, *[lambda s: daily.ensure_daily(s, day, NOW)] * 6)
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


PER_PLAYER = date(2020, 1, 1)  # the rule date long past: every day is a per-player day


def test_a_double_start_on_a_per_player_day_gives_one_attempt(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    results = race(
        app_engine,
        *[lambda s: daily.start(s, s.get_one(User, daily_player.id), "mech", NOW, rules_from=PER_PLAYER)[1]]
        * 4,
    )
    assert len({(a.id, a.deadline_at, a.question_id) for a in results}) == 1, results
    assert db.scalar(select(func.count()).select_from(Attempt)) == 1
    assert db.scalar(select(func.count()).select_from(DailyQuestion)) == 0  # nothing shared was drawn


def test_players_starting_at_once_on_a_per_player_day_each_get_a_question(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    others = [User(email=f"p{i}@x.com", password_hash="x", display_name=f"P{i}") for i in range(5)]
    db.add_all(others)
    db.commit()
    players = [daily_player, *others]
    results = race(
        app_engine,
        *[lambda s, u=u: daily.start(s, u, "mech", NOW, rules_from=PER_PLAYER)[1] for u in players],
    )
    assert not failed(results), results
    assert sorted(a.user_id for a in results) == sorted(u.id for u in players)
    assert db.scalar(select(func.count()).select_from(DailyQuestion)) == 0
    assert (
        db.scalar(select(func.count(func.distinct(Attempt.question_id)))) == 3
    )  # the area's three, each once
    assert db.scalar(select(func.count()).select_from(Attempt)) == 6


def test_two_accounts_starting_at_the_same_instant_are_not_dealt_the_same_question(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    """The spread counts what others drew, so two starts that read the same state would both pick the same
    question; colluders could fire them together on purpose. The area's draw lock makes each see the other."""
    other = User(email="p2@x.com", password_hash="x", display_name="Player Two")
    db.add(other)
    db.commit()
    for day in range(6):
        when = NOW + timedelta(days=day)
        first, second = race(
            app_engine,
            *[
                lambda s, u=u, when=when: daily.start(s, u, "mech", when, rules_from=PER_PLAYER)[0].id
                for u in (daily_player, other)
            ],
        )
        assert not failed([first, second]), (first, second)
        assert first != second, (day, first, second)


def test_a_start_racing_the_owners_deletion_ends_in_200_or_401(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    """The start takes the player's row before it writes, as answering does and deleting an account expects: the
    deletion never meets a half-written attempt (a foreign key error, a 500) and the two never wait on each
    other in a circle."""
    admin = accounts.create_first_admin(db, "a@x.com", "Alpha", "pit lane boss 2026", NOW)
    victims = [User(email=f"v{i}@x.com", password_hash="x", display_name=f"V{i}") for i in range(8)]
    db.add_all(victims)
    db.commit()
    ids = {v.email: v.id for v in victims}
    for v in victims:
        db.expunge(v)  # as the route has it: loaded before the request, whatever happens to the row meanwhile
    outcomes = set()
    for victim in victims:
        started, deleted = race(
            app_engine,
            lambda s, v=victim: daily.start(s, v, "mech", NOW, rules_from=PER_PLAYER),  # type: ignore[misc]
            lambda s, v=victim: privacy.delete_user(s, s.get_one(User, admin.id), ids[v.email], NOW),  # type: ignore[misc]
        )
        assert deleted is None, deleted  # a deadlock or a foreign key error would show here or below
        if isinstance(started, Exception):
            assert isinstance(started, UserError) and started.status == 401, started
        outcomes.add("401" if isinstance(started, Exception) else "200")
        db.expire_all()
        assert db.get(User, ids[victim.email]) is None
        assert (
            db.scalar(select(func.count()).select_from(Attempt).where(Attempt.user_id == ids[victim.email]))
            == 0
        )
    assert outcomes <= {"200", "401"}
    assert db.scalar(select(func.count()).select_from(DailyQuestion)) == 0


ON = Policy(collect=True, canary=True)


def failed(results: list[Any]) -> list[Any]:
    return [r for r in results if isinstance(r, Exception)]


def test_a_double_start_with_the_canary_draws_one_decoy_and_counts_no_reopening(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    qid = db.scalars(select(Question.id).where(Question.fsquiz_id == 90001)).one()  # four options
    set_daily(db, madrid_day(NOW), qid)
    results = race(
        app_engine, *[lambda s: daily.start(s, s.get_one(User, daily_player.id), "mech", NOW, ON)[1]] * 4
    )
    assert not failed(results), results
    row = db.scalars(select(Attempt)).one()
    # whoever's insert won, everyone got that row: its decoy and no second draw
    assert {(a.id, a.decoy_option_id) for a in results} == {(row.id, row.decoy_option_id)}
    assert row.decoy_option_id is not None and row.resumes == 0


def test_parallel_reopenings_of_a_daily_question_are_all_counted(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    _, a = daily.start(db, daily_player, "mech", NOW, ON)
    later = NOW + timedelta(seconds=15)
    results = race(
        app_engine, *[lambda s: daily.start(s, s.get_one(User, daily_player.id), "mech", later, ON)[1]] * 4
    )
    assert not failed(results), results
    row = db.get_one(Attempt, a.id)
    db.refresh(row)
    assert row.resumes == 4  # one atomic update each: none lost, none doubled


def test_parallel_page_loads_of_a_mock_run_are_all_counted(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    run = mock.start(db, daily_player, 9002, NOW)
    current = mock.state(db, daily_player, run.id, NOW, ON).current
    assert current is not None
    later = NOW + timedelta(seconds=15)
    results = race(
        app_engine,
        *[
            lambda s: (
                mock.state(
                    s, s.get_one(User, daily_player.id), run.id, later, ON, resumed=True
                ).session.position
            )
        ]
        * 4,
    )
    assert not failed(results), results
    row = db.get_one(Attempt, current[1].id)
    db.refresh(row)
    assert (row.resumes, row.submitted_at) == (4, None)


def test_a_double_submit_stores_one_consistent_set_of_signals(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    _, attempt = daily.start(db, daily_player, "rules", NOW, ON)
    later = NOW + timedelta(seconds=30)
    jobs = [
        (
            lambda s, i=i: daily.answer(
                s,
                s.get_one(User, daily_player.id),
                attempt.id,
                [],
                None,
                later,
                signals=Signals(away_declared_s=i, long_copies=10 * i),
                policy=ON,
            )
        )
        for i in (1, 2, 3, 4)
    ]
    assert not failed(race(app_engine, *jobs))
    row = db.get_one(Attempt, attempt.id)
    db.refresh(row)
    assert row.away_declared_s in (1, 2, 3, 4)
    assert row.long_copies == 10 * row.away_declared_s  # one request's signals, never a mix of two


def test_a_double_submit_in_a_mock_quiz_stores_one_consistent_set_of_signals(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    run = mock.start(db, daily_player, 9002, NOW)
    current = mock.state(db, daily_player, run.id, NOW, ON).current
    assert current is not None
    attempt = current[1].id
    later = NOW + timedelta(seconds=30)
    jobs = [
        (
            lambda s, i=i: (
                mock.answer(
                    s,
                    s.get_one(User, daily_player.id),
                    run.id,
                    attempt,
                    [],
                    None,
                    later,
                    signals=Signals(away_declared_s=i, long_copies=10 * i),
                    policy=ON,
                ).session.position
            )
        )
        for i in (1, 2, 3, 4)
    ]
    results = race(app_engine, *jobs)
    assert results == [1, 1, 1, 1], results
    row = db.get_one(Attempt, attempt)
    db.refresh(row)
    assert row.away_declared_s in (1, 2, 3, 4) and row.long_copies == 10 * row.away_declared_s


def test_the_signals_purge_runs_beside_an_account_deletion_and_an_answer(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    admin = accounts.create_first_admin(db, "a@x.com", "Alpha", "pit lane boss 2026", NOW)
    others = [User(email=f"p{i}@x.com", password_hash="x", display_name=f"P{i}") for i in range(2)]
    db.add_all(others)
    db.commit()
    players = [daily_player, *others]
    gone_id, player_id = others[0].id, daily_player.id
    old = datetime(2025, 10, 1, 10, tzinfo=UTC)  # last season: its signals are due for the nightly purge
    for u in players:
        _, a = daily.start(db, u, "mech", old, ON)
        daily.answer(
            db, u, a.id, [], None, old + timedelta(seconds=30), signals=Signals(long_copies=3), policy=ON
        )
    assert db.scalar(select(func.count()).select_from(Attempt).where(Attempt.resumes.is_not(None))) == 3
    _, running = daily.start(db, daily_player, "elec", NOW, ON)  # and this season's, still being answered
    results = race(
        app_engine,
        lambda s: signal_service.purge(s, NOW + timedelta(days=400)),
        lambda s: privacy.delete_user(s, s.get_one(User, admin.id), gone_id, NOW),
        lambda s: daily.answer(
            s,
            s.get_one(User, player_id),
            running.id,
            [],
            None,
            NOW + timedelta(seconds=30),
            signals=Signals(away_declared_s=5),
            policy=ON,
        ),
    )
    # Like every nightly job, a player deleted between listing and locking them is a UserError, not a deadlock
    assert not [r for r in failed(results) if not isinstance(r, UserError)], results
    db.expire_all()
    assert db.get(User, gone_id) is None
    old_rows = db.scalars(select(Attempt).where(Attempt.day == date(2025, 10, 1))).all()
    assert len(old_rows) == 2
    if not isinstance(results[0], Exception):
        assert results[0] in (2, 3)  # the deleted player's row may or may not have been purged first
        assert all(a.resumes is None and a.long_copies is None for a in old_rows)
    now_row = db.get_one(Attempt, running.id)
    assert (now_row.away_declared_s, now_row.resumes) == (5, 0)  # this season's stays
    signal_service.purge(
        db, NOW + timedelta(days=400)
    )  # a purge that met the deleted player finishes the job
    db.expire_all()
    assert all(
        a.resumes is None and a.long_copies is None
        for a in db.scalars(select(Attempt).where(Attempt.day == date(2025, 10, 1)))
    )
    assert signal_service.purge(db, NOW + timedelta(days=400)) == 0


def test_a_policy_left_off_never_writes_the_signal_columns_even_in_a_race(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    results = race(
        app_engine, *[lambda s: daily.start(s, s.get_one(User, daily_player.id), "mech", NOW, OFF)[1]] * 4
    )
    assert not failed(results), results
    row = db.scalars(select(Attempt)).one()
    assert (row.resumes, row.decoy_option_id, row.long_copies) == (None, None, None)


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
                results["job"] = daily.settle_results(s, later)
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


def _answer_pending(db: Session, player: User, area: str, right: bool = True) -> int:
    """Start the player's daily in `area` on a per-player day and answer it at once: stored and graded, its
    result waiting for the Madrid midnight. Returns the attempt id."""
    q, attempt = daily.start(db, player, area, NOW, rules_from=PER_PLAYER)
    body = right_answer(db, q.id) if right else _wrong(db, q.id)
    daily.answer(db, player, attempt.id, body.get("options"), body.get("value"), NOW + timedelta(seconds=30))
    return attempt.id


def _wrong(db: Session, qid: int) -> dict[str, Any]:
    right = right_answer(db, qid)
    if "options" in right:
        every = db.scalars(
            select(AnswerOption.id).where(AnswerOption.question_id == qid).order_by("position")
        )
        return {"options": [o for o in every if o not in right["options"]][:1]}
    return {"value": "; ".join("-1" for _ in right["value"].split(";"))}


def _settled_once(db: Session, user_id: int, ids: list[int], start: float) -> list[Attempt]:
    """Every attempt granted, and the player's account holds exactly their sum: a double grant would leave the
    account ahead of what the attempts say."""
    db.expire_all()
    rows = list(
        db.scalars(select(Attempt).where(Attempt.id.in_(ids)).execution_options(populate_existing=True))
    )
    assert all(a.settled_at is not None for a in rows)
    player = db.get_one(User, user_id, populate_existing=True)
    assert player.xp == sum(a.xp for a in rows)
    assert player.rank_points == pytest.approx(start + sum(a.lp for a in rows))
    return rows


LATER = NOW + timedelta(days=1)  # past the Madrid midnight that closes NOW's day (22:00 UTC on 1 October)


def test_a_double_submit_on_a_per_player_day_records_one_answer_and_grants_nothing(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    daily_player.rank_points = 500.0
    db.commit()
    q, attempt = daily.start(db, daily_player, "mech", NOW, rules_from=PER_PLAYER)
    body = right_answer(db, q.id)
    at = NOW + timedelta(seconds=20)
    results = race(
        app_engine,
        *[
            lambda s: daily.answer(
                s, s.get_one(User, daily_player.id), attempt.id, body.get("options"), body.get("value"), at
            )
        ]
        * 4,
    )
    assert not failed(results), results
    for r in results:  # every copy gets the same hidden result
        assert (r.xp, r.lp, r.checked.correct, r.checked.official) == (0, 0, None, None)
    db.expire_all()
    row = db.get_one(Attempt, attempt.id, populate_existing=True)
    assert (row.correct, row.submitted_at, row.xp, row.lp, row.settled_at) == (True, at, 0, 0, None)
    assert row.released_at == NOW.replace(hour=22)
    player = db.get_one(User, daily_player.id, populate_existing=True)
    assert (player.xp, player.rank_points, player.combo) == (0, 500.0, 0)
    assert daily.settle_results(db, LATER) == (1, 0)
    rows = _settled_once(db, daily_player.id, [attempt.id], 500.0)
    assert rows[0].xp > 0 and rows[0].lp > 0


def test_settle_racing_the_page_and_the_nightly_job_grants_once(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    daily_player.rank_points = 500.0
    db.commit()
    ids = [_answer_pending(db, daily_player, area) for area in ("mech", "elec", "rules")]
    assert db.scalar(select(func.count()).select_from(Attempt).where(Attempt.settled_at.is_not(None))) == 0
    results = race(
        app_engine,
        lambda s: daily.settle_results(s, LATER),
        lambda s: daily.settle_results(s, LATER),
        lambda s: daily.status(s, s.get_one(User, daily_player.id), LATER, rules_from=PER_PLAYER),
    )
    assert not failed(results), results
    assert results[0][1] == results[1][1] == 0 and results[0][0] + results[1][0] <= 3  # nothing failed
    rows = _settled_once(db, daily_player.id, ids, 500.0)
    assert all(a.settled_at == LATER and a.xp > 0 and a.lp > 0 for a in rows)
    assert daily.settle_results(db, LATER) == (0, 0)


def test_settle_racing_account_deletion_never_deadlocks(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    """The settle takes the player's row, then the attempt: the order deleting an account takes. A deletion in
    flight ends the settle quietly (the cascade took the attempt); it never raises or waits in a circle."""
    admin = accounts.create_first_admin(db, "a@x.com", "Alpha", "pit lane boss 2026", NOW)
    victims = [User(email=f"v{i}@x.com", password_hash="x", display_name=f"V{i}") for i in range(8)]
    db.add_all(victims)
    db.commit()
    for v in victims:
        _answer_pending(db, v, "mech")
    ids = {v.email: v.id for v in victims}
    for v in victims:
        db.expunge(v)
    granted = 0
    for victim in victims:
        settled, deleted = race(
            app_engine,
            lambda s: daily.settle_results(s, LATER),
            lambda s, v=victim: privacy.delete_user(s, s.get_one(User, admin.id), ids[v.email], LATER),  # type: ignore[misc]
        )
        assert deleted is None, deleted  # a deadlock or a foreign key error would show here
        assert isinstance(settled, tuple) and settled[1] == 0, (
            settled
        )  # and the settle carried on, not failed
        granted += settled[0]
        db.expire_all()
        assert db.get(User, ids[victim.email]) is None
        assert (
            db.scalar(select(func.count()).select_from(Attempt).where(Attempt.user_id == ids[victim.email]))
            == 0
        )
    left = db.scalar(select(func.count()).select_from(Attempt).where(Attempt.released_at.is_not(None)))
    assert left == 0 and granted <= len(victims)  # each granted at most once: by the first to get to it


def _settle_beside(
    app_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    player_job: Callable[[Session], Any],
    settle_for: int | None = None,
) -> dict[str, Any]:
    """The settle job holds the player's row mid-grant (a slow grant) while `player_job` queues behind it."""
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
                results["job"] = daily.settle_results(s, LATER, settle_for)
            except Exception as e:  # noqa: BLE001
                results["job"] = e

    def player() -> None:
        job_holds.wait(5)
        with sessionmaker(app_engine, expire_on_commit=False)() as s:
            player_waits.set()
            try:
                results["player"] = player_job(s)
            except Exception as e:  # noqa: BLE001
                results["player"] = e

    threads = [threading.Thread(target=job, name="job"), threading.Thread(target=player)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_settle_racing_a_late_answer_on_another_area(
    db: Session, app_engine: Engine, daily_player: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    daily_player.rank_points = 500.0
    db.commit()
    done = _answer_pending(db, daily_player, "mech")
    q, open_attempt = daily.start(db, daily_player, "elec", NOW, rules_from=PER_PLAYER)
    body = right_answer(db, q.id)
    open_id = open_attempt.id
    results = _settle_beside(
        app_engine,
        monkeypatch,
        lambda s: daily.answer(
            s, s.get_one(User, daily_player.id), open_id, body.get("options"), body.get("value"), LATER
        ),
    )
    assert not any(isinstance(r, Exception) for r in results.values()), results
    # the job grants the waiting one and, if it gets to the player's row after the answer, the late one as well
    # (an answer after its day's midnight is granted by its own request): never both twice
    assert results["job"] in ((1, 0), (2, 0))
    rows = _settled_once(db, daily_player.id, [done, open_id], 500.0)  # both granted, each once
    late = next(a for a in rows if a.id == open_id)
    assert (
        late.late is True and late.submitted_at == LATER and late.lp < 0
    )  # a right answer too late counts wrong
    assert next(a for a in rows if a.id == done).lp > 0


def test_settle_racing_a_practice_answer_after_midnight_grants_in_answer_order(
    db: Session, app_engine: Engine, daily_player: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wrong daily at 02:00 and a right practice answer after midnight: the daily is granted first whoever gets
    to the player's row first, so the combo ends at 1 (the other way round it would end at 0)."""
    daily_player.rank_points = 500.0
    db.commit()
    wrong_one = _answer_pending(db, daily_player, "mech", right=False)
    practised = db.scalars(select(Question).where(Question.area == "rules", Question.graded)).first()
    assert practised is not None
    body = right_answer(db, practised.id)
    scored: list[Any] = []

    def player_job(s: Session) -> Any:
        checked = practice.answer(
            s, s.get_one(User, daily_player.id), practised.id, body.get("options"), body.get("value"), LATER
        )
        scored.append(checked.score)
        return checked

    results = _settle_beside(app_engine, monkeypatch, player_job)
    assert not any(isinstance(r, Exception) for r in results.values()), results
    assert results["job"] == (1, 0)
    db.expire_all()
    daily_row = db.get_one(Attempt, wrong_one, populate_existing=True)
    assert daily_row.settled_at == LATER and daily_row.lp < 0
    player = db.get_one(User, daily_player.id, populate_existing=True)
    assert (player.combo, player.miss_streak) == (1, 1)
    assert player.xp == daily_row.xp + scored[0].xp
    assert player.rank_points == pytest.approx(500 + daily_row.lp)  # practice moves no LP


def test_a_scored_answer_that_finds_the_settle_done_grants_nothing_twice(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    """Six practice answers and a settle, all at once, after midnight: the daily is granted exactly once."""
    daily_player.rank_points = 500.0
    db.commit()
    done = _answer_pending(db, daily_player, "mech")
    qids = list(db.scalars(select(Question.id).where(Question.area != "mech", Question.graded).limit(5)))
    jobs: list[Callable[[Session], Any]] = [lambda s: daily.settle_results(s, LATER)]
    for qid in qids:
        body = right_answer(db, qid)
        jobs.append(
            lambda s, qid=qid, body=body: practice.answer(  # type: ignore[misc]
                s, s.get_one(User, daily_player.id), qid, body.get("options"), body.get("value"), LATER
            )
        )
    results = race(app_engine, *jobs)
    assert not failed(results), results
    db.expire_all()
    row = db.get_one(Attempt, done, populate_existing=True)
    assert row.settled_at == LATER
    practice_xp = sum(r.score.xp for r in results[1:])
    assert db.get_one(User, daily_player.id, populate_existing=True).xp == row.xp + practice_xp


def test_the_job_the_page_and_an_account_deletion_at_once_grant_once_and_never_deadlock(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    """The night job, the owner's page (a lazy settle) and the deletion of the account all take the player's row
    first, then the attempt. A bystander's results, reached by the job and by their own page, are granted once."""
    admin = accounts.create_first_admin(db, "a@x.com", "Alpha", "pit lane boss 2026", NOW)
    daily_player.rank_points = 500.0
    victims = [User(email=f"v{i}@x.com", password_hash="x", display_name=f"V{i}") for i in range(6)]
    db.add_all(victims)
    db.commit()
    bystander = [_answer_pending(db, daily_player, area) for area in ("mech", "elec")]
    ids = {}
    for v in victims:
        _answer_pending(db, v, "mech")
        ids[v.email] = v.id
        db.expunge(v)
    for victim in victims:
        job, page, theirs, deleted = race(
            app_engine,
            lambda s: daily.settle_results(s, LATER),
            lambda s, v=victim: daily.settle_results(s, LATER, ids[v.email]),  # type: ignore[misc]
            lambda s: daily.status(s, s.get_one(User, daily_player.id), LATER, rules_from=PER_PLAYER),
            lambda s, v=victim: privacy.delete_user(s, s.get_one(User, admin.id), ids[v.email], LATER),  # type: ignore[misc]
        )
        assert deleted is None, deleted  # a deadlock or a foreign key error would show here
        assert isinstance(job, tuple) and job[1] == 0, job  # the settle carried on: nothing failed
        assert not isinstance(theirs, Exception), theirs
        assert isinstance(page, tuple) and page[1] == 0, (
            page
        )  # the page's own settle: a vanished account is skipped
        db.expire_all()
        assert db.get(User, ids[victim.email]) is None
        assert (
            db.scalar(select(func.count()).select_from(Attempt).where(Attempt.user_id == ids[victim.email]))
            == 0
        )
    daily.settle_results(db, LATER)  # whatever the pages did not reach
    rows = _settled_once(db, daily_player.id, bystander, 500.0)
    assert all(a.xp > 0 and a.lp > 0 for a in rows)


def test_a_live_share_and_the_settle_of_the_same_member_grant_each_once(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    """A table member with a result waiting: the share of the table's closed question (xp.grant settles first)
    races the night job and another share. The daily is granted once, and so is the live answer."""
    daily_player.rank_points = 500.0
    db.commit()
    done = _answer_pending(db, daily_player, "mech")
    code, _, table = _live_room(db, daily_player)
    live.answer(db, db.get_one(User, daily_player.id), code, [], None, False, NOW)
    session_id = db.scalar(select(LiveSession.id).where(LiveSession.code == code))
    assert session_id is not None
    results = race(
        app_engine,
        lambda s: live.share(s, session_id, LATER),
        lambda s: daily.settle_results(s, LATER),
        lambda s: live.share(s, session_id, LATER),
    )
    assert not [r for r in results if isinstance(r, Exception) and not isinstance(r, UserError)], results
    live.share(db, session_id, LATER)
    db.expire_all()
    row = db.get_one(Attempt, done, populate_existing=True)
    assert row.settled_at == LATER and row.xp > 0 and row.lp > 0
    lives = db.scalars(
        select(Attempt).where(Attempt.mode == "live").execution_options(populate_existing=True)
    ).all()
    assert sorted(a.user_id for a in lives) == sorted(u.id for u in table)  # every member, once
    mine = next(a for a in lives if a.user_id == daily_player.id)
    player = db.get_one(User, daily_player.id, populate_existing=True)
    assert player.xp == row.xp + mine.xp
    assert player.rank_points == pytest.approx(500 + row.lp)  # a table's answer moves no LP


def test_a_live_share_with_a_poisoned_pending_row_still_scores_the_table(
    db: Session, app_engine: Engine, daily_player: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A member whose waiting result cannot be granted (a row that fails) sits at a live table. The share of the
    table's question, racing the job and another share, still pays every member their answer, once: the failing
    row is rolled back to its savepoint and left for the next try, and nothing is raised into the share."""
    daily_player.rank_points = 500.0
    db.commit()
    done = _answer_pending(db, daily_player, "mech")
    poisoned = db.get_one(Attempt, done).question_id
    code, _, table = _live_room(db, daily_player)
    live.answer(db, db.get_one(User, daily_player.id), code, [], None, False, NOW)
    session_id = db.scalar(select(LiveSession.id).where(LiveSession.code == code))
    assert session_id is not None

    def crit(_db: Session, _user: int, question: Any, _moment: Any) -> bool:
        if getattr(question, "id", question) == poisoned:
            raise RuntimeError("boom")
        return False

    monkeypatch.setattr(xp_service, "_crit", crit)
    results = race(
        app_engine,
        lambda s: live.share(s, session_id, LATER),
        lambda s: daily.settle_results(s, LATER),
        lambda s: live.share(s, session_id, LATER),
    )
    assert not [r for r in results if isinstance(r, Exception) and not isinstance(r, UserError)], results
    assert results[1] == (0, 1), results[1]  # counted as failed, not raised
    live.share(db, session_id, LATER)
    db.expire_all()
    lives = db.scalars(
        select(Attempt).where(Attempt.mode == "live").execution_options(populate_existing=True)
    ).all()
    assert sorted(a.user_id for a in lives) == sorted(u.id for u in table)  # every member, once
    assert all(a.xp > 0 for a in lives)
    row = db.get_one(Attempt, done, populate_existing=True)
    assert (row.settled_at, row.xp, row.lp) == (None, 0, 0)  # still waiting
    mine = next(a for a in lives if a.user_id == daily_player.id)
    player = db.get_one(User, daily_player.id, populate_existing=True)
    assert (player.xp, player.rank_points) == (mine.xp, 500.0)

    monkeypatch.setattr(xp_service, "_crit", lambda *_: False)  # the fault is gone
    assert daily.settle_results(db, LATER) == (1, 0)
    db.expire_all()
    row = db.get_one(Attempt, done, populate_existing=True)
    assert row.settled_at == LATER and row.xp > 0 and row.lp > 0
    player = db.get_one(User, daily_player.id, populate_existing=True)
    assert player.xp == row.xp + mine.xp and player.rank_points == pytest.approx(500 + row.lp)


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


def test_a_room_opening_a_board_at_once_adds_up_the_lp_once(
    db: Session, app_engine: Engine, daily_player: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    room = [daily_player] + [
        User(email=f"r{i}@x.com", password_hash="x", display_name=f"R{i}") for i in range(7)
    ]
    db.add_all(room[1:])
    db.commit()
    for u in room:
        q, a = daily.start(db, u, "mech", NOW)
        b = right_answer(db, q.id)
        daily.answer(db, u, a.id, b.get("options"), b.get("value"), NOW)
    sums: list[str | None] = []
    real = leaderboard._lp

    def slow(db: Session, first: date, area: str | None, only: int | None = None) -> dict[int, float]:
        if only is None:
            sums.append(area)
            time.sleep(0.05)  # everyone's sum late in a season
        return real(db, first, area, only)

    monkeypatch.setattr(leaderboard, "_lp", slow)
    ids = [u.id for u in room]
    boards = race(
        app_engine,
        *[lambda s, i=i: leaderboard.board(s, s.get_one(User, i), "mech", "season", NOW) for i in ids],
    )
    assert sums == ["mech"]
    assert [(b.players, b.me and b.me.rank) for b in boards] == [(len(room), 1)] * len(room)
