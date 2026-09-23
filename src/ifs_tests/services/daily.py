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
from .errors import UserError
from .questions import Checked, check

LOCK = 0x1F5DA11  # pg advisory lock key for choosing the day's questions


def ensure_daily(db: DB, day: date) -> dict[str, int]:
    """Choose the day's questions once; concurrent callers wait for the first and reuse its choice."""
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
                insert(DailyQuestion).values(day=day, area=area, question_id=qid).on_conflict_do_nothing()
            )
            chosen[area] = qid
    db.commit()
    return chosen


def _chosen(db: DB, day: date) -> dict[str, int]:
    rows = db.execute(select(DailyQuestion.area, DailyQuestion.question_id).where(DailyQuestion.day == day))
    return {area: qid for area, qid in rows}


def _mine(user: User, day: date, area: str) -> Select[tuple[Attempt]]:
    return select(Attempt).where(
        Attempt.user_id == user.id, Attempt.mode == "daily", Attempt.day == day, Attempt.area == area
    )


def _attempt(db: DB, user: User, day: date, area: str) -> Attempt | None:
    return db.scalar(_mine(user, day, area))


def _on_time_days(db: DB, user: User) -> set[date]:
    rows = db.scalars(
        select(Attempt.day).where(
            Attempt.user_id == user.id,
            Attempt.mode == "daily",
            Attempt.submitted_at.is_not(None),
            Attempt.late.is_(False),
        )
    )
    return {d for d in rows if d}


@dataclass
class AreaState:
    area: str
    budget_s: int
    state: str  # "new", "started" or "done"
    deadline_at: datetime | None
    correct: bool | None
    late: bool | None
    points: int


@dataclass
class Status:
    day: date
    streak: int
    points_today: int
    areas: list[AreaState]


def status(db: DB, user: User, now: datetime) -> Status:
    day = rules.madrid_day(now)
    chosen = ensure_daily(db, day)
    areas = []
    for area, qid in chosen.items():
        q = db.get_one(Question, qid)
        a = _attempt(db, user, day, area)
        state = "new" if a is None else "done" if a.submitted_at else "started"
        areas.append(
            AreaState(
                area=area,
                budget_s=rules.budget(q.time_s, q.answer_kind),
                state=state,
                deadline_at=a.deadline_at if a else None,
                correct=a.correct if a else None,
                late=a.late if a else None,
                points=a.points if a else 0,
            )
        )
    order = {a: i for i, a in enumerate(rules.AREAS)}
    areas.sort(key=lambda s: order[s.area])
    return Status(day, rules.streak(_on_time_days(db, user), day), sum(a.points for a in areas), areas)


def start(db: DB, user: User, area: str, now: datetime) -> tuple[Question, Attempt]:
    """Start the clock, or return the running attempt. The question is only revealed from here."""
    day = rules.madrid_day(now)
    qid = ensure_daily(db, day).get(area)
    if qid is None:
        raise UserError("There's no daily question for this area today.", 404)
    q = db.get_one(Question, qid)
    existing = _attempt(db, user, day, area)
    if existing is None:
        deadline = now + timedelta(seconds=rules.budget(q.time_s, q.answer_kind))
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
                deadline_at=deadline,
            )
            # A literal predicate: once psycopg prepares the statement, a bound parameter here stops
            # Postgres matching the partial unique index and the insert fails.
            .on_conflict_do_nothing(
                index_elements=["user_id", "day", "area"], index_where=text("mode = 'daily'")
            )
        )
        db.commit()
        existing = db.scalars(_mine(user, day, area)).one()
    if existing.submitted_at:
        raise UserError("You've already answered today's question for this area.", 409)
    return q, existing


@dataclass
class Result:
    question: Question
    checked: Checked
    late: bool
    points: int
    streak: int


def answer(
    db: DB, user: User, attempt_id: int, options: list[int] | None, value: str | None, now: datetime
) -> Result:
    """Submit once. Late answers are recorded but score nothing; repeats return the stored result."""
    a = db.scalar(
        select(Attempt).where(Attempt.id == attempt_id, Attempt.user_id == user.id, Attempt.mode == "daily")
    )
    if a is None or a.day is None or a.deadline_at is None:
        raise UserError("Start the question first.", 404)
    if a.submitted_at is None:
        checked = check(db, db.get_one(Question, a.question_id), options, value)
        late = rules.is_late(now, a.deadline_at)
        days = _on_time_days(db, user) | ({a.day} if not late else set())
        db.execute(
            update(Attempt)
            .where(Attempt.id == a.id, Attempt.submitted_at.is_(None))
            .values(
                answer={"options": options, "value": value},
                correct=checked.correct,
                submitted_at=now,
                late=late,
                points=rules.points(bool(checked.correct), late, rules.streak(days, a.day)),
            )
        )
        db.commit()
        db.refresh(a)
    return review_attempt(db, user, a)


def review_attempt(db: DB, user: User, a: Attempt) -> Result:
    """The stored result of a submitted attempt: retries and reloads never re-grade."""
    q = db.get_one(Question, a.question_id)
    checked = check(db, q, a.answer.get("options"), a.answer.get("value"))
    checked.correct = a.correct
    run = rules.streak(_on_time_days(db, user), a.day) if a.day else 0
    return Result(q, checked, bool(a.late), a.points, run)


def review(db: DB, user: User, area: str, now: datetime) -> Result:
    a = _attempt(db, user, rules.madrid_day(now), area)
    if a is None or a.submitted_at is None:
        raise UserError("Answer today's question first.", 409)
    return review_attempt(db, user, a)
