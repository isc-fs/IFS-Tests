"""The rank: how well you answer, in League-style divisions and LP that go up and down (ADR 0007).

One number, rank points: 100 per division, Mingo I at 0, DT V at 1400, the top from 1500 with uncapped LP.
Each answer moves it Elo-style against the question's rating, so blind guessing never pays and you settle
where your accuracy puts you. The account level (domain/xp.py) is separate and only goes up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .daily import madrid_day
from .mock import season

DIVISION = 100
TIERS = ("Mingo", "Jefe", "DT")
DIVISIONS = ("I", "II", "III", "IV", "V")
TOP = len(TIERS) * len(DIVISIONS)  # the division past DT V
TOP_POINTS = TOP * DIVISION
# The title waiting at the top depends on the vertical; nobody sees it until DT V.
TOP_TITLES = {
    "Mechanical": "Gigante Noble",
    "Electronics": "Villano",
    "Tractive System": "Villano",
    "Driverless": "Villano",
}
TOP_TITLE = "Leyenda"

# A question's rating from its difficulty (1-5), on the same scale as rank points.
Q_MID, Q_STEP, SCALE = 650, 170, 600
# Practice is for learning and live answers are a table's: only the daily question and mock runs move the rank.
K = {"daily": 30.0, "mock": 20.0, "practice": 0.0, "live": 0.0}
REPEAT = 0.25  # a question already graded this season
HINT = 0.5  # of the gain
PASS = 0.5  # "I'm not sure" costs half a wrong answer (never more than a blind guess): free passes would let
# anyone climb forever
SOFTEN = {"choice-one": 1.0, "choice-many": 0.75}  # typed answers 0.5: a slip in a sum isn't not knowing
TYPED = 0.5
# Back on your feet: after this many wrong in a row, losses halve and the next right answer pays 1.5x (less on a
# single choice, where that would make a blind guess pay: see bad_run).
CUSHION_AFTER, CUSHION, COMEBACK = 3, 0.5, 1.5

# Where each position on the team is placed: its division, 50 LP in so one slip doesn't demote on day one.
PLACEMENT = {"mingo": 0, "member": 3, "department_head": 5, "technical_director": 10}
SEASON_DROP = 300  # each September everyone climbs back from three divisions lower


@dataclass(frozen=True)
class Division:
    number: int
    tier: str  # "Mingo", "Jefe", "DT" or "Top"
    division: str  # "I" to "V"; empty at the top
    formulas: bool
    learn_more: bool
    hint: bool
    stakes: float  # how hard a wrong answer bites, from 0.80 at Mingo I to 1.25 at the top


# (formulas, learn more, hint) from Mingo I to the top: one training wheel at a time. They come back if you drop.
_AIDS = (
    [(True, True, True)] * 4
    + [(True, False, True)]
    + [(False, False, True)] * 5
    + [(False, False, False)] * 6
)
DIVISION_TABLE = tuple(
    Division(
        n,
        TIERS[n // 5] if n < TOP else "Top",
        DIVISIONS[n % 5] if n < TOP else "",
        *_AIDS[n],
        stakes=round(0.80 + 0.03 * n, 2),
    )
    for n in range(TOP + 1)
)


@dataclass(frozen=True)
class Rank:
    points: float
    division: Division
    lp: float  # points into the division (above 1500 at the top, uncapped)
    title: str


def division_of(points: float) -> int:
    return min(int(max(points, 0) // DIVISION), TOP)


def title(division: int, vertical: str | None) -> str:
    """ "Mingo III", "Jefe I", "DT V", or the vertical's title at the top."""
    d = DIVISION_TABLE[min(division, TOP)]
    if d.number == TOP:
        return TOP_TITLES.get(vertical or "", TOP_TITLE)
    return f"{d.tier} {d.division}"


def rank_of(points: float, vertical: str | None = None) -> Rank:
    n = division_of(points)
    return Rank(points, DIVISION_TABLE[n], round(points - n * DIVISION, 2), title(n, vertical))


def placement(position: str) -> float:
    return PLACEMENT[position] * DIVISION + 50.0


def reposition(points: float, old: str, new: str, lifts: dict[str, float]) -> tuple[float, dict[str, float]]:
    """A new position on the team places them again. A higher one lifts the rank to at least its placement and
    records, per position crossed, the LP that lift gave. A lower one takes back those lifts (for a position held
    since sign-up or since before this season, its whole head start: the gap to the placement below), keeping
    what they earned, so undoing a mistaken raise puts them back where they were. Floor 0."""
    ladder = sorted(PLACEMENT, key=PLACEMENT.__getitem__)
    lo, hi = sorted((ladder.index(old), ladder.index(new)))
    crossed = ladder[lo + 1 : hi + 1]
    lifts = dict(lifts)
    if PLACEMENT[new] > PLACEMENT[old]:
        for p in crossed:
            lifts[p] = max(placement(p) - points, 0.0)
            points += lifts[p]
        return points, lifts
    width = {p: placement(p) - placement(ladder[ladder.index(p) - 1]) for p in crossed}
    back = sum(lifts.pop(p, width[p]) for p in crossed)
    return max(points - back, 0.0), lifts


