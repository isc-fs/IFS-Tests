# mypy: disable-error-code="misc"
# (lambdas bind loop variables as defaults, which mypy can't infer)
"""Admin actions, nightly jobs and account deletion racing players: no deadlocks, no 500s, ledgers that add up."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from ifs_tests.db.models import Attempt, AuditLog, MockSession, Question, User
from ifs_tests.domain import rank as rank_rules
from ifs_tests.services import accounts, daily, live, maintenance, mock, practice, privacy
from ifs_tests.services import xp as xp_service
from ifs_tests.services.errors import UserError

from ..api.helpers import right_answer
from .conftest import NOW
from .test_concurrency import race

pytestmark = pytest.mark.integration
SEASON = rank_rules.season_of(NOW)
CONFIG = {
    "questions": "areas",
    "areas": ["rules", "mech", "elec"],
    "count": 2,
    "timing": "fixed",
    "seconds": 600,
    "feedback": "end",
    "routing": "all",
    "speed_points": False,
}


def run_named(engine: Engine, jobs: dict[str, Callable[[Session], Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def go(name: str, fn: Callable[[Session], Any]) -> None:
        with sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                out[name] = fn(s)
            except Exception as e:  # noqa: BLE001
                s.rollback()
                out[name] = e

    threads = [threading.Thread(target=go, args=(n, f), name=n) for n, f in jobs.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return out


def unexpected(results: dict[str, Any] | list[Any]) -> list[Any]:
    vals = results.values() if isinstance(results, dict) else results
    return [
        r for r in vals if isinstance(r, Exception) and not isinstance(r, (UserError, accounts.AccountError))
    ]


def signed_in(s: Session, user_id: int) -> User:
    """For players a racing admin may delete before the harness looks them up: the app answers such a request
    401 before any service code runs, so a missing account is that 401, not a harness failure."""
    user = s.get(User, user_id)
    if user is None:
        raise UserError("Sign in first.", 401)
    return user


def mk(db: Session, n: int, prefix: str, **kw: Any) -> list[User]:
    users = [
        User(
            email=f"{prefix}{i}@x.com",
            password_hash="x",
            display_name=f"{prefix}{i}",
            rank_points=kw.get("rank_points", 500.0),
            rank_season=kw.get("rank_season", SEASON),
            rank_best=5,
            position=kw.get("position", "member"),
            role=kw.get("role", "member"),
            status=kw.get("status", "active"),
            left_at=kw.get("left_at"),
            streak_freezes=kw.get("streak_freezes", 0),
        )
        for i in range(n)
    ]
    db.add_all(users)
    db.commit()
    return users


def rehearsal(db: Session, host: User, tables: list[list[User]], feedback: str = "end") -> str:
    s = live.create(db, host, {**CONFIG, "feedback": feedback}, NOW)
    for t in tables:
        for u in t:
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
    return s.code


def pause_after(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    name: str,
    thread: str,
    hold: threading.Event,
    seconds: float = 1.5,
) -> None:
    real = getattr(module, name)

    def wrapped(*a: Any, **k: Any) -> Any:
        r = real(*a, **k)
        if threading.current_thread().name == thread and not hold.is_set():
            hold.set()
            time.sleep(seconds)
        return r

    monkeypatch.setattr(module, name, wrapped)


def check_ledger(db: Session, users: list[User], start: dict[int, tuple[int, float]]) -> list[str]:
    """xp = start + sum(attempt xp); rank = start + sum(attempt lp) (no floor hit at 500)."""
    bad = []
    for u in users:
        row = db.execute(select(User.xp, User.rank_points).where(User.id == u.id)).first()
        if row is None:
            continue
        sx, sp = db.execute(
            select(func.coalesce(func.sum(Attempt.xp), 0), func.coalesce(func.sum(Attempt.lp), 0)).where(
                Attempt.user_id == u.id
            )
        ).one()
        x0, p0 = start[u.id]
        if row.xp != x0 + sx or abs(float(row.rank_points) - (p0 + float(sp))) > 0.011:
            bad.append(f"user {u.id}: xp {row.xp} vs {x0}+{sx}; rank {row.rank_points} vs {p0}+{sp}")
    return bad


# 1. Admin row locks vs a live quiz sharing XP to an admin who plays


@pytest.mark.parametrize("action", ["position", "delete", "alumni"])
def test_admin_action_on_player_while_rehearsal_ends(
    db: Session, app_engine: Engine, daily_player: User, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    actor = mk(db, 1, "actor", role="admin")[0]
    host = mk(db, 1, "host", position="technical_director")[0]
    p, q = mk(db, 2, "p")  # lower ids than the admin player
    admin_player = mk(db, 1, "adm", role="admin")[0]
    code = rehearsal(db, host, [[p, admin_player], [q]])
    for cap in (p, q):
        live.answer(db, db.get_one(User, cap.id), code, [], None, False, NOW)
    hold = threading.Event()
    pause_after(monkeypatch, accounts, "_active_admin_ids", "admin", hold)
    pause_after(monkeypatch, privacy, "_active_admin_ids", "admin", hold)

    def admin(s: Session) -> Any:
        a = s.get_one(User, actor.id)
        if action == "position":
            return accounts.update_user(s, a, p.id, position="technical_director")
        if action == "delete":
            return privacy.delete_user(s, a, p.id, NOW)
        return privacy.mark_alumni(s, a, [p.id], NOW)

    def host_ends(s: Session) -> Any:
        hold.wait(5)
        time.sleep(0.2)
        return live.share(s, live.end(s, s.get_one(User, host.id), code, NOW), NOW)

    results = run_named(app_engine, {"admin": admin, "host": host_ends})
    assert not unexpected(results), results


# 2. Account deletion while the same player's answer is in flight (another tab, or an admin)


@pytest.mark.parametrize("mode", ["daily", "mock"])
def test_delete_while_answering(
    db: Session, app_engine: Engine, daily_player: User, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    actor = mk(db, 1, "actor", role="admin")[0]
    player = mk(db, 1, "pl")[0]
    if mode == "daily":
        _, a = daily.start(db, player, "rules", NOW)
        answer: Callable[[Session], Any] = lambda s: daily.answer(  # noqa: E731
            s, signed_in(s, player.id), a.id, None, "-1", NOW
        )
    else:
        run = mock.start(db, player, 9002, NOW)
        cur = mock.state(db, player, run.id, NOW).current
        assert cur is not None
        aid = cur[1].id
        answer = lambda s: mock.answer(s, signed_in(s, player.id), run.id, aid, [], None, NOW)  # noqa: E731
    hold = threading.Event()
    pause_after(monkeypatch, xp_service, "last_seen", "player", hold)

    def admin(s: Session) -> Any:
        hold.wait(5)
        return privacy.delete_user(s, s.get_one(User, actor.id), player.id, NOW)

    results = run_named(app_engine, {"player": answer, "admin": admin})
    assert not unexpected(results), results


# 3. mark_alumni locks users in physical order, the rehearsal in id order


def test_mark_alumni_physical_order_vs_rehearsal_end(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    actor = mk(db, 1, "actor", role="admin")[0]
    host = mk(db, 1, "host", position="technical_director")[0]
    x, y = mk(db, 2, "xy")
    # Rewrite x so its tuple lands after y's in the heap: a seq/bitmap scan now meets y first.
    for _ in range(3):
        db.execute(update(User).where(User.id == x.id).values(combo=User.combo))
        db.commit()
    order = db.scalars(
        text("select id from users where id in (:a, :b) order by ctid"), {"a": x.id, "b": y.id}
    ).all()
    assert order == [y.id, x.id]
    code = rehearsal(db, host, [[x, y]])
    live.answer(db, db.get_one(User, x.id), code, [], None, False, NOW)

    blocker_has, release = threading.Event(), threading.Event()

    def blocker(s: Session) -> None:
        s.execute(select(User.id).where(User.id == y.id).with_for_update(key_share=True))
        blocker_has.set()
        release.wait(5)
        s.commit()

    def alumni(s: Session) -> Any:
        blocker_has.wait(5)
        s.execute(text("SET LOCAL enable_indexscan = off"))
        s.execute(text("SET LOCAL enable_bitmapscan = on"))
        return privacy.mark_alumni(s, s.get_one(User, actor.id), [x.id, y.id], NOW)

    def host_ends(s: Session) -> Any:
        blocker_has.wait(5)
        time.sleep(0.4)
        return live.share(s, live.end(s, s.get_one(User, host.id), code, NOW), NOW)

    def releaser(s: Session) -> None:
        blocker_has.wait(5)
        time.sleep(0.9)
        release.set()

    results = run_named(
        app_engine, {"blocker": blocker, "alumni": alumni, "host": host_ends, "releaser": releaser}
    )
    assert not unexpected(results), results


# 4. The whole nightly job against a busy evening


def test_maintenance_run_against_players(db: Session, app_engine: Engine, daily_player: User) -> None:
    yesterday = NOW - timedelta(days=1)
    actor = mk(db, 1, "actor", role="admin")[0]
    host = mk(db, 1, "host", position="technical_director")[0]
    players = mk(db, 10, "pl", streak_freezes=1)
    old = mk(db, 3, "old", rank_season=SEASON - 1, rank_points=900.0)
    gone = mk(
        db, 2, "gone", status="alumni", left_at=NOW - timedelta(days=400), position="technical_director"
    )
    code_gone = live.create(
        db, gone[0], CONFIG, NOW - timedelta(days=500)
    ).code  # alumni host, never finished
    # Abandoned dailies yesterday, abandoned mock runs
    for u in players[:5] + old:
        daily.start(db, u, "mech", yesterday)
    for u in players[5:8]:
        r = mock.start(db, u, 9002, yesterday)
        mock.state(db, u, r.id, yesterday)
    # Players with a daily open today, answering during the job
    today = {u.id: daily.start(db, u, "rules", NOW)[1].id for u in players[:5] + old}
    # A rehearsal ending during the job; admin actor sits in it
    code = rehearsal(db, host, [[players[0], players[2], players[4]], [players[1], players[3], players[9]]])
    for cap in (players[0], players[1]):
        live.answer(db, db.get_one(User, cap.id), code, [], None, False, NOW)
    graded = list(db.scalars(select(Question.id).where(Question.graded, Question.playable).limit(8)))
    everyone = players + old
    start = {u.id: (0, 0.0) for u in everyone}
    db.execute(update(Attempt).values(xp=0, lp=0))
    db.execute(update(User).where(User.id.in_([u.id for u in everyone])).values(xp=0))
    db.commit()
    start = {
        u.id: (0, float(db.scalar(select(User.rank_points).where(User.id == u.id)) or 0)) for u in everyone
    }
    later = NOW + timedelta(minutes=30)

    jobs: list[Callable[[Session], Any]] = [lambda s: maintenance.run(s, later)]
    for u in players[:5] + old:
        jobs.append(lambda s, u=u: daily.answer(s, s.get_one(User, u.id), today[u.id], None, "-1", NOW))
    for u, q in zip(players, graded, strict=False):
        jobs.append(
            lambda s, u=u, q=q: practice.answer(
                s,
                s.get_one(User, u.id),
                q,
                right_answer(s, q).get("options"),
                right_answer(s, q).get("value"),
                later,
            )
        )
    jobs.append(lambda s: live.share(s, live.end(s, s.get_one(User, host.id), code, later), later))
    jobs.append(
        lambda s: accounts.update_user(
            s, s.get_one(User, actor.id), players[2].id, position="technical_director"
        )
    )
    jobs.append(lambda s: privacy.mark_alumni(s, s.get_one(User, actor.id), [players[9].id], later))
    for u in players[5:8]:
        jobs.append(
            lambda s, u=u: mock.state(
                s,
                s.get_one(User, u.id),
                s.scalar(select(MockSession.id).where(MockSession.user_id == u.id)),
                later,
            )
        )
    results = race(app_engine, *jobs)
    bad = unexpected(results)
    assert not bad, bad
    db.expire_all()
    # the season rollover for `old` happened before or during their answer: rank = reset + LP
    for u in old:
        p0 = rank_rules.season_reset(900.0, "member")
        start[u.id] = (0, p0)
    # position change lifts players[2] to placement 1050 at some point: skip it from the ledger
    ledger = [u for u in everyone if u.id != players[2].id]
    problems = check_ledger(db, ledger, start)
    assert not problems, problems
    assert db.scalar(select(func.count()).where(User.email.like("gone%"))) == 0
    assert (
        db.scalar(
            select(func.count()).where(
                Attempt.submitted_at.is_(None), Attempt.deadline_at < later - timedelta(seconds=10)
            )
        )
        == 0
    )
    _ = code_gone


def test_two_maintenance_runs_at_once(db: Session, app_engine: Engine, daily_player: User) -> None:
    yesterday = NOW - timedelta(days=1)
    players = mk(db, 8, "pl", streak_freezes=1)
    for u in players:
        daily.start(db, u, "mech", yesterday)
        daily.start(db, u, "elec", yesterday)
    # Make lots of questions due for recalibration: 25 players answering the same questions right
    many = mk(db, 25, "many")
    qs = list(db.scalars(select(Question.id).where(Question.graded, Question.playable).limit(6)))
    for u in many:
        for q in qs:
            db.add(
                Attempt(
                    user_id=u.id,
                    question_id=q,
                    mode="practice",
                    answer={},
                    correct=True,
                    created_at=yesterday,
                )
            )
    db.commit()
    results = race(app_engine, *[lambda s: maintenance.run(s, NOW)] * 3)
    assert not unexpected(results), results


# 5. Two tabs of one player, every mode at once


def test_one_player_every_mode_at_once(db: Session, app_engine: Engine, daily_player: User) -> None:
    p = mk(db, 1, "solo")[0]
    started = [daily.start(db, p, a, NOW)[1].id for a in ("mech", "elec", "rules")]
    run = mock.start(db, p, 9002, NOW)
    cur = mock.state(db, p, run.id, NOW).current
    assert cur is not None
    db.execute(update(Attempt).values(xp=0, lp=0))
    db.commit()
    qs = list(db.scalars(select(Question.id).where(Question.graded, Question.playable).offset(10).limit(4)))
    jobs: list[Callable[[Session], Any]] = [
        (lambda s, a=a: daily.answer(s, s.get_one(User, p.id), a, None, "-1", NOW)) for a in started
    ]
    jobs += [lambda s: mock.answer(s, s.get_one(User, p.id), run.id, cur[1].id, [], None, NOW)] * 2
    jobs += [(lambda s, q=q: practice.answer(s, s.get_one(User, p.id), q, None, "-1", NOW)) for q in qs]
    jobs += [lambda s: daily.status(s, s.get_one(User, p.id), NOW)] * 2
    results = race(app_engine, *jobs)
    assert not unexpected(results), results
    db.expire_all()
    p0 = db.get_one(User, p.id)
    assert not check_ledger(db, [p], {p.id: (0, 500.0)}), check_ledger(db, [p], {p.id: (0, 500.0)})
    assert p0.miss_streak <= 99 and p0.combo == 0


# 6. Live: several tables answering with feedback each, overlapping deletions and host ending


# Repeated: deleting players while their tables propose deadlocked about 1 run in 6 when sessions were locked FOR
# UPDATE (the deletion's foreign-key check queued behind requests waiting for the session). Eight rounds make a
# regression all but certain to fail.
@pytest.mark.parametrize("round_", range(8))
def test_live_many_tables_each_feedback_with_deletion_and_end(
    db: Session, app_engine: Engine, daily_player: User, round_: int
) -> None:
    actor = mk(db, 1, "actor", role="admin")[0]
    host = mk(db, 1, "host", position="technical_director")[0]
    ps = mk(db, 16, "lp")
    tables = [ps[i::4] for i in range(4)]  # interleaved ids across tables
    code = rehearsal(db, host, tables, feedback="each")
    jobs: list[Callable[[Session], Any]] = [
        (lambda s, t=t: live.share(s, live.answer(s, signed_in(s, t[0].id), code, [], None, False, NOW), NOW))
        for t in tables
    ]
    jobs += [
        (lambda s, u=u: live.propose(s, signed_in(s, u.id), code, {"options": [], "value": None}, NOW))
        for t in tables
        for u in t[1:3]
    ]
    jobs.append(lambda s: privacy.delete_user(s, s.get_one(User, actor.id), tables[1][2].id, NOW))
    jobs.append(
        lambda s: privacy.delete_user(s, s.get_one(User, actor.id), tables[2][0].id, NOW)
    )  # a captain
    jobs.append(lambda s: live.view(s, s.get_one(User, host.id), code, NOW))
    results = race(app_engine, *jobs)
    assert not unexpected(results), results
    targets = {tables[1][2].id, tables[2][0].id}
    left = set(db.scalars(select(User.id).where(User.id.in_([u.id for u in ps]))))
    assert left >= {u.id for u in ps} - targets  # signed_in's 401 only ever stands for a deleted target
    live.share(db, live.end(db, db.get_one(User, host.id), code, NOW), NOW)
    # nobody got XP twice for the question
    dup = db.execute(
        select(Attempt.user_id, Attempt.question_id, func.count())
        .where(Attempt.mode == "live")
        .group_by(Attempt.user_id, Attempt.question_id)
        .having(func.count() > 1)
    ).all()
    assert not dup, dup


def test_host_deleted_mid_quiz_while_captains_answer(
    db: Session, app_engine: Engine, daily_player: User
) -> None:
    actor = mk(db, 1, "actor", role="admin")[0]
    host = mk(db, 1, "host", position="technical_director", role="admin")[0]
    ps = mk(db, 9, "hp")
    tables = [ps[i::3] for i in range(3)]
    code = rehearsal(db, host, tables, feedback="end")
    jobs: list[Callable[[Session], Any]] = [
        (
            lambda s, t=t: live.share(
                s, live.answer(s, s.get_one(User, t[0].id), code, [], None, False, NOW), NOW
            )
        )
        for t in tables
    ]
    jobs.append(lambda s: privacy.delete_user(s, s.get_one(User, actor.id), host.id, NOW))
    jobs += [
        (
            lambda s, u=u: practice.answer(
                s,
                s.get_one(User, u.id),
                s.scalars(select(Question.id).where(Question.graded, Question.playable)).first(),
                None,
                "-1",
                NOW,
            )
        )
        for u in ps[:5]
    ]
    results = race(app_engine, *jobs)
    assert not unexpected(results), results


def test_rollover_and_nightly_vs_answers(db: Session, app_engine: Engine, daily_player: User) -> None:
    from ifs_tests.services import season, streaks

    ps = mk(db, 12, "ro", rank_season=SEASON - 1, rank_points=900.0, streak_freezes=1)
    qs = list(db.scalars(select(Question.id).where(Question.graded, Question.playable).limit(12)))
    jobs: list[Callable[[Session], Any]] = [
        lambda s: season.rollover(s, NOW),
        lambda s: streaks.nightly(s, NOW),
    ]
    jobs += [
        (lambda s, u=u, q=q: practice.answer(s, s.get_one(User, u.id), q, None, "-1", NOW))
        for u, q in zip(ps, qs, strict=False)
    ]
    jobs += [
        (
            lambda s, u=u: daily.answer(
                s,
                s.get_one(User, u.id),
                daily.start(s, s.get_one(User, u.id), "mech", NOW)[1].id,
                None,
                "-1",
                NOW,
            )
        )
        for u in ps[:6]
    ]
    results = race(app_engine, *jobs)
    assert not unexpected(results), results
    reset = rank_rules.season_reset(900.0, "member")
    problems = check_ledger(db, ps, {u.id: (0, reset) for u in ps})
    assert not problems, problems


def test_position_change_vs_answers(db: Session, app_engine: Engine, daily_player: User) -> None:
    actor = mk(db, 1, "actor", role="admin")[0]
    ps = mk(db, 8, "pos")
    # "-1" is a wrong answer to every question but a list, which refuses it as unreadable.
    graded = select(Question.id).where(Question.graded, Question.playable, Question.answer_kind != "numbers")
    qs = list(db.scalars(graded.limit(8)))
    jobs: list[Callable[[Session], Any]] = []
    for u, q in zip(ps, qs, strict=False):
        jobs.append(
            lambda s, u=u: accounts.update_user(
                s, s.get_one(User, actor.id), u.id, position="technical_director"
            )
        )
        jobs.append(lambda s, u=u, q=q: practice.answer(s, s.get_one(User, u.id), q, None, "-1", NOW))
    results = race(app_engine, *jobs)
    assert not unexpected(results), results
    for u in ps:
        final = db.scalar(
            select(User.rank_points).where(User.id == u.id).execution_options(populate_existing=True)
        )
        lp = db.scalar(select(Attempt.lp).where(Attempt.user_id == u.id))
        assert final is not None and lp is not None
        placed = rank_rules.placement("technical_director")
        assert any(abs(final - v) < 0.011 for v in (placed, placed + lp)), (final, lp)


def signed_in_then(engine: Engine, jobs: list[tuple[int, Callable[[Session, User], Any]]]) -> list[Any]:
    """Each job's actor is loaded first, as the request's session check does, then they all act at once."""
    barrier = threading.Barrier(len(jobs))
    out: list[Any] = [None] * len(jobs)

    def go(i: int) -> None:
        actor_id, act = jobs[i]
        with sessionmaker(engine, expire_on_commit=False)() as s:
            me = s.get_one(User, actor_id)
            s.commit()
            barrier.wait()
            try:
                out[i] = act(s, me)
            except Exception as e:  # noqa: BLE001
                s.rollback()
                out[i] = e

    threads = [threading.Thread(target=go, args=(i,)) for i in range(len(jobs))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return out


@pytest.mark.parametrize("action", ["demote", "delete"])
def test_two_of_three_admins_acting_on_each_other_at_once(
    db: Session, app_engine: Engine, action: str
) -> None:
    """With three admins the last-admin rule doesn't stop it: the one who acts second is no admin by then."""
    a, b = (u.id for u in mk(db, 3, "boss", role="admin")[:2])

    def act(target: int) -> Callable[[Session, User], Any]:
        if action == "demote":
            return lambda s, me: accounts.update_user(s, me, target, role="member", now=NOW)
        return lambda s, me: privacy.delete_user(s, me, target, NOW)

    results = signed_in_then(app_engine, [(a, act(b)), (b, act(a))])
    assert not unexpected(results), results
    refused = [r for r in results if isinstance(r, accounts.AccountError)]
    assert len(refused) == 1 and refused[0].status == 403, results
    db.expire_all()
    left = db.scalars(
        select(User.id).where(User.id.in_([a, b]), User.role == "admin", User.status == "active")
    ).all()
    assert len(left) == 1
    actors = set(
        db.scalars(select(AuditLog.actor_id).where(AuditLog.action.in_(["user.update", "user.delete"])))
    )
    assert actors == set(left)  # the change is by the admin who is still one
