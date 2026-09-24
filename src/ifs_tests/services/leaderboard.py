"""Leaderboards (ADR 0007). The ranked board orders members by their rank this season; the others by LP
won in the period, per area or in the last 7 days ("climbers"), which can be negative. Only active members
appear; people who opted out are never named but still see their own place."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session as DB

from ..db.models import Attempt, MockSession, Question, User
from ..domain import leaderboard as rules
from ..domain import rank as rank_rules
from ..domain.daily import madrid_day
from ..domain.xp import account_level


@dataclass
class Row:
    rank: int
    display_name: str
    vertical: str | None
    score: float  # rank points on the ranked board, LP won on the others
    me: bool
    division: int
    title: str
    level: int  # account level


@dataclass
class Mine:
    rank: int
    score: float
    hidden: bool


@dataclass
class Board:
    rows: list[Row]
    me: Mine | None
    players: int


def _scores(
    db: DB, period: str, now: datetime, area: str | None = None
) -> list[tuple[int, str, str | None, bool, float]]:
    """(id, name, vertical, opted out, LP) of each active member whose rank moved in the period. LP belongs to
    the day the play started: a daily's own day, a practice answer's day, a mock run's start. So a run begun
    before midnight on 31 August can't count in two seasons."""
    first = rules.first_day(period, madrid_day(now))
    stmt = (
        select(
            User.id,
            User.display_name,
            User.vertical,
            User.leaderboard_opt_out,
            func.sum(Attempt.lp),
        )
        .join(Attempt, Attempt.user_id == User.id)
        .outerjoin(MockSession, MockSession.id == Attempt.session_id)
        .where(
            User.status == "active",
            Attempt.lp != 0,
            or_(
                and_(
                    Attempt.mode.in_(["daily", "practice"]),
                    func.coalesce(Attempt.day, func.date(func.timezone("Europe/Madrid", Attempt.created_at)))
                    >= first,
                ),
                and_(Attempt.mode == "mock", MockSession.started_at >= rules.madrid_midnight(first)),
            ),
        )
        .group_by(User.id)
    )
    if area:
        # Attempts record the area they were played under, so relabelling a question later moves nothing.
        # (Mock attempts from before that was recorded fall back to the question's area.)
        stmt = stmt.join(Question, Question.id == Attempt.question_id).where(
            func.coalesce(Attempt.area, Question.area) == area
        )
    return [(i, name, v, hidden, round(float(p), 2)) for i, name, v, hidden, p in db.execute(stmt)]


def _ranked(db: DB, now: datetime) -> list[tuple[int, str, str | None, bool, float]]:
    """Everyone who has played for their rank this season, at their current rank points."""
    played = {s[0] for s in _scores(db, "season", now)}
    rows = db.execute(
        select(User.id, User.display_name, User.vertical, User.leaderboard_opt_out, User.rank_points).where(
            User.id.in_(played)
        )
    )
    return [(i, name, v, hidden, float(p)) for i, name, v, hidden, p in rows]


def board(db: DB, user: User, area: str | None, period: str, now: datetime) -> Board:
    scores = _ranked(db, now) if area is None and period == "season" else _scores(db, period, now, area)
    shown = sorted((s for s in scores if not s[3]), key=lambda s: (-s[4], s[1].casefold()))
    ranks = rules.ranks([s[4] for s in shown])
    # Everyone tied at the cut stays, so nobody ranked in the top 50 is missing from it.
    top = [(rank, s) for rank, s in zip(ranks, shown, strict=True) if rank <= rules.TOP]
    state = {
        uid: (points, xp)
        for uid, points, xp in db.execute(
            select(User.id, User.rank_points, User.xp).where(User.id.in_([s[0] for _, s in top]))
        ).tuples()
    }
    rows = []
    for rank, (uid, name, vertical, _, score) in top:
        points, xp = state[uid]
        division = rank_rules.division_of(points)
        rows.append(
            Row(
                rank,
                name,
                vertical,
                score,
                uid == user.id,
                division,
                rank_rules.title(division, vertical),
                account_level(xp)[0],
            )
        )
    mine = next((s[4] for s in scores if s[0] == user.id), None)
    me = None
    if mine is not None:  # LP won and lost can net to zero; they still played
        others = (s[4] for s in shown if s[0] != user.id)
        me = Mine(rules.rank_among(mine, others), mine, user.leaderboard_opt_out)
    return Board(rows, me, len(shown))


def verticals(db: DB, period: str, now: datetime) -> list[rules.VerticalScore]:
    """Average rank of each vertical's active members, and how many played this week."""
    week_start = rules.first_day("week", madrid_day(now))
    played = set(
        db.scalars(
            select(Attempt.user_id)
            .where(Attempt.mode == "daily", Attempt.submitted_at.is_not(None), Attempt.day >= week_start)
            .distinct()
        )
    )
    # People who opted out are left out entirely: counting them in an average lets anyone subtract the
    # named members' ranks and recover theirs.
    members = db.execute(
        select(User.id, User.vertical, User.rank_points).where(
            User.status == "active", User.leaderboard_opt_out.is_(False)
        )
    )
    return rules.vertical_board(rules.Member(v, float(p), i in played) for i, v, p in members)
