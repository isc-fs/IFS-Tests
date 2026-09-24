"""Daily question rules: which question, how long you get, whether you were late, and streaks."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
AREAS = ("mech", "elec", "rules")
GRACE = timedelta(seconds=3)
MIN_BUDGET, MAX_BUDGET = 60, 600
DEFAULT_BUDGET = {"choice-one": 120, "choice-many": 150}
TYPED_BUDGET = 240
POOL = 20  # the day's question is drawn from this many least recently used ones


def madrid_day(now: datetime) -> date:
    """The day as the team lives it: midnight in Madrid, whatever the server's clock says."""
    return now.astimezone(MADRID).date()


@dataclass(frozen=True)
class Candidate:
    id: int
    last_used: date | None  # last day it was a daily question
    practised: int  # attempts by anyone, in any mode


def _draw(secret: bytes, day: date, area: str, qid: int) -> bytes:
    return hmac.new(secret, f"{day}:{area}:{qid}".encode(), hashlib.sha256).digest()


def pick(candidates: list[Candidate], day: date, area: str, secret: bytes = b"") -> int | None:
    """Drawn with a server secret from the least recently used (then least practised) questions, so nobody
    can work out tomorrow's question from the public bank. Small pools just take the least recently used."""
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda c: (c.last_used or date.min, c.practised, c.id))
    pool = ranked[: max(1, min(POOL, len(ranked) // 4))]
    return min(pool, key=lambda c: _draw(secret, day, area, c.id)).id


def budget(time_s: int | None, answer_kind: str) -> int:
    """Seconds allowed: the real quiz's budget when known, otherwise a default by kind of answer."""
    seconds = time_s or DEFAULT_BUDGET.get(answer_kind, TYPED_BUDGET)
    return max(MIN_BUDGET, min(MAX_BUDGET, seconds))


def is_late(submitted: datetime, deadline: datetime) -> bool:
    return submitted > deadline + GRACE


FREEZE_EVERY, FREEZE_CAP = 7, 2  # a streak freeze every 7 days of streak, at most 2 held


def freeze_needed(kept: set[date], yesterday: date) -> bool:
    """Yesterday was missed while the streak was still alive the day before: a freeze can save it."""
    return yesterday not in kept and yesterday - timedelta(days=1) in kept


def freeze_earned(kept: set[date], played: set[date], yesterday: date) -> bool:
    """Yesterday was played and brought the streak (freezes included) to a multiple of 7."""
    return yesterday in played and streak(kept, yesterday) % FREEZE_EVERY == 0


def streak(days: set[date], today: date) -> int:
    """Consecutive days with an on-time daily answer, ending today (or yesterday, if today is still open)."""
    day = today if today in days else today - timedelta(days=1)
    count = 0
    while day in days:
        count += 1
        day -= timedelta(days=1)
    return count
