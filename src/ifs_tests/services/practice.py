"""Practice: any playable question, answered as often as you like, at half XP; a question seen before earns a tenth."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session as DB

from ..db.models import AREAS, Attempt, Question, User
from ..domain.daily import madrid_day
from . import hints, xp
from .errors import UserError
from .questions import Checked, check, not_running, playable, running


@dataclass
class AreaProgress:
    area: str
    questions: int = 0
    answered: int = 0
    correct: int = 0
    topics: dict[str, int] = field(default_factory=dict)


def areas(db: DB, user: User) -> list[AreaProgress]:
    by_area = {a: AreaProgress(a) for a in AREAS}
    for area, topic, n in db.execute(
        select(Question.area, Question.topic, func.count())
        .where(Question.playable)
        .group_by(Question.area, Question.topic)
    ):
        by_area[area].questions += n
        if topic:
            by_area[area].topics[topic] = n
    mine = (
        select(
            Question.area,
            func.count(distinct(Attempt.question_id)),
            func.count(distinct(case((Attempt.correct.is_(True), Attempt.question_id)))),
        )
        .join(Question, Question.id == Attempt.question_id)
        .where(Attempt.user_id == user.id, Attempt.mode == "practice", Question.playable)
        .group_by(Question.area)
    )
    for area, answered, correct in db.execute(mine):
        by_area[area].answered, by_area[area].correct = answered, correct
    return [a for a in by_area.values() if a.questions]


def next_question(
    db: DB,
    user: User,
    now: datetime,
    area: str | None = None,
    topic: str | None = None,
    skip: int | None = None,
) -> Question:
    """A random question, preferring the ones this person has practised least, never one they still have to
    answer in a daily, mock or live quiz."""
    mine = (
        select(Attempt.question_id, func.count().label("n"))
        .where(Attempt.user_id == user.id, Attempt.mode == "practice")
        .group_by(Attempt.question_id)
        .subquery()
    )
    stmt = select(Question).outerjoin(mine, mine.c.question_id == Question.id).where(Question.playable)
    if area:
        stmt = stmt.where(Question.area == area)
    if topic:
        stmt = stmt.where(Question.topic == topic)
    if skip:
        stmt = stmt.where(Question.id != skip)
    if busy := running(db, user.id, now):
        stmt = stmt.where(Question.id.not_in(busy))
    q = db.scalars(stmt.order_by(func.coalesce(mine.c.n, 0), func.random()).limit(1)).first()
    if q is None:
        raise UserError("No questions match that filter yet.", 404)
    return q


def answer(
    db: DB,
    user: User,
    question_id: int,
    options: list[int] | None,
    value: str | None,
    now: datetime,
    unsure: bool = False,
) -> Checked:
    q = playable(db, question_id)
    not_running(db, user.id, q.id, now)
    result = check(db, q, options, value, unsure)
    xp.lock(db, user.id)  # so two tabs can't both score the first answer
    last = xp.last_seen(db, user.id, q.id, now)
    again_today = last is not None and madrid_day(last) == madrid_day(now)
    hinted = hints.spend_practice(db, user.id, q.id)
    granted = xp.grant(
        db,
        user.id,
        q,
        "practice",
        result.correct,
        now,
        repeat=last is not None,
        again_today=again_today,
        passed=result.passed,
        hint=hinted,
    )
    db.add(
        Attempt(
            user_id=user.id,
            question_id=q.id,
            mode="practice",
            answer={"options": options, "value": value, "unsure": result.passed},
            correct=result.correct,
            created_at=now,
            area=q.area,
            xp=granted.xp,
            passed=result.passed,
            hint_used=hinted,
        )
    )
    db.commit()
    result.xp, result.level, result.level_up = granted.xp, granted.level, granted.level_up
    return result
