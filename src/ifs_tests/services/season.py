"""1 September: every active member's rank drops back for a fresh climb (ADR 0007). Account levels stay."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from ..db.models import User
from ..domain import rank as rules


def rollover(db: DB, now: datetime) -> int:
    """Idempotent: only players placed in an earlier season move. Anyone it misses (alumni who come back)
    resets on their next answer instead (services/xp.grant)."""
    season = rules.season_of(now)
    due = db.scalars(
        select(User.id).where(User.status == "active", User.rank_season != 0, User.rank_season < season)
    ).all()
    db.commit()
    moved = 0
    for uid in due:  # one player per transaction, like answering: no multi-row lock to deadlock on
        u = db.get_one(User, uid, with_for_update={"key_share": True}, populate_existing=True)
        if u.rank_season in (0, season):  # an answer reset them meanwhile
            db.commit()
            continue
        u.rank_points = rules.season_reset(u.rank_points, u.position)
        u.rank_best = rules.division_of(u.rank_points)
        u.rank_season = season
        db.commit()
        moved += 1
    return moved
