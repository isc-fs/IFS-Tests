"""Daily question: one per area per Madrid day, one try, against the clock. The server owns every
deadline; the browser only displays it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import Select, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DB

from ..db.models import Attempt, DailyQuestion, Question, User
from ..domain import daily as rules
from . import streaks, xp
from .errors import UserError
from .questions import Checked, check

LOCK = 0x1F5DA11  # pg advisory lock key for choosing the day's questions


def ensure_daily(db: DB, day: date) -> dict[str, int]:
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
        qid = rules.pick([rules.Candidate(i, used, n) for i, used, n in rows], day, area)
        if qid is not None:
            db.execute(
                insert(DailyQuestion)
                .values(day=day, area=area, question_id=qid)
                .on_conflict_do_update(index_elements=["day", "area"], set_={"question_id": qid})
            )
            chosen[area] = qid
    db.commit()
    return chosen


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


def _on_time_days(db: DB, user: User) -> set[date]:
    return streaks.kept(db, user.id)


@dataclass
class AreaState:
    area: str
    budget_s: int
    state: str  # "new", "started" or "done"
    deadline_at: datetime | None
    correct: bool | None
    late: bool | None
    xp: int
    lp: float


@dataclass
class Status:
    day: date
    streak: int
    xp_today: int
    lp_today: float
    areas: list[AreaState]


def status(db: DB, user: User, now: datetime) -> Status:
    close_expired(db, now, user.id)
    day = rules.madrid_day(now)
    chosen = ensure_daily(db, day)
    mine = {
        a.area: a
        for a in db.scalars(
            select(Attempt).where(Attempt.user_id == user.id, Attempt.mode == "daily", Attempt.day == day)
        )
    }
    areas = []
    for area in sorted(set(chosen) | {a for a in mine if a}):
        a = mine.get(area)
        q = db.get_one(Question, a.question_id if a else chosen[area])
        state = "new" if a is None else "done" if a.submitted_at else "started"
        areas.append(
            AreaState(
                area=area,
                budget_s=rules.budget(q.time_s, q.answer_kind),
                state=state,
                deadline_at=a.deadline_at if a else None,
                correct=a.correct if a else None,
                late=a.late if a else None,
                xp=a.xp if a else 0,
                lp=a.lp if a else 0.0,
            )
        )
    order = {a: i for i, a in enumerate(rules.AREAS)}
    areas.sort(key=lambda s: order[s.area])
    run = rules.streak(_on_time_days(db, user), day)
    return Status(day, run, sum(a.xp for a in areas), round(sum(a.lp for a in areas), 2), areas)


def start(db: DB, user: User, area: str, now: datetime) -> tuple[Question, Attempt]:
    """Start the clock, or return the running attempt. The question is only revealed from here."""
    day = rules.madrid_day(now)
    existing = _attempt(db, user, day, area)
    if existing is not None:
        if existing.submitted_at:
            raise UserError("You've already answered today's question for this area.", 409)
        return db.get_one(Question, existing.question_id), existing
    qid = ensure_daily(db, day).get(area)
    if qid is None:
        raise UserError("There's no daily question for this area today.", 404)
    q = db.get_one(Question, qid)
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
        )
        # A literal predicate: once psycopg prepares the statement, a bound parameter here stops
        # Postgres matching the partial unique index and the insert fails.
        .on_conflict_do_nothing(index_elements=["user_id", "day", "area"], index_where=text("mode = 'daily'"))
    )
    db.commit()
    started = db.scalars(_mine(user, day, area)).one()  # ours, or a parallel request's
    return db.get_one(Question, started.question_id), started


@dataclass
class Result:
    question: Question
    checked: Checked
    late: bool
    xp: int
    lp: float
    streak: int


def answer(
    db: DB,
    user: User,
    attempt_id: int,
    options: list[int] | None,
    value: str | None,
    now: datetime,
    unsure: bool = False,
) -> Result:
    """Submit once. Late answers are recorded and count as wrong; repeats return the stored result."""
    a = db.scalar(
        select(Attempt).where(Attempt.id == attempt_id, Attempt.user_id == user.id, Attempt.mode == "daily")
    )
    if a is None or a.day is None or a.deadline_at is None:
        raise UserError("Start the question first.", 404)
    granted = None
    if a.submitted_at is None:
        q = db.get_one(Question, a.question_id)
        checked = check(db, q, options, value, unsure)
        late = rules.is_late(now, a.deadline_at)
        recorded = db.execute(
            update(Attempt)
            .where(Attempt.id == a.id, Attempt.submitted_at.is_(None))
            .values(
                answer={"options": options, "value": value, "unsure": checked.passed},
                correct=checked.correct,
                submitted_at=now,
                late=late,
                passed=checked.passed,
            )
            .returning(Attempt.id)
        ).first()
        if recorded:  # only the request that recorded the answer earns the XP
            repeat = xp.last_seen(db, user.id, q.id, now, other_than=a.id) is not None
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
            )
            db.execute(update(Attempt).where(Attempt.id == a.id).values(xp=granted.xp, lp=granted.lp))
        db.commit()
        db.refresh(a)
    result = review_attempt(db, user, a)
    if (
        granted
    ):  # the request that scored it tells of promotions and bonuses; reloads show the stored XP and LP
        result.checked.score = granted
    return result


def close_expired(db: DB, now: datetime, user_id: int | None = None) -> int:
    """Close daily questions left to run out: late and wrong, like an answer sent after the time.
    Otherwise closing the tab on a hard question would dodge the XP a wrong answer costs."""
    stmt = (
        select(Attempt.id, Attempt.question_id, Attempt.user_id)
        .where(
            Attempt.mode == "daily", Attempt.submitted_at.is_(None), Attempt.deadline_at < now - rules.GRACE
        )
        .order_by(Attempt.user_id, Attempt.id)
    )
    if user_id is not None:
        stmt = stmt.where(Attempt.user_id == user_id)
    closed = 0
    for attempt_id, question_id, owner in db.execute(stmt).all():
        q = db.get_one(Question, question_id)
        correct = False if q.graded else None
        recorded = db.execute(
            update(Attempt)
            .where(Attempt.id == attempt_id, Attempt.submitted_at.is_(None))
            .values(correct=correct, submitted_at=now, late=True)
            .returning(Attempt.id)
        ).first()
        if recorded:
            repeat = xp.last_seen(db, owner, q.id, now, other_than=attempt_id) is not None
            granted = xp.grant(db, owner, q, "daily", correct, now, answered=False, late=True, repeat=repeat)
            db.execute(update(Attempt).where(Attempt.id == attempt_id).values(xp=granted.xp, lp=granted.lp))
            closed += 1
        db.commit()  # one attempt per transaction: attempt then player, the same lock order as answering
    return closed


def review_attempt(db: DB, user: User, a: Attempt) -> Result:
    """The stored result of a submitted attempt: retries and reloads never re-grade."""
    q = db.get_one(Question, a.question_id)
    checked = check(db, q, a.answer.get("options"), a.answer.get("value"), a.passed)
    checked.correct = a.correct
    run = rules.streak(_on_time_days(db, user), a.day) if a.day else 0
    checked.score = xp.stored(db, user.id, a)
    return Result(q, checked, bool(a.late), a.xp, a.lp, run)


def review(db: DB, user: User, area: str, now: datetime) -> Result:
    a = _attempt(db, user, rules.madrid_day(now), area)
    if a is None or a.submitted_at is None:
        raise UserError("Answer today's question first.", 409)
    return review_attempt(db, user, a)
