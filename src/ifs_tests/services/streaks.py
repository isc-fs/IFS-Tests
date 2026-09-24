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


CATCH_UP = 3  # nights a missed job can catch up on


def nightly(db: DB, now: datetime) -> dict[str, int]:
    """For each of the last few days, oldest first: spend a freeze on a day missed mid-streak, then give one to
    anyone whose streak reached a multiple of 7 that day. Idempotent (a freeze day is stored once, an earning
    day too), so a night the job didn't run is caught up. One player per transaction, locked on its own: a
    live quiz sharing XP to many players at once can't deadlock with it."""
    today = rules.madrid_day(now)
    first = today - timedelta(days=CATCH_UP)
    recent = select(Attempt.user_id).where(Attempt.mode == "daily", Attempt.day >= first - timedelta(days=1))
    ids = db.scalars(
        select(User.id)
        .where(User.status == "active", User.id.in_(recent) | (User.streak_freezes > 0))
        .order_by(User.id)
    ).all()
    db.commit()
    used = earned = 0
    for uid in ids:
        u = db.get_one(User, uid, with_for_update={"key_share": True}, populate_existing=True)
        mine, saved = played(db, uid), kept(db, uid)
        for back in range(CATCH_UP, 0, -1):
            day = today - timedelta(days=back)
            if u.streak_freezes > 0 and rules.freeze_needed(saved, day):
                db.add(StreakFreeze(user_id=uid, day=day))
                u.streak_freezes -= 1
                saved.add(day)
                used += 1
            if (
                rules.freeze_earned(saved, mine, day)
                and (u.freeze_earned_on is None or u.freeze_earned_on < day)
                and u.streak_freezes < rules.FREEZE_CAP
            ):
                u.streak_freezes += 1
                u.freeze_earned_on = day
                earned += 1
        db.commit()
    return {"freezes_used": used, "freezes_earned": earned}
