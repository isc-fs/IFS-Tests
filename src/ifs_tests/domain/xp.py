"""XP: the one currency. It sets your level (lifetime XP) and your place on the leaderboard (XP earned in the
period). Levels climb like a competitive ladder, Mingo I to DT V and a last title at the top, and take the
training wheels away as you go: fewer aids, and wrong answers start to cost XP.

The numbers were chosen by simulation (see docs/adr/0004-xp-and-levels.md): an active newcomer reaches Jefe in
about five weeks and DT around the January registration quizzes; the top takes most of a season.
"""

from __future__ import annotations

from dataclasses import dataclass

STEP = 250  # level n needs STEP * n * (n + 1) lifetime XP: each level asks 500 XP more than the one before
BASE_XP = {1: 10, 2: 15, 3: 25, 4: 40, 5: 60}
MODE = {"practice": 0.5, "daily": 2.0, "mock": 1.5}
REPEAT = 0.1  # a question you already had graded this season, or a mock replay
HINT = 0.5
STREAK_STEP, STREAK_CAP = 0.05, 10  # +5 % per day of streak after the first, up to +50 %
MIN_SAMPLE = 20  # answers before success rates start to move a question's difficulty
# Outside the rules, wrong answers cost less: a slip in a calculation isn't not knowing a rule.
MANY_SHARE, TYPED_SHARE = 0.5, 0.25

TIERS = ("Mingo", "Jefe", "DT")
DIVISIONS = ("I", "II", "III", "IV", "V")
TOP = len(TIERS) * len(DIVISIONS)  # the last level, past DT V
# The title waiting at the top depends on the vertical; nobody sees it until DT V.
TOP_TITLES = {
    "Mechanical": "Gigante Noble",
    "Electronics": "Villano",
    "Tractive System": "Villano",
    "Driverless": "Villano",
}
TOP_TITLE = "Leyenda"


@dataclass(frozen=True)
class Level:
    number: int
    tier: str  # "Mingo", "Jefe", "DT" or "Top"
    division: str  # "I" to "V"; empty at the top
    formulas: bool
    learn_more: bool
    hint: bool
    penalty: float  # share of a correct answer's XP lost on a wrong one


# (formulas, learn more, hint, penalty) from Mingo I to the top: one training wheel at a time.
_AIDS = (
    (True, True, True, 0.0),
    (True, True, True, 0.0),
    (True, True, True, 0.0),
    (True, True, True, 0.05),
    (True, False, True, 0.1),
    (False, False, True, 0.15),
    (False, False, True, 0.2),
    (False, False, True, 0.25),
    (False, False, True, 0.3),
    (False, False, True, 0.35),
    (False, False, False, 0.45),
    (False, False, False, 0.5),
    (False, False, False, 0.55),
    (False, False, False, 0.6),
    (False, False, False, 0.7),
    (False, False, False, 0.75),
)
LEVELS = tuple(
    Level(n, TIERS[n // 5] if n < TOP else "Top", DIVISIONS[n % 5] if n < TOP else "", *aids)
    for n, aids in enumerate(_AIDS)
)

# Where each position on the team starts on the ladder. Chosen at sign-up; after that only admins change it.
START_LEVEL = {"mingo": 0, "member": 3, "department_head": 5, "technical_director": 10}


def xp_for_level(level: int) -> int:
    """Lifetime XP needed to reach `level` (Mingo I needs none)."""
    return STEP * level * (level + 1)


def level_for(xp: int) -> int:
    level = 0
    while level < TOP and xp_for_level(level + 1) <= xp:
        level += 1
    return level


def at(level: int) -> Level:
    return LEVELS[min(level, TOP)]


def title(level: int, vertical: str | None) -> str:
    """ "Mingo III", "Jefe I", "DT V", or the vertical's title at the top."""
    lv = at(level)
    if lv.number == TOP:
        return TOP_TITLES.get(vertical or "", TOP_TITLE)
    return f"{lv.tier} {lv.division}"


def floor_for(position: str) -> int:
    """Nobody drops below the level their position starts at, however many wrong answers."""
    return xp_for_level(START_LEVEL[position])


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


def penalty(level: int, area: str | None, answer_kind: str, options: int = 4) -> float:
    """Share of a right answer's XP that a wrong one costs. Rules questions take the level's full share: you
    know the rule or you don't. Elsewhere a single choice never costs more than makes a blind guess break
    even (1/(options - 1)), multiple choice half the share and typed answers a quarter."""
    share = at(level).penalty
    if area == "rules":
        return share
    if answer_kind == "choice-one":
        return min(share, 1 / (options - 1)) if options > 1 else 0.0
    if answer_kind == "choice-many":
        return share * MANY_SHARE
    return share * TYPED_SHARE


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
    *,
    area: str | None = "rules",
    answer_kind: str = "choice-one",
    options: int = 4,
    passed: bool = False,
) -> int:
    """XP for one answer: positive when right, zero or negative when wrong depending on the level and the kind
    of question (the defaults describe a rules question). Saying "I'm not sure" in time gives nothing either
    way. A late answer (or one left to run out) counts as wrong, so waiting out the clock never beats trying.
    Ungraded questions give nothing either way; a question already got right again today gives nothing."""
    if correct is None:
        return 0
    if passed and not late:
        return 0
    if correct and again_today and not late:
        return 0
    base = BASE_XP[difficulty] * MODE[mode] * (REPEAT if repeat else 1)
    if correct and not late:
        return max(1, round(base * streak_multiplier(streak_days) * (HINT if hint else 1)))
    return -round(base * penalty(level, area, answer_kind, options))
