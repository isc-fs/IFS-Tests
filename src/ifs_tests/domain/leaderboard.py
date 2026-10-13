"""Leaderboard rules: periods, ranking with ties and the vertical board."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .daily import GRACE, MADRID, MAX_BUDGET, madrid_day
from .mock import season

PERIODS = ("season", "week")
TOP = 50
WEEK_DAYS = 7
MIN_VERTICAL = 3
MIN_ANSWERED = 5  # counted questions before a share is shown


def first_day(period: str, today: date) -> date:
    """Season: 1 September of the current season. Week: the last 7 Madrid days, today included."""
    if period == "season":
        return date(season(today), 9, 1)
    return today - timedelta(days=WEEK_DAYS - 1)


@dataclass(frozen=True)
class Accuracy:
    answered: int
    share: float | None
    low: float | None
    high: float | None


def accuracy(right: int, answered: int, bounds: tuple[float, float]) -> Accuracy:
    """Share right with its interval widened outwards to 0.001; none under MIN_ANSWERED questions."""
    if answered < MIN_ANSWERED:
        return Accuracy(answered, None, None, None)
    low, high = bounds
    share = round(right / answered, 3)
    if 0 < right < answered:  # 100% and 0% only when exact
        share = min(0.999, max(0.001, share))
    return Accuracy(
        answered,
        share,
        math.floor(round(low * 1000, 6)) / 1000,
        math.ceil(round(high * 1000, 6)) / 1000,
    )


def accuracy_cutoff(now: datetime) -> date:
    """Dailies of days before this one count for accuracy: nobody can still answer them in time."""
    return madrid_day(now - timedelta(seconds=MAX_BUDGET) - GRACE)


def madrid_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), MADRID)


def ranks(scores: Sequence[float]) -> list[int]:
    """Competition ranking of scores sorted high to low: 30, 20, 20, 10 -> 1, 2, 2, 4."""
    out: list[int] = []
    for i, x in enumerate(scores):
        out.append(out[-1] if i and x == scores[i - 1] else i + 1)
    return out


def rank_among(score: float, others: Iterable[float]) -> int:
    """Where someone with `score` would stand among `others`, sharing the rank of anyone level."""
    return 1 + sum(1 for x in others if x > score)


@dataclass(frozen=True)
class Member:
    vertical: str | None
    points: float  # rank points
    played_this_week: bool


@dataclass(frozen=True)
class VerticalScore:
    vertical: str
    members: int
    rank_points: float  # the members' average
    participation: float


def vertical_board(members: Iterable[Member]) -> list[VerticalScore]:
    """Average rank per member and the share who played this week, best average first.
    Verticals with too few members to average fairly are left out."""
    by_vertical: dict[str, list[Member]] = {}
    for m in members:
        if m.vertical:
            by_vertical.setdefault(m.vertical, []).append(m)
    rows = [
        VerticalScore(
            vertical=v,
            members=len(ms),
            rank_points=round(sum(m.points for m in ms) / len(ms), 1),
            participation=round(sum(m.played_this_week for m in ms) / len(ms), 3),
        )
        for v, ms in by_vertical.items()
        if len(ms) >= MIN_VERTICAL
    ]
    return sorted(rows, key=lambda r: (-r.rank_points, -r.participation, r.vertical))
