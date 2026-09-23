"""Awarding XP for answers, and keeping question difficulty in line with how people do."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session as DB

from ..db.models import AnswerOption, Attempt, MockSession, Question, User
from ..domain import daily as daily_rules
from ..domain import leaderboard as board_rules
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


def lock(db: DB, user_id: int) -> tuple[int, str]:
    """Take the player's row lock until commit, so their answers are scored one at a time. NO KEY UPDATE
    still lets rows that reference the user (attempts, sessions) be inserted meanwhile. Returns XP and position."""
    row = db.execute(
        select(User.xp, User.position).where(User.id == user_id).with_for_update(key_share=True)
    ).one()
    return row.xp, row.position


def last_seen(
    db: DB, user_id: int, question_id: int, now: datetime, other_than: int | None = None
) -> datetime | None:
    """When the player last had this question graded this season, in any mode: from then on they have seen
    its answer. A new season starts everyone afresh; a mock answer belongs to the season its run started in,
    as on the leaderboard."""
    season_start = board_rules.madrid_midnight(board_rules.first_day("season", daily_rules.madrid_day(now)))
    stmt = (
        select(func.max(Attempt.created_at))
        .outerjoin(MockSession, MockSession.id == Attempt.session_id)
        .where(
            Attempt.user_id == user_id,
            Attempt.question_id == question_id,
            Attempt.correct.is_not(None),
            func.coalesce(MockSession.started_at, Attempt.created_at) >= season_start,
        )
    )
    if other_than is not None:
        stmt = stmt.where(Attempt.id != other_than)
    return db.scalar(stmt)


def level(db: DB, user_id: int) -> int:
    return rules.level_for(db.execute(select(User.xp).where(User.id == user_id)).scalar_one())


def _options(db: DB, question: Question) -> int:
    if question.answer_kind != "choice-one":
        return 0
    return db.scalar(select(func.count()).where(AnswerOption.question_id == question.id)) or 0


@dataclass
class Grant:
    xp: int
    level: int
    level_up: bool


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
    passed: bool = False,
) -> Grant:
    """Work out the XP for one answer and add it to the player's lifetime XP, which never drops below the
    level their position starts at. The caller stores `xp` on the attempt and commits."""
    before, position = lock(db, user_id)
    amount = rules.award(
        correct,
        question.difficulty,
        mode,
        rules.level_for(before),
        streak_days(db, user_id, now),
        hint,
        repeat,
        late,
        again_today,
        area=question.area,
        answer_kind=question.answer_kind,
        options=_options(db, question),
        passed=passed,
    )
    total = db.execute(
        update(User)
        .where(User.id == user_id)
        .values(xp=func.greatest(rules.floor_for(position), User.xp + amount))
        .returning(User.xp)
    ).scalar_one()
    after = rules.level_for(total)
    return Grant(amount, after, after > rules.level_for(before))


def recalibrate(db: DB) -> int:
    """Nightly: move each graded question's difficulty towards how people actually answer it. Only each
    person's first answer in time counts, so nobody can drag a question's difficulty by answering it again."""
    first = (
        select(Attempt.question_id, Attempt.correct)
        .where(Attempt.correct.is_not(None), Attempt.late.is_not(True))
        .distinct(Attempt.user_id, Attempt.question_id)
        .order_by(Attempt.user_id, Attempt.question_id, Attempt.created_at, Attempt.id)
        .subquery()
    )
    stats = db.execute(
        select(
            Question.id,
            Question.answer_kind,
            Question.time_s,
            Question.difficulty,
            func.count(),
            func.count(case((first.c.correct.is_(True), 1))),
        )
        .join(first, first.c.question_id == Question.id)
        .where(Question.graded)
        .group_by(Question.id)
    )
    changed = 0
    for qid, kind, time_s, current, answered, right in stats:
        new = rules.difficulty(kind, time_s, answered, right)
        if new != current:
            db.execute(update(Question).where(Question.id == qid).values(difficulty=new))
            changed += 1
    return changed
