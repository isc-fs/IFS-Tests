"""Practice: any playable question, answered as often as you like, never scored."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session as DB

from ..db.models import AREAS, Attempt, Question, User
from .errors import UserError
from .questions import Checked, check, playable


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
    db: DB, user: User, area: str | None = None, topic: str | None = None, skip: int | None = None
) -> Question:
    """A random question, preferring the ones this person has practised least."""
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
    q = db.scalars(stmt.order_by(func.coalesce(mine.c.n, 0), func.random()).limit(1)).first()
    if q is None:
        raise UserError("No questions match that filter yet.", 404)
    return q


def answer(
    db: DB, user: User, question_id: int, options: list[int] | None, value: str | None, now: datetime
) -> Checked:
    q = playable(db, question_id)
    result = check(db, q, options, value)
    db.add(
        Attempt(
            user_id=user.id,
            question_id=q.id,
            mode="practice",
            answer={"options": options, "value": value},
            correct=result.correct,
            created_at=now,
        )
    )
    db.commit()
    return result
