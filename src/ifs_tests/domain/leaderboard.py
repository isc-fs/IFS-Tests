"""Leaderboard rules: periods, ranking with ties and the vertical board."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .daily import MADRID
from .mock import season

PERIODS = ("season", "week")
TOP = 50
WEEK_DAYS = 7
MIN_VERTICAL = 3


def first_day(period: str, today: date) -> date:
    """Season: 1 September of the current season. Week: the last 7 Madrid days, today included."""
    if period == "season":
        return date(season(today), 9, 1)
    return today - timedelta(days=WEEK_DAYS - 1)


def madrid_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), MADRID)


def ranks(xp: Sequence[int]) -> list[int]:
    """Competition ranking of xp sorted high to low: 30, 20, 20, 10 -> 1, 2, 2, 4."""
    out: list[int] = []
    for i, p in enumerate(xp):
        out.append(out[-1] if i and p == xp[i - 1] else i + 1)
    return out


def rank_among(xp: int, others: Iterable[int]) -> int:
    """Where someone with `xp` would stand among `others`, sharing the rank of anyone level."""
    return 1 + sum(1 for p in others if p > xp)


@dataclass(frozen=True)
class Member:
    vertical: str | None
    xp: int
    played_this_week: bool


@dataclass(frozen=True)
class VerticalScore:
    vertical: str
    members: int
    xp_per_member: float
    participation: float


def vertical_board(members: Iterable[Member]) -> list[VerticalScore]:
    """Average xp per member and the share who played this week, best average first.
    Verticals with too few members to average fairly are left out."""
    by_vertical: dict[str, list[Member]] = {}
    for m in members:
        if m.vertical:
            by_vertical.setdefault(m.vertical, []).append(m)
    rows = [
        VerticalScore(
            vertical=v,
            members=len(ms),
            xp_per_member=round(sum(m.xp for m in ms) / len(ms), 1),
            participation=round(sum(m.played_this_week for m in ms) / len(ms), 3),
        )
        for v, ms in by_vertical.items()
        if len(ms) >= MIN_VERTICAL
    ]
    return sorted(rows, key=lambda r: (-r.xp_per_member, -r.participation, r.vertical))
