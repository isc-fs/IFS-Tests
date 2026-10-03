"""Leaderboards (ADR 0007). The ranked board orders members by their rank this season; the others by LP
won in the period, per area or in the last 7 days ("climbers"), which can be negative. Only active members
appear; people who opted out are never named but still see their own place."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import ColumnElement, Select, func, literal_column, or_, select
from sqlalchemy.orm import Session as DB

from ..db.models import LP_DAY, RANKED_PLAY, Attempt, MockSession, Question, User
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


def _day_play(first: date) -> Select[tuple[int]]:
    """Each member's daily and practice answers that moved their rank since `first`, correlated to `User`."""
    return select(Attempt.id).where(Attempt.user_id == User.id, RANKED_PLAY, first <= LP_DAY)


def _mock_play(first: date) -> Select[tuple[int]]:
    """Their mock answers that moved their rank in runs started since `first`."""
    return (
        select(Attempt.id)
        .join(MockSession, MockSession.id == Attempt.session_id)
        .where(
            MockSession.user_id == User.id,
            Attempt.mode == "mock",
            Attempt.lp != 0,
            MockSession.started_at >= rules.madrid_midnight(first),
        )
    )


def _any(rows: Select[tuple[int]]) -> ColumnElement[bool]:
    # Looked up member by member. An EXISTS may be planned as one hashed pass over every row ever stored.
    return rows.limit(1).scalar_subquery().is_not(None)


def _played(first: date) -> ColumnElement[bool]:
    return or_(_any(_day_play(first)), _any(_mock_play(first)))


def _lp(db: DB, first: date, area: str | None, only: int | None = None) -> dict[int, float]:
    """LP of each active member whose rank moved since `first` (or of member `only`). LP belongs to the day the
    play started: a daily's own day, a practice answer's day, a mock run's start. So a run begun before midnight
    on 31 August can't count in two seasons. Each member's sum reads only the period's rows."""
    sums = []
    for play in (_day_play(first), _mock_play(first)):
        play = play.with_only_columns(func.sum(Attempt.lp))
        if area:
            # Attempts record the area they were played under, so relabelling a question later moves nothing.
            # (Mock attempts from before that was recorded fall back to the question's area.)
            play = play.join(Question, Question.id == Attempt.question_id).where(
                func.coalesce(Attempt.area, Question.area) == area
            )
        sums.append(play.scalar_subquery())
    stmt = select(User.id, *sums).where(User.status == "active")
    if only is not None:
        stmt = stmt.where(User.id == only)
    return {
        i: round((day or 0) + (mock or 0), 2)
        for i, day, mock in db.execute(stmt).tuples()
        if day is not None or mock is not None
    }


# Late in a season those sums cost about 20 ms of database time per view, and a room opening the board at once
# queued behind them. Each worker keeps them for BOARD_TTL; the viewer's own LP, names, opt-outs and who is
# active are read on every view.
BOARD_TTL = 30.0
_sums: dict[tuple[str | None, date], tuple[float, dict[int, float]]] = {}
_summing = threading.Lock()


def _period_lp(db: DB, first: date, area: str | None) -> tuple[dict[int, float], bool]:
    """Everyone's LP since `first` in `area`, and whether it came from the cache. One sum at a time per worker,
    so a room of phones opening the board together reads it once."""
    key = (area, first)

    def cached() -> dict[int, float] | None:
        hit = _sums.get(key)
        return hit[1] if hit and time.monotonic() - hit[0] < BOARD_TTL else None

    if (lp := cached()) is not None:
        return lp, True
    with _summing:
        if (lp := cached()) is not None:
            return lp, True
        at = time.monotonic()
        lp = _lp(db, first, area)
        for k in [k for k, (t, _) in _sums.items() if at - t >= BOARD_TTL]:
            del _sums[k]
        _sums[key] = (at, lp)
        return lp, False


def _scores(
    db: DB, user: User, period: str, now: datetime, area: str | None = None
) -> list[tuple[int, str, str | None, bool, float]]:
    """(id, name, vertical, opted out, LP) of each active member whose rank moved in the period. Others' LP may
    be up to BOARD_TTL old; the viewer's own is always current."""
    first = rules.first_day(period, madrid_day(now))
    lp, cached = _period_lp(db, first, area)
    if cached:
        lp = {i: x for i, x in lp.items() if i != user.id} | _lp(db, first, area, user.id)
    rows = db.execute(
        select(User.id, User.display_name, User.vertical, User.leaderboard_opt_out).where(
            User.status == "active", User.id.in_(lp)
        )
    ).tuples()
    return [(i, name, v, hidden, lp[i]) for i, name, v, hidden in rows]


def _ranked(db: DB, now: datetime) -> list[tuple[int, str, str | None, bool, float]]:
    """Everyone who has played for their rank this season, at their current rank points."""
    first = rules.first_day("season", madrid_day(now))
    rows = db.execute(
        select(User.id, User.display_name, User.vertical, User.leaderboard_opt_out, User.rank_points).where(
            User.status == "active", _played(first)
        )
    )
    return [(i, name, v, hidden, float(p)) for i, name, v, hidden, p in rows]


def board(db: DB, user: User, area: str | None, period: str, now: datetime) -> Board:
    scores = _ranked(db, now) if area is None and period == "season" else _scores(db, user, period, now, area)
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
    """Average rank of each vertical's members who played for it this season, and how many played this week.
    Members who haven't played would only add their placement, which says more about positions than play."""
    week_start = rules.first_day("week", madrid_day(now))
    this_week = _any(
        select(Attempt.id).where(
            Attempt.user_id == User.id,
            Attempt.mode == literal_column("'daily'"),  # a literal, to match uq_attempts_daily
            Attempt.day >= week_start,
            Attempt.submitted_at.is_not(None),
        )
    )
    # People who opted out are left out entirely: counting them in an average lets anyone subtract the
    # named members' ranks and recover theirs.
    members = db.execute(
        select(User.vertical, User.rank_points, this_week).where(
            User.status == "active",
            User.leaderboard_opt_out.is_(False),
            _played(rules.first_day("season", madrid_day(now))),
        )
    )
    return rules.vertical_board(rules.Member(v, float(p), played) for v, p, played in members)
