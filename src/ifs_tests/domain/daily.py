"""Daily question rules: which question, how long you get, whether you were late, and streaks."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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


def released_at(day: date) -> datetime:
    """When a daily of `day` reveals its result: the Madrid midnight that closes the day (ADR 0010)."""
    return datetime.combine(day + timedelta(days=1), time(), MADRID)


def per_player(day: date, rules_from: date | None) -> bool:
    """Season 1b: from this Madrid day the daily is drawn per player (ADR 0010). The one copy of the switch."""
    return rules_from is not None and day >= rules_from


@dataclass(frozen=True)
class PlayerCandidate:
    id: int
    reserved: (
        bool  # on screen elsewhere: an unfinished live session, or shown and unanswered in an open mock run
    )
    played_today: bool  # this player already answered it today, in any mode: a daily on it would pay nothing
    drawn_today: int  # daily attempts by anyone on it today (carried-open ones from yesterday included)
    answered_today: int  # of those, submitted: the key is out
    last_drawn: date | None  # last Madrid day it was anyone's daily
    last_seen: (
        date | None
    )  # last day this player had it graded this season, as of midnight (xp.last_seen's rule)


def _draw_for(secret: bytes, day: date, area: str, user_id: int, qid: int) -> bytes:
    return hmac.new(secret, f"{day}:{area}:{user_id}:{qid}".encode(), hashlib.sha256).digest()


def pick_for(
    candidates: list[PlayerCandidate], day: date, area: str, user_id: int, secret: bytes = b""
) -> int | None:
    """Ranks, never excludes: a tiny pool still gives a question. Nothing another surface is showing right now,
    then a question nobody drew today (two players rarely share one), then one this player hasn't answered today
    (a daily on it would pay nothing; it ranks below the spread so that answering a whole area can't steer two
    players onto one question), then one whose key nobody has yet, then unseen by this player this season, then
    the least recently anyone's daily, the least drawn today, the one this player saw longest ago, and an HMAC
    with the player in it."""
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda c: (
            c.reserved,
            c.drawn_today > 0,
            c.played_today,
            c.answered_today > 0,
            c.last_seen is not None,
            c.last_drawn or date.min,
            c.drawn_today,
            c.last_seen or date.min,
            _draw_for(secret, day, area, user_id, c.id),
        ),
    ).id


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


@dataclass(frozen=True)
class Freezes:
    spent: list[date]  # days a freeze saved
    held: int
    earned_on: date | None
    earned: int


def settle(
    played: set[date], kept: set[date], held: int, earned_on: date | None, today: date, nights: int
) -> Freezes:
    """The last `nights` days before today, oldest first: spend a freeze on a day missed mid-streak, then give
    one when a played day brought the streak to a multiple of 7. The nightly job stores the result; anything
    reading the streak before it runs applies the same freezes from midnight."""
    saved, spent, earned = set(kept), [], 0
    for back in range(nights, 0, -1):
        day = today - timedelta(days=back)
        if held > 0 and freeze_needed(saved, day):
            saved.add(day)
            spent.append(day)
            held -= 1
        if freeze_earned(saved, played, day) and (earned_on is None or earned_on < day) and held < FREEZE_CAP:
            held += 1
            earned_on = day
            earned += 1
    return Freezes(spent, held, earned_on, earned)


def streak(days: set[date], today: date) -> int:
    """Consecutive days with an on-time daily answer, ending today (or yesterday, if today is still open)."""
    day = today if today in days else today - timedelta(days=1)
    count = 0
    while day in days:
        count += 1
        day -= timedelta(days=1)
    return count
