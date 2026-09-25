from __future__ import annotations

import random
import statistics
from typing import Any

import pytest

from ifs_tests.domain.rank import (
    DIVISION_TABLE,
    TOP,
    expected,
    lp_award,
    next_miss_streak,
    placement,
    rank_of,
    season_reset,
    swing,
    title,
)


@pytest.mark.parametrize(
    ("points", "name", "lp"),
    [
        (0, "Mingo I", 0),
        (99.5, "Mingo I", 99.5),
        (100, "Mingo II", 0),
        (550, "Jefe I", 50),
        (1499, "DT V", 99),
    ],
)
def test_divisions_are_100_lp(points: float, name: str, lp: float) -> None:
    r = rank_of(points)
    assert (r.title, r.lp) == (name, lp)


def test_the_top_keeps_counting_lp_and_depends_on_the_vertical() -> None:
    assert rank_of(1500, "Mechanical").title == "Gigante Noble"
    assert rank_of(2240, "Driverless").lp == 740
    assert title(TOP, "Business") == "Leyenda"


def test_aids_come_off_one_at_a_time_and_stakes_only_grow() -> None:
    for a, b in zip(DIVISION_TABLE, DIVISION_TABLE[1:], strict=False):
        assert (b.formulas <= a.formulas, b.learn_more <= a.learn_more, b.hint <= a.hint) == (
            True,
            True,
            True,
        )
        assert b.stakes > a.stakes
    assert [d.number for d in DIVISION_TABLE if not d.learn_more][0] == 4  # reading ends at Mingo V
    assert [d.number for d in DIVISION_TABLE if not d.formulas][0] == 5  # formulas at Jefe I
    assert [d.number for d in DIVISION_TABLE if not d.hint][0] == 10  # hints at DT I
    assert (DIVISION_TABLE[0].stakes, DIVISION_TABLE[TOP].stakes) == (0.8, 1.25)


@pytest.mark.parametrize("points", [0, 300, 700, 1100, 1500, 2500])
@pytest.mark.parametrize("difficulty", [1, 3, 5])
@pytest.mark.parametrize("options", [2, 4, 5])
@pytest.mark.parametrize("miss_streak", [0, 3, 10])
def test_blind_guessing_never_pays(points: float, difficulty: int, options: int, miss_streak: int) -> None:
    p = 1 / options
    kw: dict[str, Any] = {"options": options, "miss_streak": miss_streak}
    right = lp_award(True, points, difficulty, "daily", **kw).amount
    wrong = lp_award(False, points, difficulty, "daily", **kw).amount
    assert p * right + (1 - p) * wrong <= 0.01


def test_right_answers_pay_more_low_down_and_wrong_ones_cost_more_up_high() -> None:
    assert swing(50) == (16.45, -10.84)
    low, high = swing(50), swing(1400)
    assert low[0] > high[0] and low[1] > high[1]
    assert expected(0, 5, "choice-one", 4) < expected(1500, 1, "choice-one", 4)


def test_slips_cost_less_than_not_knowing_and_passing_costs_half() -> None:
    wrong = lp_award(False, 700, 3, "daily", area="mech", answer_kind="choice-one").amount
    typed = lp_award(False, 700, 3, "daily", area="mech", answer_kind="number", options=0).amount
    many = lp_award(False, 700, 3, "daily", area="elec", answer_kind="choice-many", options=0).amount
    rules_typed = lp_award(False, 700, 3, "daily", area="rules", answer_kind="number", options=0).amount
    passed = lp_award(False, 700, 3, "daily", passed=True).amount
    assert wrong < 0 and many > wrong * 1 and typed > many
    assert rules_typed < typed  # a rule you don't know is not a slip
    assert passed == pytest.approx(lp_award(False, 700, 3, "daily").amount / 2, abs=0.01)
    assert (
        lp_award(False, 700, 3, "daily", passed=True, late=True).amount
        == lp_award(False, 700, 3, "daily").amount
    )


