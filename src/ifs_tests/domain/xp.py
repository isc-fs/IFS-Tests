"""XP and the account level: time played, and the rewards that keep you coming back (ADR 0007). XP only
goes up; how well you answer is the rank's job (domain/rank.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

BASE_XP = {1: 10, 2: 15, 3: 25, 4: 40, 5: 60}
MODE = {"practice": 0.75, "daily": 2.0, "mock": 1.5, "live": 1.5}
REPEAT = 0.25
HINT = 0.5
WRONG, PASS = 0.3, 0.1  # shares of a right answer's XP: League pays for losses too
# Bonuses on right answers, added (never multiplied) on top of the base.
FIRST_WINS, FIRST_WIN = 3, 0.5  # the first three right answers of the day
COMBO_STEP, COMBO_CAP = 0.1, 5  # +10 % per right answer in a row before this one, up to +50 %
STREAK_STEP, STREAK_CAP = 0.05, 10  # +5 % per day of daily streak after the first, up to +50 %
CRIT_CHANCE, CRIT = 0.05, 1.0  # a rare double
RESTED_PER_DAY, RESTED_CAP = 150, 450  # XP banked per full day away; it doubles XP until spent
MILESTONES = (10, 25, 50, 100)  # account levels that earn an emblem frame

MIN_SAMPLE = 20  # answers before success rates start to move a question's difficulty
# Single choice starts at 3 like typed answers: with the guess floor, a 2 made it look easier than it plays.
PRIOR = {"choice-one": 3, "choice-many": 3, "numbers": 4}


@dataclass(frozen=True)
class Xp:
    amount: int
    bonuses: dict[str, int] = field(default_factory=dict)


def streak_bonus(streak_days: int) -> float:
    return STREAK_STEP * min(max(streak_days - 1, 0), STREAK_CAP)


def xp_award(
    correct: bool | None,
    difficulty: int,
    mode: str,
    *,
    answered: bool = True,
    hint: bool = False,
    repeat: bool = False,
    late: bool = False,
    passed: bool = False,
    again_today: bool = False,
    first_win: bool = False,
    combo: int = 0,
    streak_days: int = 0,
    crit: bool = False,
    rested: int = 0,
) -> Xp:
    """XP for one answer: something for every answer given, the most for a right one plus its bonuses. A
    question left to run out gives nothing, and one already graded today gives nothing again. `rested` is the
    rested XP banked: it doubles a right answer's base while it lasts (the caller spends what the bonus used)."""
    if not answered or again_today:
        return Xp(0)
    base = BASE_XP[difficulty] * MODE[mode] * (REPEAT if repeat else 1) * (HINT if hint else 1)
    if correct is None or passed:
        return Xp(round(base * PASS))
    if not correct or late:
        return Xp(round(base * WRONG))
    shares = {
        "first_win": FIRST_WIN if first_win else 0.0,
        "combo": COMBO_STEP * min(combo, COMBO_CAP),
        "streak": streak_bonus(streak_days),
        "crit": CRIT if crit else 0.0,
    }
    bonuses = {k: round(base * v) for k, v in shares.items() if round(base * v) > 0}
    if rested > 0:
        bonuses["rested"] = min(max(1, round(base)), rested)
    return Xp(max(1, round(base)) + sum(bonuses.values()), bonuses)


def rested_bank(bank: int, days_away: int) -> int:
    """Rested XP after `days_away` full days without playing."""
    return min(RESTED_CAP, bank + RESTED_PER_DAY * max(days_away, 0))


def to_next(level: int) -> int:
    """XP from `level` to the next: 300 at first, 50 more each level, then 1,500 a level from level 25."""
    return 250 + 50 * min(level, 25)


def account_level(xp: int) -> tuple[int, int, int]:
    """(level, XP into it, XP it needs). Everyone starts at level 1."""
    level, left = 1, max(xp, 0)
    while left >= to_next(level):
        left -= to_next(level)
        level += 1
    return level, left, to_next(level)


def difficulty(answer_kind: str, time_s: int | None, answered: int = 0, right: int = 0) -> int:
    """1 (easy) to 5 (hard). A prior from the kind of answer and the real quiz's time budget, pulled towards
    how people actually did once enough of them have answered."""
    prior = PRIOR.get(answer_kind, 3)
    if time_s:
        prior += 1 if time_s >= 360 else -1 if time_s <= 60 else 0
    prior = min(5, max(1, prior))
    if answered < MIN_SAMPLE:
        return prior
    rate = right / answered
    observed = 1 if rate >= 0.8 else 2 if rate >= 0.6 else 3 if rate >= 0.4 else 4 if rate >= 0.2 else 5
    return round((prior + 2 * observed) / 3)
