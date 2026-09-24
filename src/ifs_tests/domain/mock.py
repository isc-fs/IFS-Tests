"""Mock quiz rules: seasons, runs left untouched and the bar to beat."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

STALE_AFTER = timedelta(days=2)  # the nightly job ends a run nobody has touched for this long


def season(day: date) -> int:
    """Seasons run September to August and are named by the year they start in."""
    return day.year if day.month >= 9 else day.year - 1


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