def test_modes_repeats_hints_and_what_moves_nothing() -> None:
    daily = lp_award(True, 300, 3, "daily").amount
    assert lp_award(True, 300, 3, "mock").amount == pytest.approx(daily * 2 / 3, abs=0.01)
    assert lp_award(True, 300, 3, "practice").amount == lp_award(False, 300, 3, "practice").amount == 0
    assert lp_award(True, 300, 3, "daily", repeat=True).amount == pytest.approx(daily / 4, abs=0.01)
    # A hint leaves a single choice a two-way guess, and halves what's left to win.
    two_way = lp_award(True, 300, 3, "daily", options=2).amount
    assert lp_award(True, 300, 3, "daily", hint=True).amount == pytest.approx(two_way / 2, abs=0.01)
    assert lp_award(
        True, 300, 3, "daily", answer_kind="numbers", area="mech", hint=True
    ).amount == pytest.approx(
        lp_award(True, 300, 3, "daily", answer_kind="numbers", area="mech").amount / 2, abs=0.01
    )
    assert lp_award(True, 300, 3, "live").amount == lp_award(False, 300, 3, "live").amount == 0
    assert lp_award(None, 300, 3, "daily").amount == 0  # ungraded
    assert lp_award(True, 300, 3, "daily", again_today=True).amount == 0
    assert lp_award(True, 300, 3, "daily", late=True).amount < 0  # late counts as wrong


def test_a_bad_run_is_cushioned_and_the_way_back_pays_more() -> None:
    miss = 0
    for _ in range(3):
        miss = next_miss_streak(miss, False, False, False)
    assert miss == 3
    typed: dict[str, Any] = {"area": "mech", "answer_kind": "number", "options": 0}
    fresh, down = (
        lp_award(False, 700, 3, "daily", **typed),
        lp_award(False, 700, 3, "daily", miss_streak=3, **typed),
    )
    assert down.cushioned and down.amount == pytest.approx(fresh.amount / 2, abs=0.01)
    back = lp_award(True, 700, 3, "daily", miss_streak=3, **typed)
    assert back.comeback and back.amount == pytest.approx(
        lp_award(True, 700, 3, "daily", **typed).amount * 1.5, abs=0.01
    )
    assert next_miss_streak(miss, True, False, False) == 0
    assert next_miss_streak(miss, False, True, False) == miss  # a pass leaves it alone
    assert next_miss_streak(miss, None, False, False) == miss


@pytest.mark.parametrize("points", [0, 50, 550, 1050, 1550])
@pytest.mark.parametrize("options", [2, 4])
def test_on_a_single_choice_a_bad_run_shrinks_until_a_blind_guess_still_loses(
    points: float, options: int
) -> None:
    def lp(correct: bool, miss_streak: int) -> float:
        return lp_award(correct, points, 3, "daily", options=options, miss_streak=miss_streak).amount

    right, wrong, back, cushioned = lp(True, 0), lp(False, 0), lp(True, 3), lp(False, 3)
    # Still a comeback and a cushion, at most the full ones.
    assert right < back <= right * 1.5 + 0.01 and wrong < cushioned <= wrong / 2 + 0.01
    guess = right / options + wrong * (1 - 1 / options)
    assert back / options + cushioned * (1 - 1 / options) <= guess / 2 + 0.01  # at least half the usual loss


def test_placement_and_the_season_reset() -> None:
    assert [placement(p) for p in ("mingo", "member", "department_head", "technical_director")] == [
        50,
        350,
        550,
        1050,
    ]
    assert season_reset(2400, "mingo") == 1200  # the top counts as 1500, then three divisions back
    assert season_reset(800, "mingo") == 500
    assert season_reset(1200, "technical_director") == 1050  # never below your position's placement
    assert season_reset(700, "technical_director") == 700  # nor above where you finished
    assert season_reset(100, "mingo") == 50


# The graded bank's mix, in twentieths: about a sixth rules; mostly single choice, a sixth typed.
MIX = (
    [("rules", "choice-one")] * 3
    + [("mech", "choice-one")] * 12
    + [("elec", "choice-many")]
    + [("mech", "number")] * 4
)


Run = tuple[dict[int, int], dict[int, float]]


