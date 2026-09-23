"""Daily question rules: which question, how long you get, whether you were late, and streaks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
AREAS = ("mech", "elec", "rules")
GRACE = timedelta(seconds=3)
MIN_BUDGET, MAX_BUDGET = 60, 600
DEFAULT_BUDGET = {"choice-one": 120, "choice-many": 150}
TYPED_BUDGET = 240


def madrid_day(now: datetime) -> date:
    """The day as the team lives it: midnight in Madrid, whatever the server's clock says."""
    return now.astimezone(MADRID).date()


@dataclass(frozen=True)
class Candidate:
    id: int
    last_used: date | None  # last day it was a daily question
    practised: int  # attempts by anyone, in any mode


def _tie_break(day: date, area: str, qid: int) -> str:
    return hashlib.sha256(f"{day}:{area}:{qid}".encode()).hexdigest()


def pick(candidates: list[Candidate], day: date, area: str) -> int | None:
    """Least recently used first, then least practised, then a stable pseudo-random order per day."""
    if not candidates:
        return None
    best = min(
        candidates,
        key=lambda c: (c.last_used or date.min, c.practised, _tie_break(day, area, c.id)),
    )
    return best.id


def budget(time_s: int | None, answer_kind: str) -> int:
    """Seconds allowed: the real quiz's budget when known, otherwise a default by kind of answer."""
    seconds = time_s or DEFAULT_BUDGET.get(answer_kind, TYPED_BUDGET)
    return max(MIN_BUDGET, min(MAX_BUDGET, seconds))


def is_late(submitted: datetime, deadline: datetime) -> bool:
    return submitted > deadline + GRACE


def streak(days: set[date], today: date) -> int:
    """Consecutive days with an on-time daily answer, ending today (or yesterday, if today is still open)."""
    day = today if today in days else today - timedelta(days=1)
    count = 0
    while day in days:
        count += 1
        day -= timedelta(days=1)
    return count
