"""XP: the one currency. It sets your level (lifetime XP) and your place on the leaderboard (XP earned in the
period). Levels bring titles and take the training wheels away: fewer aids, and wrong answers start to cost XP.

The numbers were chosen by simulation (see docs/adr/0004-xp-and-levels.md): an active newcomer reaches the
Department Head band in about five weeks and the Technical Director band in about four months, i.e. around the
January registration quizzes; a typical player gets there in a season or two.
"""

from __future__ import annotations

from dataclasses import dataclass

CURVE_K, CURVE_E = 25, 2.3
BASE_XP = {1: 10, 2: 15, 3: 25, 4: 40, 5: 60}
MODE = {"practice": 0.5, "daily": 2.0, "mock": 1.5}
REPEAT = 0.1  # a question you already got right before, or a mock replay
HINT = 0.5
STREAK_STEP, STREAK_CAP = 0.05, 10  # +5 % per day of streak after the first, up to +50 %
MIN_SAMPLE = 20  # answers before success rates start to move a question's difficulty


@dataclass(frozen=True)
class Tier:
    name: str
    first_level: int
    formulas: bool
    learn_more: bool
    hint: bool
    penalty: float  # share of a correct answer's XP lost on a wrong one


TIERS = (
    Tier("Mingo", 0, True, True, True, 0.0),
    Tier("Rookie", 4, True, True, True, 0.0),
    Tier("Engineer", 8, True, False, True, 0.1),
    Tier("Department Head", 12, False, False, True, 0.25),
    Tier("Senior", 16, False, False, False, 0.5),
    Tier("Technical Director", 20, False, False, False, 0.75),
)

# Where each rank starts. People choose their rank when they join; admins can correct it.
RANKS = {"mingo": 0, "member": 8, "department_head": 12, "technical_director": 20}


def xp_for_level(level: int) -> int:
    """Lifetime XP needed to reach `level` (level 0 needs none)."""
    return int(round(CURVE_K * level**CURVE_E))


def level_for(xp: int) -> int:
    level = 0
    while xp_for_level(level + 1) <= xp:
        level += 1
    return level


def tier(level: int) -> Tier:
    return [t for t in TIERS if level >= t.first_level][-1]


def floor_for(rank: str) -> int:
    """Nobody drops below the level their rank starts at, however many wrong answers."""
    return xp_for_level(RANKS[rank])


PRIOR = {"choice-one": 2, "choice-many": 3, "numbers": 4}


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


def streak_multiplier(streak_days: int) -> float:
    return 1 + STREAK_STEP * min(max(streak_days - 1, 0), STREAK_CAP)


def award(
    correct: bool | None,
    difficulty: int,
    mode: str,
    level: int,
    streak_days: int = 0,
    hint: bool = False,
    repeat: bool = False,
    late: bool = False,
    again_today: bool = False,
) -> int:
    """XP for one answer: positive when right, zero or negative when wrong depending on your tier.
    A late answer (or one left to run out) counts as wrong, so waiting out the clock never beats trying.
    Ungraded questions give nothing either way; a question already got right again today gives nothing."""
    if correct is None:
        return 0
    if correct and again_today and not late:
        return 0
    base = BASE_XP[difficulty] * MODE[mode] * (REPEAT if repeat else 1)
    if correct and not late:
        return max(1, round(base * streak_multiplier(streak_days) * (HINT if hint else 1)))
    return -round(base * tier(level).penalty)
