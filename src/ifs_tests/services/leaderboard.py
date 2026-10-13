"""Leaderboards (ADR 0007). The ranked board orders members by their rank this season; the others by LP
won in the period, per area or in the last 7 days ("climbers"), which can be negative. Only active members
appear; people who opted out are never named but still see their own place. From season 1b (ADR 0010) each
person board also shows accuracy beside LP: display only, cached like LP."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    CompoundSelect,
    Select,
    and_,
    case,
    func,
    literal_column,
    or_,
    select,
    true,
    tuple_,
    union_all,
)
from sqlalchemy.orm import Session as DB
from sqlalchemy.orm import aliased

from ..db.models import LP_DAY, RANKED_PLAY, Attempt, MockSession, Question, User
from ..domain import leaderboard as rules
from ..domain import rank as rank_rules
from ..domain.daily import madrid_day
from ..domain.integrity import wilson
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
    answered: int | None = None  # the four are None while accuracy is off
    accuracy: float | None = None
    accuracy_low: float | None = None
    accuracy_high: float | None = None


@dataclass
class Mine:
    rank: int
    score: float
    hidden: bool
    answered: int | None = None
    accuracy: float | None = None
    accuracy_low: float | None = None
    accuracy_high: float | None = None


@dataclass
class Board:
    rows: list[Row]
    me: Mine | None
    players: int
    shows_accuracy: bool = False
    accuracy_from: date | None = None


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


def _first(season: date) -> ColumnElement[bool]:
    """No other graded answer by the member to this question earlier this season, in any mode, in grading order:
    the repeat rule `xp.last_seen` applies at grant time and `integrity.grading_order` replays. Unlike
    `last_seen`, the `_hidden_mock` exception isn't applied (game-rules, leaderboards). A mock answer belongs
    to the season its run started in."""
    seen, run = aliased(Attempt), aliased(MockSession)

    def graded(a: Any) -> ColumnElement[Any]:
        return case((a.mode.in_(("practice", "live")), a.created_at), else_=a.submitted_at)

    def order(a: Any) -> ColumnElement[Any]:
        return case((a.mode == "daily", 0), else_=1)

    earlier = (
        select(seen.id)
        .outerjoin(run, run.id == seen.session_id)
        .where(
            seen.user_id == Attempt.user_id,
            seen.question_id == Attempt.question_id,
            seen.correct.is_not(None),
            func.coalesce(run.started_at, seen.created_at) >= rules.madrid_midnight(season),
            tuple_(graded(seen), order(seen), seen.id) < tuple_(graded(Attempt), order(Attempt), Attempt.id),
        )
    )
    return ~_any(earlier)


Tally = dict[tuple[int, str], tuple[int, int]]  # (member, area) -> (right, answered)


def _counted(window: date, season: date, cutoff: date) -> CompoundSelect[tuple[str, int, int]]:
    """Per area, (right, answered) of the member's answers that count for accuracy: first and graded, on ranked
    play only (dailies and first counted mock runs). A late answer, "I'm not sure" or a question left to run
    out counts as answered and wrong, as the game scores it (a run-out daily only once it is closed, by its
    player's next visit or the nightly job). Dailies only before `cutoff`, because (a) nothing is tallied
    before its result is shown to the player (mock results come at the end, so only finished counted runs),
    and (b) a figure that moves while a daily is still open for others would show their result on a question
    that is still running for them. Correlated to `User`."""
    area = func.coalesce(Attempt.area, Question.area)
    cols = (
        area.label("area"),
        func.count()
        .filter(and_(Attempt.correct.is_(True), Attempt.late.is_not(True), Attempt.passed.is_not(True)))
        .label("right"),
        func.count().label("n"),
    )
    shared = (Attempt.correct.is_not(None), Attempt.submitted_at.is_not(None), _first(season))
    daily = (
        select(*cols)
        .select_from(Attempt)
        .join(Question, Question.id == Attempt.question_id)
        .where(
            Attempt.user_id == User.id,
            Attempt.mode == literal_column("'daily'"),  # a literal, to match uq_attempts_daily
            Attempt.day >= window,
            Attempt.day < cutoff,
            *shared,
        )
        .group_by(area)
    )
    mock = (
        select(*cols)
        .select_from(Attempt)
        .join(Question, Question.id == Attempt.question_id)
        .join(MockSession, MockSession.id == Attempt.session_id)
        .where(
            MockSession.user_id == User.id,
            MockSession.counted.is_(True),
            MockSession.finished_at.is_not(None),
            MockSession.started_at >= rules.madrid_midnight(window),
            Attempt.mode == "mock",
            *shared,
        )
        .group_by(area)
    )
    return union_all(daily, mock)


def _tally(db: DB, window: date, season: date, cutoff: date) -> Tally:
    """(right, answered) per member and area of each active member with a counted answer since `window`."""
    counted = _counted(window, season, cutoff).lateral()
    stmt = (
        select(User.id, counted.c.area, func.sum(counted.c.right), func.sum(counted.c.n))
        .select_from(User)
        .join(counted, true())
        .where(User.status == "active")
        .group_by(User.id, counted.c.area)
    )
    return {(i, area): (int(right), int(n)) for i, area, right, n in db.execute(stmt).tuples()}


# Accuracy is cached apart from LP: the same TTL, but a tally never queues behind the LP sums, and while the
# switch is off nothing here runs. One tally serves every board of a window (it is grouped by area). The key
# carries the cutoff, so it changes at the minute the day's dailies join. The viewer's own figure is as old
# as the rest.
_tallies: dict[tuple[date, date], tuple[float, Tally]] = {}
_tallying = threading.Lock()


def _period_tally(db: DB, window: date, season: date, cutoff: date) -> Tally:
    """Everyone's tally from `window` on; one at a time per worker."""
    key = (window, cutoff)

    def cached() -> Tally | None:
        hit = _tallies.get(key)
        return hit[1] if hit and time.monotonic() - hit[0] < BOARD_TTL else None

    if (tally := cached()) is not None:
        return tally
    with _tallying:
        if (tally := cached()) is not None:
            return tally
        at = time.monotonic()
        tally = _tally(db, window, season, cutoff)
        for k in [k for k, (t, _) in _tallies.items() if at - t >= BOARD_TTL]:
            del _tallies[k]
        _tallies[key] = (at, tally)
        return tally


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


def board(
    db: DB, user: User, area: str | None, period: str, now: datetime, since: date | None = None
) -> Board:
    """`since`: from when accuracy counts (the rule date of season 1b); None leaves it off. Accuracy never
    crosses a season, so the window starts at the latest of the period, the season and `since`."""
    scores = _ranked(db, now) if area is None and period == "season" else _scores(db, user, period, now, area)
    shown = sorted((s for s in scores if not s[3]), key=lambda s: (-s[4], s[1].casefold()))
    ranks = rules.ranks([s[4] for s in shown])
    # Everyone tied at the cut stays, so nobody ranked in the top 50 is missing from it.
    top = [(rank, s) for rank, s in zip(ranks, shown, strict=True) if rank <= rules.TOP]
    tally: dict[int, tuple[int, int]] | None = None
    window = None
    if since is not None:
        today = madrid_day(now)
        season = rules.first_day("season", today)
        window = max(rules.first_day(period, today), season, since)
        counted = _period_tally(db, window, season, rules.accuracy_cutoff(now))
        tally = {}
        for (uid, a), (right, n) in counted.items():
            if area is None or a == area:  # Everyone sums all areas, "unclassified" included
                r0, n0 = tally.get(uid, (0, 0))
                tally[uid] = (r0 + right, n0 + n)

    def accuracy(uid: int) -> dict[str, Any]:
        if tally is None:
            return {}
        right, n = tally.get(uid, (0, 0))
        a = rules.accuracy(right, n, wilson(right, n))
        return {
            "answered": a.answered,
            "accuracy": a.share,
            "accuracy_low": a.low,
            "accuracy_high": a.high,
        }

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
                **accuracy(uid),
            )
        )
    mine = next((s[4] for s in scores if s[0] == user.id), None)
    me = None
    if mine is not None:  # LP won and lost can net to zero; they still played
        others = (s[4] for s in shown if s[0] != user.id)
        me = Mine(rules.rank_among(mine, others), mine, user.leaderboard_opt_out, **accuracy(user.id))
    return Board(rows, me, len(shown), tally is not None, window)


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