def season_reset(points: float, position: str) -> float:
    """1 September: three divisions back (the top counts as 1500), never below your position's placement, and
    never above where you finished."""
    return max(min(placement(position), points), min(points, TOP_POINTS) - SEASON_DROP)


def season_of(now: datetime) -> int:
    return season(madrid_day(now))


def current_points(points: float, placed_in: int, position: str, now: datetime) -> float:
    """Rank points as they stand this season: a season not yet started for this player resets first.
    Season 0 is someone placed by the migration, or who joined through the release before it (not placed)."""
    if placed_in == 0:
        return max(points, placement(position))
    if placed_in == season_of(now):
        return points
    return season_reset(points, position)


def standing(points: float, placed_in: int, position: str, vertical: str | None, now: datetime) -> Rank:
    """Someone's rank as it stands now, the season's reset included even before their next answer."""
    return rank_of(current_points(points, placed_in, position, now), vertical)


def expected(points: float, difficulty: int, answer_kind: str, options: int) -> float:
    """How likely someone at this rank gets the question right. The guess floor makes a blind guess on a
    single choice break even at any rank."""
    guess = 1 / options if answer_kind == "choice-one" and options > 1 else 0.0
    rating = Q_MID + Q_STEP * (difficulty - 3)
    return guess + (1 - guess) / (1 + math.exp(-(points - rating) / SCALE))


def bad_run(gain: float, loss: float, answer_kind: str, options: int) -> float:
    """How much of the cushion and comeback a bad run gets, from 0 to 1. All of it, except on a single choice:
    there a blind guess must still lose on average at least CUSHION of what it loses outside a bad run, so the
    comeback and the cushion shrink together until it does (a blind guess never pays, and "I'm not sure" never
    costs nothing)."""
    if answer_kind != "choice-one" or options < 2:
        return 1.0
    misses = options - 1  # a blind guess: one right for every `misses` wrong
    short = misses * loss - gain  # what it loses on average, times options; positive at any sane rank
    moved = (COMEBACK - 1) * gain + (1 - CUSHION) * misses * loss  # how much a full bad run shifts that
    return max(0.0, min(1.0, (1 - CUSHION) * short / moved))


@dataclass(frozen=True)
class Lp:
    amount: float
    cushioned: bool = False
    comeback: bool = False


def lp_award(
    correct: bool | None,
    points: float,
    difficulty: int,
    mode: str,
    *,
    area: str | None = "rules",
    answer_kind: str = "choice-one",
    options: int = 4,
    hint: bool = False,
    repeat: bool = False,
    late: bool = False,
    passed: bool = False,
    again_today: bool = False,
    miss_streak: int = 0,
) -> Lp:
    """LP for one answer (the defaults describe a rules question). Right: K x (1 - expected); wrong or late:
    K x expected x stakes, softer for typed and multiple-choice slips. "I'm not sure" in time costs half a
    wrong answer, never more than a blind guess would lose on average. A hint on a single choice leaves it a
    two-way guess. A question already graded today moves nothing if right; ungraded ones never move LP."""
    if correct is None:
        return Lp(0.0)
    if hint and answer_kind == "choice-one":
        options = min(options, 2)
    k = K[mode] * (REPEAT if repeat else 1)
    e = expected(points, difficulty, answer_kind, options)
    # Slips in a sum aren't not knowing a rule, and typed answers play harder than their rating: both ways.
    k *= 1.0 if area == "rules" else SOFTEN.get(answer_kind, TYPED)
    gain = k * (1 - e) * (HINT if hint else 1)
    loss = k * e * DIVISION_TABLE[division_of(points)].stakes
    down = bad_run(gain, loss, answer_kind, options) if miss_streak >= CUSHION_AFTER else 0.0
    gain *= 1 + down * (COMEBACK - 1)
    loss *= 1 - down * (1 - CUSHION)
    if correct and not late and not passed:
        if again_today:
            return Lp(0.0)
        return Lp(round(gain, 2), comeback=down > 0 and gain > 0)
    if passed and not late:
        loss *= PASS
        if answer_kind == "choice-one" and options > 1:
            loss = min(loss, max(0.0, (1 - 1 / options) * loss / PASS - gain / options))
    return Lp(-round(loss, 2), cushioned=down > 0 and loss > 0)


def next_miss_streak(miss_streak: int, correct: bool | None, passed: bool, late: bool) -> int:
    """Wrong answers in a row. A right answer ends it; a pass or an ungraded question leaves it alone."""
    if correct is None or (passed and not late):
        return miss_streak
    return 0 if correct and not late else miss_streak + 1


def swing(points: float) -> tuple[float, float]:
    """What a daily question of middling difficulty is worth right and wrong at this rank, for the rank card."""
    return (
        lp_award(True, points, 3, "daily").amount,
        lp_award(False, points, 3, "daily").amount,
    )
