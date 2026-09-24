"""Daily streaks and the freezes that save them (ADR 0007)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from ..db.models import Attempt, StreakFreeze, User
from ..domain import daily as rules


def played(db: DB, user_id: int) -> set[date]:
    """Days with an on-time daily answer."""
    days = db.scalars(
        select(Attempt.day).where(
            Attempt.user_id == user_id,
            Attempt.mode == "daily",
            Attempt.submitted_at.is_not(None),
            Attempt.late.is_(False),
        )
    )
    return {d for d in days if d}


def kept(db: DB, user_id: int) -> set[date]:
    """Days that count for the streak: played, or saved by a freeze."""
    return played(db, user_id) | set(
        db.scalars(select(StreakFreeze.day).where(StreakFreeze.user_id == user_id))
    )


def days(db: DB, user_id: int, now: datetime) -> int:
    return rules.streak(kept(db, user_id), rules.madrid_day(now))


def nightly(db: DB, now: datetime) -> dict[str, int]:
    """Spend a freeze on yesterday for anyone who missed it mid-streak, then give one to anyone whose streak
    reached a multiple of 7 yesterday. Idempotent: a freeze day is stored once, and an earning day too."""
    yesterday = rules.madrid_day(now) - timedelta(days=1)
    recent = select(Attempt.user_id).where(
        Attempt.mode == "daily", Attempt.day >= yesterday - timedelta(days=1)
    )
    users = db.scalars(
        select(User)
        .where(User.status == "active", User.id.in_(recent) | (User.streak_freezes > 0))
        .order_by(User.id)
        .with_for_update()
    ).all()
    used = earned = 0
    for u in users:
        mine, saved = played(db, u.id), kept(db, u.id)
        if u.streak_freezes > 0 and rules.freeze_needed(saved, yesterday):
            db.add(StreakFreeze(user_id=u.id, day=yesterday))
            u.streak_freezes -= 1
            saved.add(yesterday)
            used += 1
        if (
            rules.freeze_earned(saved, mine, yesterday)
            and u.freeze_earned_on != yesterday
            and u.streak_freezes < rules.FREEZE_CAP
        ):
            u.streak_freezes += 1
            u.freeze_earned_on = yesterday
            earned += 1
    return {"freezes_used": used, "freezes_earned": earned}
