"""Mock quiz rules: seasons, clocks, runs left untouched and the bar to beat."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .daily import DEFAULT_BUDGET, TYPED_BUDGET

MIN_TIME, MAX_TIME = 10, 3600  # a question's time in the real quiz; anything outside is bad data
STALE_AFTER = timedelta(days=2)  # the nightly job ends a run nobody has touched for this long


def season(day: date) -> int:
    """Seasons run September to August and are named by the year they start in."""
    return day.year if day.month >= 9 else day.year - 1


def budget(time_s: int | None, answer_kind: str) -> int:
    """Seconds a mock question allows: the time it had in the real quiz, or the daily question's default for its
    kind of answer when FS-Quiz doesn't say."""
    if not time_s or time_s < 0:
        return DEFAULT_BUDGET.get(answer_kind, TYPED_BUDGET)
    return max(MIN_TIME, min(MAX_TIME, time_s))


def bar_to_beat(last_qualifier: dict[str, Any] | None) -> str | None:
    """What the last team to get a registration slot achieved, in words."""
    if not last_qualifier:
        return None
    correct, score, time_s = (last_qualifier.get(k) for k in ("correct_answers", "score", "time_s"))
    parts = []
    if correct is not None:
        parts.append(f"{correct} correct answers")
    elif score is not None:
        parts.append(f"a score of {score}")
    if time_s:
        parts.append(f"in {time_s // 60} min {time_s % 60:02d} s")
    return "The last team to get a slot had " + " ".join(parts) + "." if parts else None
