"""Leaderboards: points from daily questions and mock quizzes, per person, per area and per vertical.
Only active members appear; people who opted out are never named but still see their own rank."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from ..db.models import Attempt, Question, User
from ..domain import leaderboard as rules
from ..domain.daily import madrid_day


@dataclass
class Row:
    rank: int
    display_name: str
    vertical: str | None
    points: int
    me: bool


@dataclass
class Mine:
    rank: int
    points: int
    hidden: bool


@dataclass
class Board:
    rows: list[Row]
    me: Mine | None
    players: int


def _since(period: str, now: datetime) -> datetime:
    return rules.madrid_midnight(rules.first_day(period, madrid_day(now)))


def _scores(db: DB, since: datetime, area: str | None = None) -> list[tuple[int, str, str | None, bool, int]]:
    """(id, name, vertical, opted out, points) of each active member who scored since then."""
    stmt = (
        select(
            User.id,
            User.display_name,
            User.vertical,
            User.leaderboard_opt_out,
            func.sum(Attempt.points),
        )
        .join(Attempt, Attempt.user_id == User.id)
        .where(User.status == "active", Attempt.submitted_at >= since, Attempt.points > 0)
        .group_by(User.id)
    )
    if area:
        # Daily attempts record their area; mock attempts take it from the question.
        stmt = stmt.join(Question, Question.id == Attempt.question_id).where(
            func.coalesce(Attempt.area, Question.area) == area
        )
    return [(i, name, v, hidden, int(p)) for i, name, v, hidden, p in db.execute(stmt)]


def board(db: DB, user: User, area: str | None, period: str, now: datetime) -> Board:
    scores = _scores(db, _since(period, now), area)
    shown = sorted((s for s in scores if not s[3]), key=lambda s: (-s[4], s[1].casefold()))
    ranks = rules.ranks([s[4] for s in shown])
    rows = [
        Row(rank, name, vertical, points, uid == user.id)
        for rank, (uid, name, vertical, _, points) in zip(ranks, shown, strict=True)
    ]
    mine = next((s[4] for s in scores if s[0] == user.id), 0)
    me = None
    if mine:
        others = (s[4] for s in shown if s[0] != user.id)
        me = Mine(rules.rank_among(mine, others), mine, user.leaderboard_opt_out)
    return Board(rows[: rules.TOP], me, len(shown))


def verticals(db: DB, period: str, now: datetime) -> list[rules.VerticalScore]:
    points = {s[0]: s[4] for s in _scores(db, _since(period, now))}
    week_start = rules.first_day("week", madrid_day(now))
    played = set(
        db.scalars(
            select(Attempt.user_id)
            .where(Attempt.mode == "daily", Attempt.submitted_at.is_not(None), Attempt.day >= week_start)
            .distinct()
        )
    )
    members = db.execute(select(User.id, User.vertical).where(User.status == "active"))
    return rules.vertical_board(rules.Member(v, points.get(i, 0), i in played) for i, v in members)
