"""1 September: every active member's rank drops back for a fresh climb (ADR 0007). Account levels stay."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session as DB

from ..db.models import Attempt, User
from ..domain import rank as rules
from . import xp


def rollover(db: DB, now: datetime) -> int:
    """Idempotent: only players placed in an earlier season move. Anyone it misses (alumni who come back)
    resets on their next answer instead (services/xp.grant). maintenance.run settles the due daily results
    first, so each is granted in the season it was played in; a player with one still due (it failed) waits for
    a later night, or for their next answer, which settles it first."""
    season = rules.season_of(now)
    due = db.scalars(
        select(User.id).where(User.status == "active", User.rank_season != 0, User.rank_season < season)
    ).all()
    db.commit()
    moved = 0
    for uid in due:  # one player per transaction, like answering: no multi-row lock to deadlock on
        u = db.get_one(User, uid, with_for_update={"key_share": True}, populate_existing=True)
        if u.rank_season in (0, season) or db.scalar(  # an answer reset them meanwhile, or a result is due
            select(exists().where(xp.due(now)[0], Attempt.user_id == uid))
        ):
            db.commit()
            continue
        u.rank_points = rules.season_reset(u.rank_points, u.position)
        u.rank_best = rules.division_of(u.rank_points)
        u.rank_season = season
        db.commit()
        moved += 1
    return moved
