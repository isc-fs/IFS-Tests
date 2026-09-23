"""Awarding XP for answers, and keeping question difficulty in line with how people do."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session as DB

from ..db.models import Attempt, Question, User
from ..domain import daily as daily_rules
from ..domain import xp as rules


def streak_days(db: DB, user_id: int, now: datetime) -> int:
    """Consecutive Madrid days with an on-time daily answer, ending today (or yesterday)."""
    days = db.scalars(
        select(Attempt.day).where(
            Attempt.user_id == user_id,
            Attempt.mode == "daily",
            Attempt.submitted_at.is_not(None),
            Attempt.late.is_(False),
        )
    )
    return daily_rules.streak({d for d in days if d}, daily_rules.madrid_day(now))


def lock(db: DB, user_id: int) -> int:
    """Take the player's row lock until commit, so their answers are scored one at a time. Returns their XP."""
    return db.execute(select(User.xp).where(User.id == user_id).with_for_update()).scalar_one()


def last_right(db: DB, user_id: int, question_id: int) -> datetime | None:
    return db.scalar(
        select(func.max(Attempt.created_at)).where(
            Attempt.user_id == user_id, Attempt.question_id == question_id, Attempt.correct.is_(True)
        )
    )


def level(db: DB, user_id: int) -> int:
    return rules.level_for(db.execute(select(User.xp).where(User.id == user_id)).scalar_one())


@dataclass
class Grant:
    xp: int
    level: int


def grant(
    db: DB,
    user_id: int,
    question: Question,
    mode: str,
    correct: bool | None,
    now: datetime,
    *,
    hint: bool = False,
    repeat: bool = False,
    late: bool = False,
    again_today: bool = False,
) -> Grant:
    """Work out the XP for one answer and add it to the player's lifetime XP, which never drops below the
    level their rank starts at. The caller stores `xp` on the attempt and commits."""
    rank = db.execute(select(User.rank).where(User.id == user_id)).scalar_one()
    amount = rules.award(
        correct,
        question.difficulty,
        mode,
        rules.level_for(lock(db, user_id)),
        streak_days(db, user_id, now),
        hint,
        repeat,
        late,
        again_today,
    )
    total = db.execute(
        update(User)
        .where(User.id == user_id)
        .values(xp=func.greatest(rules.floor_for(rank), User.xp + amount))
        .returning(User.xp)
    ).scalar_one()
    return Grant(amount, rules.level_for(total))


def recalibrate(db: DB) -> int:
    """Nightly: move each graded question's difficulty towards how people actually answer it."""
    stats = db.execute(
        select(
            Question.id,
            Question.answer_kind,
            Question.time_s,
            Question.difficulty,
            func.count(Attempt.id),
            func.count(case((Attempt.correct.is_(True), 1))),
        )
        .join(Attempt, Attempt.question_id == Question.id)
        .where(Question.graded, Attempt.correct.is_not(None))
        .group_by(Question.id)
    )
    changed = 0
    for qid, kind, time_s, current, answered, right in stats:
        new = rules.difficulty(kind, time_s, answered, right)
        if new != current:
            db.execute(update(Question).where(Question.id == qid).values(difficulty=new))
            changed += 1
    return changed