def _season(
    seed: int, start: str, active: float, practice: int, mock_every: int, skill: float, improve: float
) -> Run:
    """A seeded season (September to August): dailies, some practice, a mock now and then, from a bank of 1,000
    questions (seen ones are easier). As services/xp.grant scores them: practice moves no LP (it only makes
    questions seen); only first-time daily and mock answers count towards a bad run."""
    rng = random.Random(seed)
    points, miss, seen = placement(start), 0, set()
    reached: dict[int, int] = {}
    trace: dict[int, float] = {}
    for day in range(1, 366):
        if rng.random() < active:
            plays = [("daily", 3), ("practice", practice)] + ([("mock", 10)] if day % mock_every == 0 else [])
            for mode, n in plays:
                for _ in range(n):
                    d = rng.choice([1, 2, 2, 3, 3, 3, 4, 4, 5])
                    area, kind = rng.choice(MIX)
                    q = rng.randrange(1000)
                    repeat = q in seen
                    seen.add(q)
                    p = min(0.88, skill + day * improve) - 0.06 * (d - 3)
                    right = rng.random() < (p + 0.3 * (1 - p) if repeat else p)
                    if mode == "practice":
                        continue
                    run = not repeat
                    lp = lp_award(
                        right,
                        points,
                        d,
                        mode,
                        area=area,
                        answer_kind=kind,
                        repeat=repeat,
                        miss_streak=miss if run else 0,
                    ).amount
                    points = max(0.0, points + lp)
                    if run:
                        miss = next_miss_streak(miss, right, False, False)
        for mark in (500, 1000, 1500):
            if points >= mark:
                reached.setdefault(mark, day)
        trace[day] = points
    return reached, trace


def _median_day(runs: list[Run], mark: int) -> float:
    days = [r[mark] for r, _ in runs if mark in r]
    return statistics.median(days) if len(days) > len(runs) // 2 else float("inf")  # most never got there


def test_pacing_matches_the_design() -> None:
    def runs(**kw: Any) -> list[Run]:
        return [_season(s, **kw) for s in range(9)]

    strong = runs(start="mingo", active=0.9, practice=10, mock_every=7, skill=0.55, improve=0.0015)
    typical = runs(start="mingo", active=0.6, practice=3, mock_every=14, skill=0.45, improve=0.0015)
    casual = runs(start="mingo", active=0.3, practice=0, mock_every=10**6, skill=0.45, improve=0.0015)
    weak_td = runs(start="technical_director", active=0.6, practice=3, mock_every=14, skill=0.5, improve=0)
    assert 20 <= _median_day(strong, 500) <= 45  # Jefe in about a month
    assert 120 <= _median_day(strong, 1000) <= 185  # DT around the January and February registration quizzes
    assert 280 <= _median_day(strong, 1500) <= 365  # the top, for the strongest, by the summer events
    assert 60 <= _median_day(typical, 500) <= 120 and _median_day(typical, 1500) == float("inf")
    assert _median_day(casual, 1500) == float("inf")
    # A Technical Director who answers half right drops out of DT within a month: the rank is earned.
    assert statistics.median(t[30] for _, t in weak_td) < 1000


@pytest.mark.parametrize("options", [2, 3, 4, 5])
@pytest.mark.parametrize("points", [0, 300, 550, 1050, 1450, 2000])
@pytest.mark.parametrize("difficulty", [1, 3, 5])
@pytest.mark.parametrize("hint", [False, True])
@pytest.mark.parametrize("miss_streak", [0, 3, 10])
def test_not_sure_never_costs_more_than_a_blind_guess_and_a_hinted_guess_never_pays(
    options: int, points: float, difficulty: int, hint: bool, miss_streak: int
) -> None:
    def lp(correct: bool, **kw: Any) -> float:
        return lp_award(
            correct, points, difficulty, "daily", options=options, hint=hint, miss_streak=miss_streak, **kw
        ).amount

    n = min(options, 2) if hint else options
    guess = lp(True) / n + lp(False) * (1 - 1 / n)
    assert guess <= 0.01
    assert guess - 0.01 <= lp(False, passed=True) < 0  # and "I'm not sure" never costs nothing
