"""Leaderboards: XP earned in the period (it can be negative), per person, per area and per vertical.
Only active members appear; people who opted out are never named but still see their own rank."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session as DB

from ..db.models import Attempt, MockSession, Question, User
from ..domain import leaderboard as rules
from ..domain import xp as xp_rules
from ..domain.daily import madrid_day


@dataclass
class Row:
    rank: int
    display_name: str
    vertical: str | None
    xp: int
    me: bool
    level: int
    title: str


@dataclass
class Mine:
    rank: int
    xp: int
    hidden: bool


@dataclass
class Board:
    rows: list[Row]
    me: Mine | None
    players: int


def _scores(
    db: DB, period: str, now: datetime, area: str | None = None
) -> list[tuple[int, str, str | None, bool, int]]:
    """(id, name, vertical, opted out, xp) of each active member who won or lost XP in the period, from
    every mode. XP belongs to the day the play started: a daily's own day, a practice answer's day, a mock
    run's start. So a run begun before midnight on 31 August can't count in two seasons."""
    first = rules.first_day(period, madrid_day(now))
    stmt = (
        select(
            User.id,
            User.display_name,
            User.vertical,
            User.leaderboard_opt_out,
            func.sum(Attempt.xp),
        )
        .join(Attempt, Attempt.user_id == User.id)
        .outerjoin(MockSession, MockSession.id == Attempt.session_id)
        .where(
            User.status == "active",
            Attempt.xp != 0,
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
    return [(i, name, v, hidden, int(p)) for i, name, v, hidden, p in db.execute(stmt)]


def board(db: DB, user: User, area: str | None, period: str, now: datetime) -> Board:
    scores = _scores(db, period, now, area)
    shown = sorted((s for s in scores if not s[3]), key=lambda s: (-s[4], s[1].casefold()))
    ranks = rules.ranks([s[4] for s in shown])
    top = [(rank, s) for rank, s in zip(ranks, shown, strict=True) if rank <= rules.TOP]
    lifetime = dict(
        db.execute(select(User.id, User.xp).where(User.id.in_([s[0] for _, s in top]))).tuples().all()
    )
    rows = []
    for rank, (uid, name, vertical, _, xp) in top:
        level = xp_rules.level_for(lifetime[uid])
        rows.append(Row(rank, name, vertical, xp, uid == user.id, level, xp_rules.title(level, vertical)))
    mine = next((s[4] for s in scores if s[0] == user.id), None)
    me = None
    if mine is not None:  # XP won and lost can net to zero; they still played
        others = (s[4] for s in shown if s[0] != user.id)
        me = Mine(rules.rank_among(mine, others), mine, user.leaderboard_opt_out)
    # Everyone tied at the cut stays, so nobody ranked in the top 50 is missing from it.
    return Board(rows, me, len(shown))


def verticals(db: DB, period: str, now: datetime) -> list[rules.VerticalScore]:
    xp = {s[0]: s[4] for s in _scores(db, period, now)}
    week_start = rules.first_day("week", madrid_day(now))
    played = set(
        db.scalars(
            select(Attempt.user_id)
            .where(Attempt.mode == "daily", Attempt.submitted_at.is_not(None), Attempt.day >= week_start)
            .distinct()
        )
    )
    # People who opted out are left out entirely: counting them in an average lets anyone subtract the
    # named members' xp and recover theirs.
    members = db.execute(
        select(User.id, User.vertical).where(User.status == "active", User.leaderboard_opt_out.is_(False))
    )
    return rules.vertical_board(rules.Member(v, xp.get(i, 0), i in played) for i, v in members)
