"""Daily question: one per area per Madrid day, one try, against the clock; shared until season 1b and drawn
per player from it (ADR 0010). The server owns every deadline; the browser only displays it."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, exists, func, or_, select, text, union, union_all, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DB

from ..db.models import DAILY, Attempt, DailyQuestion, LiveQuestion, LiveSession, Question, User
from ..domain import daily as rules
from ..domain import signals as signal_rules
from ..domain.leaderboard import madrid_midnight
from . import hints, signals, streaks, xp
from .errors import UserError
from .questions import Checked, check, explain, running

LOCK = 0x1F5DA11  # pg advisory lock key for choosing the day's questions
DRAW_LOCK = 0x1F5DA12  # first key of the two-key lock a per-player draw takes, per day and area
log = logging.getLogger(__name__)


def _running_since(db: DB, day: date, area: str | None, question_id: int) -> datetime:
    """When the day's question in `area` started running for players, never before that day's midnight: when it
    was drawn (a reviewer's redraw included; rows drawn before `drawn_at` existed: midnight). On a per-player
    day there is no row, and it is when the first player started this question that day."""
    row = db.execute(
        select(DailyQuestion.drawn_at).where(DailyQuestion.day == day, DailyQuestion.area == area)
    ).first()
    midnight = madrid_midnight(day)
    if row is not None:
        return max(midnight, row[0]) if row[0] else midnight
    first = db.scalar(
        select(func.min(Attempt.created_at)).where(
            DAILY, Attempt.question_id == question_id, Attempt.day == day
        )
    )
    return max(midnight, first) if first else midnight


def is_per_player(db: DB, day: date, rules_from: date | None) -> bool:
    """Whether `day` is drawn per player: on or after the switch, and with no shared draw already made. A day
    that has a shared draw stays shared to its end, so a late deploy or a changed setting never switches
    mid-day: the switch always happens at a Madrid midnight."""
    return rules.per_player(day, rules_from) and not db.scalar(
        select(exists().where(DailyQuestion.day == day))
    )


def ensure_daily(db: DB, day: date, now: datetime) -> dict[str, int]:
    """Choose the day's questions once; concurrent callers wait for the first and reuse its choice.
    A chosen question that a reviewer hid (or that stopped being gradable) is replaced for everyone who
    hasn't started it yet; people who did keep theirs."""
    chosen = _chosen(db, day)
    if len(chosen) == len(rules.AREAS):
        return chosen
    db.execute(select(func.pg_advisory_xact_lock(LOCK)))
    chosen = _chosen(db, day)
    last = (
        select(DailyQuestion.question_id, func.max(DailyQuestion.day).label("last"))
        .group_by(DailyQuestion.question_id)
        .subquery()
    )
    tried = select(Attempt.question_id, func.count().label("n")).group_by(Attempt.question_id).subquery()
    for area in rules.AREAS:
        if area in chosen:
            continue
        rows = db.execute(
            select(Question.id, last.c.last, func.coalesce(tried.c.n, 0))
            .outerjoin(last, last.c.question_id == Question.id)
            .outerjoin(tried, tried.c.question_id == Question.id)
            .where(Question.area == area, Question.playable, Question.graded)
        )
        qid = rules.pick([rules.Candidate(i, used, n) for i, used, n in rows], day, area, hints.salt(db))
        if qid is not None:
            db.execute(
                insert(DailyQuestion)
                .values(day=day, area=area, question_id=qid, drawn_at=now)
                .on_conflict_do_update(
                    index_elements=["day", "area"], set_={"question_id": qid, "drawn_at": now}
                )
            )
            chosen[area] = qid
    db.commit()
    return chosen


def _draw_lock(db: DB, day: date, area: str) -> None:
    """Players drawing in one area take turns until their attempt is stored, so each sees what the others drew
    (the spread). Without it, two accounts starting in the same instant would draw from the same state and could
    be given one question on purpose. Taken after the player's own row, which is the order deleting an account
    takes: nobody waits on a row while holding this."""
    db.execute(select(func.pg_advisory_xact_lock(DRAW_LOCK, day.toordinal() * 4 + rules.AREAS.index(area))))


def draw(db: DB, user: User, day: date, now: datetime, areas: list[str]) -> dict[str, int]:
    """The player's questions for `areas` on a per-player day (rules.pick_for). Nothing is stored. What the
    player has seen is as of midnight, so nothing opened today (a mock run, a page) changes the draw; only what
    they have already answered today moves it, and only away from those questions, which would pay nothing.
    `start` takes the area's draw lock around this and the insert; the status preview takes none, so it is a
    preview: another player's start can change it."""
    midnight = madrid_midnight(day)
    drawn = (
        select(
            Attempt.question_id,
            func.count().label("n"),
            func.count().filter(Attempt.submitted_at.is_not(None)).label("done"),
        )
        .where(
            DAILY,
            or_(
                Attempt.day == day,
                and_(
                    Attempt.day == day - timedelta(days=1),
                    Attempt.submitted_at.is_(None),
                    Attempt.deadline_at >= now - rules.GRACE,
                ),
            ),
        )
        .group_by(Attempt.question_id)
        .subquery()
    )
    ever = union_all(
        select(DailyQuestion.question_id, DailyQuestion.day),
        select(Attempt.question_id, Attempt.day).where(DAILY, Attempt.day.is_not(None)),
    ).subquery()
    last_drawn = (
        select(ever.c.question_id, func.max(ever.c.day).label("day")).group_by(ever.c.question_id).subquery()
    )
    seen = xp.seen_this_season(user.id, now, before=midnight).subquery()
    played = (  # xp.answered_today's rule
        select(Attempt.question_id)
        .where(
            Attempt.user_id == user.id,
            Attempt.created_at >= midnight,
            Attempt.submitted_at.is_not(None) | (Attempt.mode == "practice"),
        )
        .distinct()
        .subquery()
    )
    on_screen = union(
        select(LiveQuestion.question_id)
        .join(LiveSession, LiveSession.id == LiveQuestion.session_id)
        .where(LiveSession.state != "finished"),
        select(Attempt.question_id).where(
            Attempt.mode == "mock", Attempt.submitted_at.is_(None), Attempt.deadline_at >= now - rules.GRACE
        ),
    ).subquery()
    rows = db.execute(
        select(
            Question.area,
            Question.id,
            exists().where(on_screen.c.question_id == Question.id),
            exists().where(played.c.question_id == Question.id),
            func.coalesce(drawn.c.n, 0),
            func.coalesce(drawn.c.done, 0),
            last_drawn.c.day,
            seen.c.at,
        )
        .outerjoin(drawn, drawn.c.question_id == Question.id)
        .outerjoin(last_drawn, last_drawn.c.question_id == Question.id)
        .outerjoin(seen, seen.c.question_id == Question.id)
        .where(Question.area.in_(areas), Question.playable, Question.graded)
    ).all()
    by_area: dict[str, list[rules.PlayerCandidate]] = {}
    for area, qid, reserved, played_today, n, done, last, seen_at in rows:
        by_area.setdefault(area, []).append(
            rules.PlayerCandidate(
                qid, reserved, played_today, n, done, last, rules.madrid_day(seen_at) if seen_at else None
            )
        )
    secret = hints.salt(db)
    chosen = {area: rules.pick_for(c, day, area, user.id, secret) for area, c in by_area.items()}
    return {area: qid for area, qid in chosen.items() if qid is not None}


def scheduled(db: DB, at: datetime, *, rules_from: date | None) -> dict[str, int]:
    """The 00:01 job: the day's shared draw, which a per-player day doesn't have."""
    day = rules.madrid_day(at)
    if is_per_player(db, day, rules_from):
        log.info("per-player day: no shared draw")
        return {}
    return ensure_daily(db, day, at)


def _chosen(db: DB, day: date) -> dict[str, int]:
    """The day's questions that can still be served."""
    rows = db.execute(
        select(DailyQuestion.area, DailyQuestion.question_id)
        .join(Question, Question.id == DailyQuestion.question_id)
        .where(DailyQuestion.day == day, Question.playable, Question.graded)
    )
    return {area: qid for area, qid in rows}


def _mine(user: User, day: date, area: str) -> Select[tuple[Attempt]]:
    return select(Attempt).where(
        Attempt.user_id == user.id, Attempt.mode == "daily", Attempt.day == day, Attempt.area == area
    )


def _attempt(db: DB, user: User, day: date, area: str) -> Attempt | None:
    return db.scalar(_mine(user, day, area))


def _carried(db: DB, user: User, day: date, now: datetime) -> dict[str, Attempt]:
    """Daily questions started on an earlier day and still inside their clock: a question started at 23:59
    belongs to its day, and stays on the page until it is answered or runs out."""
    rows = db.scalars(
        select(Attempt).where(
            Attempt.user_id == user.id,
            Attempt.mode == "daily",
            Attempt.day < day,
            Attempt.submitted_at.is_(None),
        )
    )
    return {a.area: a for a in rows if a.area and a.deadline_at and not rules.is_late(now, a.deadline_at)}


def _carried_done(db: DB, user: User, day: date) -> dict[str, Attempt]:
    """Daily questions from an earlier day answered (or run out) since midnight: their result stays on the page,
    and can be reviewed, until the new day's question in that area is started."""
    rows = db.scalars(
        select(Attempt)
        .where(
            Attempt.user_id == user.id,
            Attempt.mode == "daily",
            Attempt.day < day,
            Attempt.submitted_at >= madrid_midnight(day),
        )
        .order_by(Attempt.id)
    )
    return {a.area: a for a in rows if a.area}


def _on_time_days(db: DB, user: User, now: datetime) -> set[date]:
    return streaks.current(db, user.id, now)


@dataclass
class AreaState:
    area: str
    day: date  # the day the question belongs to: yesterday's for one started before midnight
    budget_s: int
    state: str  # "new", "started" or "done"
    deadline_at: datetime | None
    correct: bool | None
    late: bool | None
    passed: bool
    xp: int
    lp: float


@dataclass
class Status:
    day: date
    streak: int
    xp_today: int
    lp_today: float
    areas: list[AreaState]


def status(db: DB, user: User, now: datetime, *, rules_from: date | None = None) -> Status:
    close_expired(db, now, user.id)
    day = rules.madrid_day(now)
    gated = is_per_player(db, day, rules_from)
    chosen = {} if gated else ensure_daily(db, day, now)
    today: dict[str | None, Attempt] = {
        a.area: a
        for a in db.scalars(
            select(Attempt).where(Attempt.user_id == user.id, Attempt.mode == "daily", Attempt.day == day)
        )
    }
    carried = _carried(db, user, day, now)
    mine = _carried_done(db, user, day) | carried | today
    if gated:  # a preview: nothing is stored, the question and its clock come with the start
        chosen = draw(db, user, day, now, [x for x in rules.AREAS if x not in mine])
        db.commit()  # the draw secret, if it was just stored, must outlive this read so the start agrees
    offered = set(chosen) | {a for a in mine if a}
    areas = []
    for area in sorted(offered):
        a = mine.get(area)
        q = db.get_one(Question, a.question_id if a else chosen[area])
        budget_s = rules.budget(q.time_s, q.answer_kind)
        state = "new" if a is None else "done" if a.submitted_at else "started"
        areas.append(
            AreaState(
                area=area,
                day=a.day if a and a.day else day,
                budget_s=budget_s,
                state=state,
                deadline_at=a.deadline_at if a else None,
                correct=a.correct if a else None,
                late=a.late if a else None,
                passed=bool(a and a.passed),
                xp=a.xp if a else 0,
                lp=a.lp if a else 0.0,
            )
        )
    order = {a: i for i, a in enumerate(rules.AREAS)}
    areas.sort(key=lambda s: order[s.area])
    kept = _on_time_days(db, user, now)
    # A day whose question is still running is still open, like today.
    run = max([rules.streak(kept, d) for d in {day} | {a.day for a in carried.values() if a.day}])
    own = [a for a in areas if a.day == day]  # a carried question's result counts for its own day
    return Status(day, run, sum(a.xp for a in own), round(sum(a.lp for a in own), 2), areas)


def _resumed(db: DB, a: Attempt, now: datetime, policy: signal_rules.Policy) -> None:
    """Count a reopening of a running question, on the row itself (no lock: one atomic update)."""
    if not policy.collect or not signal_rules.is_resume(a.created_at, now):
        return
    if a.deadline_at and rules.is_late(now, a.deadline_at):  # no longer running: not a reopening
        return
    db.execute(
        update(Attempt)
        .where(Attempt.id == a.id, Attempt.submitted_at.is_(None), Attempt.resumes.is_not(None))
        .values(resumes=func.least(Attempt.resumes + 1, signal_rules.MAX_COUNT))
    )
    db.commit()
    db.refresh(a)


def start(
    db: DB,
    user: User,
    area: str,
    now: datetime,
    policy: signal_rules.Policy = signal_rules.OFF,
    *,
    rules_from: date | None = None,
) -> tuple[Question, Attempt]:
    """Start the clock, or return the running attempt. The question is only revealed from here; on a per-player
    day it is drawn here, one player at a time per area. Parallel requests of one player queue on their row, and
    every response returns the stored attempt."""
    day = rules.madrid_day(now)
    gated = is_per_player(db, day, rules_from)
    if gated:
        xp.lock(db, user.id)  # one start at a time per player, and a deletion in flight ends in 401
    existing = _carried(db, user, day, now).get(area) or _attempt(db, user, day, area)
    if existing is not None:
        if existing.submitted_at:
            raise UserError("You've already answered today's question for this area.", 409)
        _resumed(db, existing, now, policy)
        return db.get_one(Question, existing.question_id), existing
    if gated:
        _draw_lock(db, day, area)  # held until the attempt below is committed
        qid = draw(db, user, day, now, [area]).get(area)
    else:
        qid = ensure_daily(db, day, now).get(area)
    if qid is None:
        raise UserError("There's no daily question for this area today.", 404)
    q = db.get_one(Question, qid)
    if q.id in running(db, user.id, now, daily=False, on_screen=gated):
        raise UserError(
            "This question is running in your mock or live quiz: answer it there first (then it pays nothing more "
            "here today), or end the mock run (it counts as out of time there, and this one still pays in full).",
            409,
        )
    try:
        db.execute(
            insert(Attempt)
            .values(
                user_id=user.id,
                question_id=q.id,
                mode="daily",
                answer={},
                created_at=now,
                day=day,
                area=area,
                deadline_at=now + timedelta(seconds=rules.budget(q.time_s, q.answer_kind)),
                resumes=0 if policy.collect else None,
                decoy_option_id=signals.decoy_for(db, q, policy),
            )
            # A literal predicate: once psycopg prepares the statement, a bound parameter here stops
            # Postgres matching the partial unique index and the insert fails.
            .on_conflict_do_nothing(
                index_elements=["user_id", "day", "area"], index_where=text("mode = 'daily'")
            )
        )
        db.commit()
    except IntegrityError:  # the account was deleted while this request drew
        db.rollback()
        raise UserError("This account no longer exists.", 401) from None
    started = db.scalars(_mine(user, day, area)).one()  # ours, or a parallel request's
    return db.get_one(Question, started.question_id), started


@dataclass
class Result:
    day: date
    question: Question
    checked: Checked
    late: bool
    xp: int
    lp: float
    streak: int
    answer: dict[str, Any]


def answer(
    db: DB,
    user: User,
    attempt_id: int,
    options: list[int] | None,
    value: str | None,
    now: datetime,
    unsure: bool = False,
    signals: signal_rules.Signals | None = None,
    policy: signal_rules.Policy = signal_rules.OFF,
) -> Result:
    """Submit once. Late answers are recorded and count as wrong; repeats return the stored result."""
    a = db.scalar(
        select(Attempt).where(Attempt.id == attempt_id, Attempt.user_id == user.id, Attempt.mode == "daily")
    )
    if a is None or a.day is None or a.deadline_at is None:
        raise UserError("Start the question first.", 404)
    granted = None
    if a.submitted_at is None:
        xp.lock(db, user.id)  # the player, then the attempt: the order deleting an account takes
        q = db.get_one(Question, a.question_id)
        checked = check(db, q, options, value, unsure)
        late = rules.is_late(now, a.deadline_at)
        reported = signals if policy.collect and a.resumes is not None else None
        recorded = db.execute(
            update(Attempt)
            .where(Attempt.id == a.id, Attempt.submitted_at.is_(None))
            .values(
                answer={"options": options, "value": value, "unsure": checked.passed},
                correct=checked.correct,
                submitted_at=now,
                late=late,
                passed=checked.passed,
                **signal_rules.stored(
                    reported, signal_rules.elapsed_s(a.created_at, a.deadline_at, now), q.answer_kind
                ),
            )
            .returning(Attempt.id)
        ).first()
        if recorded:  # only the request that recorded the answer earns the XP
            hidden = _running_since(db, a.day, a.area, q.id)  # see xp._hidden_mock
            repeat = xp.last_seen(db, user.id, q.id, now, other_than=a.id, hidden_since=hidden) is not None
            granted = xp.grant(
                db,
                user.id,
                q,
                "daily",
                checked.correct,
                now,
                late=late,
                repeat=repeat,
                passed=checked.passed,
                hint=a.hint_used,
                again_today=xp.answered_today(db, user.id, q.id, now, other_than=a.id, hidden_since=hidden),
                season_at=a.created_at,
                played_on=a.day,
            )
            db.execute(update(Attempt).where(Attempt.id == a.id).values(xp=granted.xp, lp=granted.lp))
        db.refresh(a)  # while the player's lock still keeps the account, and so this attempt, in place
        db.commit()
    result = review_attempt(db, user, a, now)
    if (
        granted
    ):  # the request that scored it tells of promotions and bonuses; reloads show the stored XP and LP
        result.checked.score = granted
    return result


def close_expired(db: DB, now: datetime, user_id: int | None = None) -> int:
    """Close daily questions left to run out: late and wrong, like an answer sent after the time.
    Otherwise closing the tab on a hard question would dodge the XP a wrong answer costs."""
    stmt = (
        select(
            Attempt.id, Attempt.question_id, Attempt.user_id, Attempt.created_at, Attempt.day, Attempt.area
        )
        .where(
            Attempt.mode == "daily", Attempt.submitted_at.is_(None), Attempt.deadline_at < now - rules.GRACE
        )
        .order_by(Attempt.user_id, Attempt.id)
    )
    if user_id is not None:
        stmt = stmt.where(Attempt.user_id == user_id)
    closed = 0
    for attempt_id, question_id, owner, started, day, area in db.execute(stmt).all():
        xp.lock(db, owner)
        q = db.get_one(Question, question_id)
        correct = False if q.graded else None
        recorded = db.execute(
            update(Attempt)
            .where(Attempt.id == attempt_id, Attempt.submitted_at.is_(None))
            .values(correct=correct, submitted_at=now, late=True)
            .returning(Attempt.id)
        ).first()
        if recorded:
            hidden = _running_since(db, day or rules.madrid_day(started), area, q.id)
            repeat = (
                xp.last_seen(db, owner, q.id, now, other_than=attempt_id, hidden_since=hidden) is not None
            )
            granted = xp.grant(
                db,
                owner,
                q,
                "daily",
                correct,
                now,
                answered=False,
                late=True,
                repeat=repeat,
                season_at=started,
            )
            db.execute(update(Attempt).where(Attempt.id == attempt_id).values(xp=granted.xp, lp=granted.lp))
            closed += 1
        db.commit()  # one attempt per transaction: player, then attempt, the order answering takes
    return closed


def review_attempt(db: DB, user: User, a: Attempt, now: datetime) -> Result:
    """The stored result of a submitted attempt: retries and reloads never re-grade."""
    q = db.get_one(Question, a.question_id)
    checked = explain(db, q, a.correct, a.passed)
    run = rules.streak(_on_time_days(db, user, now), a.day) if a.day else 0
    checked.score = xp.stored(db, user.id, a)
    assert a.day is not None  # noqa: S101 - every daily attempt has its day
    return Result(a.day, q, checked, bool(a.late), a.xp, a.lp, run, a.answer)


def review(db: DB, user: User, area: str, now: datetime) -> Result:
    """Today's answer in this area; before today's question is started, one from yesterday answered (or run
    out) since midnight."""
    day = rules.madrid_day(now)
    a = _attempt(db, user, day, area) or _carried_done(db, user, day).get(area)
    if a is None or a.submitted_at is None:
        raise UserError("Answer today's question first.", 409)
    return review_attempt(db, user, a, now)
