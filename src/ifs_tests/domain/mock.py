"""Mock quiz rules: seasons, which session counts, points and the bar to beat."""

from __future__ import annotations

from datetime import date
from typing import Any

POINTS_PER_CORRECT = 2


def season(day: date) -> int:
    """Seasons run September to August and are named by the year they start in."""
    return day.year if day.month >= 9 else day.year - 1


def points(correct: int, counted: bool) -> int:
    """Only a player's first go at a quiz in a season scores, so replaying it can't farm points."""
    return POINTS_PER_CORRECT * correct if counted else 0


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
