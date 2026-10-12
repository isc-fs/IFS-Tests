"""The integrity report's rules (domain/integrity.py) and its settings: pure statistics, the LP replay and the
history-derived flags, written from the spec alone. Hand-computed LP numbers are `rank.lp_award` outputs at
350 points (a member's placement) written out here, never derived by calling the replay under test."""

from __future__ import annotations

import ast
import hashlib
import hmac
import itertools
import math
import os
import random
import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr, ValidationError

from ifs_tests.domain import integrity as rules
from ifs_tests.services import integrity as service
from ifs_tests.settings import IntegritySettings

SRC = Path(__file__).parents[2] / "src" / "ifs_tests"
MADRID = ZoneInfo("Europe/Madrid")


def md(month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=MADRID)


def thresholds(**over: Any) -> rules.Thresholds:
    base: dict[str, Any] = {
        "z": 1.96,
        "min_group": 3,
        "permutation_rounds": 2000,
        "bootstrap_rounds": 500,
        "seed": 0,
        "fixed_rank": 350.0,
        "shrink_m": 5.0,
        "min_n": 10,
        "follow_within": timedelta(minutes=30),
        "follow_min": 5,
        "follow_z": 2.5,
        "follow_relay_z": 2.5,
        "reading_floor_s": 12.0,
        "reading_cps": 15.0,
        "below_floor_share": 0.5,
        "narrow_sd_log": 0.15,
        "flat_corr": 0.1,
        "hard_residual_z": 2.5,
        "away_z": 2.0,
        "upstream_min": 5,
        "upstream_z": 2.5,
    }
    return rules.Thresholds(**{**base, **over})


# --- primitives -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("right", "n", "low", "high"),
    [(0, 10, 0.0, 0.2775), (10, 10, 0.7225, 1.0), (7, 10, 0.3968, 0.8922), (50, 100, 0.4038, 0.5962)],
)
def test_wilson_known_values(right: int, n: int, low: float, high: float) -> None:
    got_low, got_high = rules.wilson(right, n)
    assert got_low == pytest.approx(low, abs=1e-3)
    assert got_high == pytest.approx(high, abs=1e-3)
    assert 0.0 <= got_low <= right / n <= got_high <= 1.0


def test_wilson_without_data_knows_nothing_and_z_widens_it() -> None:
    assert rules.wilson(0, 0) == (0.0, 1.0)
    narrow, wide = rules.wilson(30, 60, 1.0), rules.wilson(30, 60, 2.58)
    assert wide[0] < narrow[0] < 0.5 < narrow[1] < wide[1]


@pytest.mark.parametrize(
    ("a_right", "a_n", "b_right", "b_n", "expected"),
    [
        (70, 100, 50, 100, 2.887),
        (50, 100, 70, 100, -2.887),
        (7, 0, 5, 10, None),  # nobody on the first side
        (10, 10, 10, 10, None),  # pooled rate 1: no variance
        (0, 10, 0, 10, None),  # pooled rate 0
    ],
)
def test_two_proportion_z(a_right: int, a_n: int, b_right: int, b_n: int, expected: float | None) -> None:
    got = rules.two_proportion_z(a_right, a_n, b_right, b_n)
    assert got is None if expected is None else got == pytest.approx(expected, abs=1e-3)


def test_tail_is_one_sided_and_holm_is_step_down() -> None:
    assert rules.tail(1.96) == pytest.approx(0.025, abs=1e-4)
    assert rules.tail(0.0) == pytest.approx(0.5)
    assert rules.tail(3.0) < rules.tail(2.0) < rules.tail(1.0)
    assert rules.holm([], 0.05) == []
    # 0.001 <= .05/3, 0.02 <= .05/2, 0.04 <= .05/1: all three fall
    assert rules.holm([0.001, 0.02, 0.04], 0.05) == [True, True, True]
    assert rules.holm([0.001, 0.02, 0.06], 0.05) == [True, True, False]
    # the smallest passes, the next (0.03 > .05/2) stops the procedure although 0.04 < .05
    assert rules.holm([0.01, 0.03, 0.04], 0.05) == [True, False, False]
    # the answer follows the input order, not the sorted one
    assert rules.holm([0.06, 0.001, 0.02], 0.05) == [False, True, True]
    assert rules.holm([0.2], 0.05) == [False]


@pytest.mark.parametrize(
    ("ps", "k", "expected"),
    [
        ([0.5] * 4, 4, 0.0625),
        ([0.5] * 4, 0, 1.0),
        ([0.5] * 4, 5, 0.0),
        ([0.2, 0.5], 1, 0.6),  # 1 - 0.8 * 0.5
        ([0.71 / 6] * 6, 4, 0.0024118),  # 6 items, 4 shared, E = 0.71: the normal tail says 1.6e-5
        ([1.06 / 6] * 6, 5, 0.00088056),  # 6 p^5 (1 - p) + p^6
    ],
)
def test_poisson_binomial_tail_is_exact(ps: list[float], k: int, expected: float) -> None:
    assert rules.poisson_binomial_sf(ps, k) == pytest.approx(expected, rel=1e-4)


def test_the_normal_tail_is_far_too_thin_for_a_rare_coincidence() -> None:
    ps = [0.71 / 6] * 6
    normal = rules.tail((4 - 0.71) / math.sqrt(sum(p * (1 - p) for p in ps)))
    assert normal < 1e-4 < rules.poisson_binomial_sf(ps, 4) / 10


def test_z_of_puts_a_p_value_on_the_threshold_scale() -> None:
    assert rules.z_of(rules.tail(2.5)) == pytest.approx(2.5)
    assert rules.z_of(0.5) == pytest.approx(0.0, abs=1e-12)
    assert rules.z_of(0.0) > 30 and rules.z_of(1.0) == rules.z_of(0.7) == 0.0  # one-sided: no evidence is 0


def test_pseudonym_is_8_hex_and_salt_bound() -> None:
    salt = b"s" * 32
    p = rules.pseudonym(salt, 900001)
    assert re.fullmatch(r"[0-9a-f]{8}", p)
    assert p == hmac.new(salt, b"900001", hashlib.sha256).hexdigest()[:8]
    assert p == rules.pseudonym(salt, 900001)
    assert p != rules.pseudonym(b"t" * 32, 900001)
    assert len({rules.pseudonym(salt, i) for i in range(500)}) == 500


def test_bootstrap_mean_is_seeded_and_needs_two_people() -> None:
    assert rules.bootstrap_mean([], rounds=100, seed=1, z=1.96) is None
    assert rules.bootstrap_mean([0.3], rounds=100, seed=1, z=1.96) is None
    low, high = cast(tuple[float, float], rules.bootstrap_mean([2.0] * 5, rounds=100, seed=1, z=1.96))
    assert (low, high) == pytest.approx((2.0, 2.0))
    values = [float(v) for v in range(1, 11)]
    first = rules.bootstrap_mean(values, rounds=300, seed=7, z=1.96)
    assert first == rules.bootstrap_mean(values, rounds=300, seed=7, z=1.96)
    assert first is not None and first[0] < 5.5 < first[1]
    wider = rules.bootstrap_mean(values, rounds=300, seed=7, z=2.58)
    assert wider is not None and wider[1] - wider[0] >= first[1] - first[0]


def test_spearman() -> None:
    assert rules.spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == pytest.approx(1.0)
    assert rules.spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)
    assert rules.spearman([1, 2, 3, 4, 5], [1, 3, 2, 5, 4]) == pytest.approx(0.8)
    assert rules.spearman([1, 2], [1, 2]) is None  # fewer than 3 pairs
    assert rules.spearman([4, 4, 4, 4], [1, 2, 3, 4]) is None  # a constant side
    assert rules.spearman([1, 2, 3, 4], [9, 9, 9, 9]) is None


# --- the replay ------------------------------------------------------------------------------------------------


def play(correct: bool | None = True, **kw: Any) -> rules.Play:
    base: dict[str, Any] = {
        "mode": "daily",
        "ranked": True,
        "area": "elec",
        "answer_kind": "choice-one",
        "difficulty": 3,
        "options": 4,
        "right_options": 1,
        "hint": False,
        "repeat": False,
        "late": False,
        "passed": False,
        "again_today": False,
        "lp": 0.0,
    }
    return rules.Play(correct=correct, **{**base, **kw})


MANY = {"answer_kind": "choice-many", "options": 5, "right_options": 2}
RULES_Q = {"area": "rules"}
TYPED = {"area": "mech", "answer_kind": "number", "options": 0, "right_options": 0}


@pytest.mark.parametrize(
    ("case", "p", "expected"),
    [
        ("right elec choice-many (SOFTEN 0.75)", play(True, **MANY), 13.55),
        ("wrong rules choice-one: stakes of Mingo IV, no SOFTEN", play(False, **RULES_Q), -14.24),
        ("wrong elec choice-many", play(False, **MANY), -7.96),
        ("wrong typed answer (TYPED 0.5)", play(False, **TYPED), -5.04),
        ("right with a hint pays less than half", play(True, hint=True), 4.67),
        ("a repeat pays a quarter", play(True, repeat=True), 3.5),
        ("a pass costs half a wrong answer", play(False, passed=True), -7.12),
        (
            "a pass is capped by what a blind guess loses (2 options)",
            play(False, passed=True, options=2),
            -4.53,
        ),
        ("not graded moves nothing", play(None), 0.0),
        ("right again today moves nothing", play(True, again_today=True), 0.0),
        ("right but late counts as wrong", play(True, late=True), -14.24),
        ("a timeout: wrong and late", play(False, late=True), -14.24),
        ("a mock answer is K 20, not 30", play(True, mode="mock"), 9.34),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_replay_hand_computed(case: str, p: rules.Play, expected: float) -> None:
    assert rules.replay_lp([p], 350.0) == pytest.approx([expected], abs=1e-9), case


def test_replay_reproduces_a_stored_path_with_every_branch() -> None:
    """18 plays in grading order, started at 350, with the LP each left stored (computed play by play)."""
    stored = [
        (play(True), 14.01),
        (play(False, difficulty=4, **MANY), -6.82),
        (play(False, late=True), -14.29),  # a daily left to run out: no answer, late, no hint
        (play(False, difficulty=2, **RULES_Q), -15.55),
        (play(False, mode="mock", **TYPED), -1.64),
        (play(True, hint=True), 6.13),
        (play(True, repeat=True), 3.54),
        (play(False, passed=True), -7.06),
        (play(None, **TYPED), 0.0),
        (play(True, again_today=True), 0.0),
        (play(False, mode="mock", ranked=False), 0.0),  # an uncounted run
        (play(False, mode="mock", difficulty=4, **RULES_Q), -8.53),
        (play(True, mode="mock", difficulty=5, **MANY), 10.94),
        (play(True, late=True), -14.08),
        (play(False), -13.98),
        (play(False), -13.87),
        (play(False), -10.2),  # fourth wrong in a row: cushioned
        (play(True), 18.0),  # and the comeback
    ]
    plays = [p for p, _ in stored]
    expected = [lp for _, lp in stored]
    assert rules.replay_lp(plays, 350.0) == pytest.approx(expected, abs=1e-9)
    assert round(350 + sum(expected), 2) == 296.6
    # the stored field of a Play is only data: the replay never reads it
    stale = [replace(p, lp=99.0) for p in plays]
    assert rules.replay_lp(stale, 350.0) == pytest.approx(expected, abs=1e-9)


W, R = play(False), play(True)


@pytest.mark.parametrize(
    ("case", "plays", "start", "kwargs", "expected"),
    [
        (
            "four wrong then right: cushion, then comeback",
            [W, W, W, W, R],
            350.0,
            {},
            [-14.24, -14.12, -14.01, -10.52, 17.86],
        ),
        (
            "a repeat is not a run: it does not advance the streak",
            [W, W, play(False, repeat=True), W, W],
            350.0,
            {},
            [-14.24, -14.12, -3.5, -13.99, -10.51],
        ),
        (
            "an answer again today is not a run either",
            [W, W, play(False, again_today=True), W, W],
            350.0,
            {},
            [-14.24, -14.12, -14.01, -13.91, -10.21],
        ),
        (
            "an uncounted run moves 0 and leaves the streak alone",
            [W, W, play(False, mode="mock", ranked=False), W, W],
            350.0,
            {},
            [-14.24, -14.12, 0.0, -14.01, -10.52],
        ),
        (
            "a pass leaves the streak alone",
            [W, W, play(False, passed=True), W, W],
            350.0,
            {},
            [-14.24, -14.12, -6.95, -13.96, -10.5],
        ),
        (
            "a right answer ends the streak",
            [W, W, W, R, W, W, W],
            350.0,
            {},
            [-14.24, -14.12, -14.01, 17.88, -14.04, -13.94, -13.36],
        ),
        (
            "right but late is a wrong in a row",
            [W, W, play(True, late=True), W],
            350.0,
            {},
            [-14.24, -14.12, -14.01, -10.52],
        ),
        (
            "an ungraded question leaves it alone",
            [W, W, play(None), W],
            350.0,
            {},
            [-14.24, -14.12, 0.0, -14.01],
        ),
        ("a streak carried in (miss0)", [W], 350.0, {"miss0": 3}, [-10.63]),
        ("a streak carried in then a right: comeback", [R], 350.0, {"miss0": 3}, [17.55]),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_replay_cushion_and_comeback(
    case: str, plays: list[rules.Play], start: float, kwargs: dict[str, Any], expected: list[float]
) -> None:
    assert rules.replay_lp(plays, start, **kwargs) == pytest.approx(expected, abs=1e-9), case


def test_replay_clips_at_zero_like_grant() -> None:
    got = rules.replay_lp([W, W, R], 1.0)
    assert got[0] == -1.0  # only the 1.0 LP there was to lose, as grant stores after - points
    assert got[1] == 0.0  # points stay 0
    assert got[2] == pytest.approx(16.81)  # and the next right answer pays from 0
    assert rules.replay_lp([W], 0.0) == [0.0]


def test_the_bad_run_crosses_the_season_change() -> None:
    """users.miss_streak is never reset in September: the replay of a season starts from the run the previous
    season left, counted on first-time ranked plays only."""
    assert rules.miss_after([W, W, W]) == 3
    assert rules.miss_after([W, W, play(True)]) == 0
    assert rules.miss_after([W, play(False, repeat=True), play(False, mode="mock", ranked=False)]) == 1
    assert rules.miss_after([W], miss0=2) == 3
    carried = rules.replay_lp([W], 0.0, fixed=350.0, miss0=rules.miss_after([W, W, W]))
    assert (
        carried
        == rules.replay_lp([W, W, W, W], 0.0, fixed=350.0)[3:]
        != rules.replay_lp([W], 0.0, fixed=350.0)
    )


def test_replay_of_nothing_is_nothing() -> None:
    assert rules.replay_lp([], 350.0) == []
    assert rules.replay_lp([], 350.0, fixed=350.0) == []


def test_fixed_rank_removes_the_placement_advantage() -> None:
    """A Mingo (50) and a DT (1050) with the same 20 right answers earn different LP in life, because the Elo
    update is rank-conditioned; at a fixed rank they earn exactly the same."""
    plays = [play(True)] * 20
    mingo, director = rules.replay_lp(plays, 50.0), rules.replay_lp(plays, 1050.0)
    assert sum(mingo) == pytest.approx(305.38, abs=0.05) and sum(director) == pytest.approx(141.35, abs=0.05)
    assert sum(mingo) > sum(director)
    flat_mingo = rules.replay_lp(plays, 50.0, fixed=350.0)
    flat_director = rules.replay_lp(plays, 1050.0, fixed=350.0)
    assert flat_mingo == flat_director == pytest.approx([14.01] * 20, abs=1e-9)
    assert rules.replay_lp(plays, 0.0, fixed=350.0) == flat_mingo  # the start is not even read


def test_fixed_rank_never_clips_and_the_streak_still_walks() -> None:
    got = rules.replay_lp([W, W, W, W, W], 0.0, fixed=350.0)
    assert got == pytest.approx([-14.24, -14.24, -14.24, -10.63, -10.63], abs=1e-9)
    assert all(x < 0 for x in got)  # a start of 0 would have clipped every one of them
    assert rules.replay_lp([W], 0.0, fixed=350.0, miss0=3) == pytest.approx([-10.63], abs=1e-9)
    unranked = play(False, mode="mock", ranked=False)
    assert rules.replay_lp([unranked, W], 350.0, fixed=350.0) == pytest.approx([0.0, -14.24], abs=1e-9)


# --- flags derived from the whole history ----------------------------------------------------------------------

_ids = itertools.count(1000)
DAY = date(2026, 10, 5)
DRAWN = {(DAY, "elec"): md(10, 5, 9)}  # the day's question started running at 09:00


def row(**kw: Any) -> rules.Row:
    base: dict[str, Any] = {
        "id": next(_ids),
        "question_id": 7,
        "mode": "daily",
        "created_at": md(10, 1, 10),
        "submitted_at": md(10, 1, 10, 5),
        "correct": True,
        "answered": True,
        "day": None,
        "area": "elec",
        "run_started_at": None,
        "counted": True,
        "late": False,
        "passed": False,
        "hint_used": False,
        "lp": 0.0,
    }
    return rules.Row(**{**base, **kw})


def practice(created: datetime, **kw: Any) -> rules.Row:
    return row(mode="practice", created_at=created, submitted_at=None, **kw)


def earlier_mock(started: datetime, created: datetime, submitted: datetime | None, **kw: Any) -> rules.Row:
    return row(mode="mock", run_started_at=started, created_at=created, submitted_at=submitted, **kw)


def daily_play(**kw: Any) -> rules.Row:
    base: dict[str, Any] = {
        "id": 1,
        "mode": "daily",
        "day": DAY,
        "created_at": md(10, 5, 10),
        "submitted_at": md(10, 5, 10, 5),
    }
    return row(**{**base, **kw})


def mock_play(**kw: Any) -> rules.Row:
    base: dict[str, Any] = {
        "id": 2,
        "mode": "mock",
        "run_started_at": md(10, 5, 10),
        "created_at": md(10, 5, 10, 20),
        "submitted_at": md(10, 5, 10, 25),
    }
    return row(**{**base, **kw})


def test_the_nightly_job_closes_the_dailies_before_the_mock_questions() -> None:
    """maintenance.run calls daily.close_expired and then mock.close_expired with the same `now`: a daily timeout
    is graded first even when the mock question was shown earlier and has the lower id."""
    at = md(10, 6, 3)
    mock_timeout = row(id=10, mode="mock", run_started_at=md(10, 5, 9), submitted_at=at, answered=False)
    daily_timeout = row(id=20, mode="daily", submitted_at=at, answered=False)
    assert sorted([mock_timeout, daily_timeout], key=rules.grading_order) == [daily_timeout, mock_timeout]
    assert rules.grading_order(row(id=1, submitted_at=at)) < rules.grading_order(row(id=2, submitted_at=at))


def test_graded_at_is_when_the_row_existed_as_graded() -> None:
    assert rules.graded_at(practice(md(10, 2, 9))) == md(10, 2, 9)
    live = row(mode="live", created_at=md(10, 2, 9), submitted_at=md(10, 2, 9))
    assert rules.graded_at(live) == md(10, 2, 9)
    assert rules.graded_at(row(mode="daily", created_at=md(10, 2, 9), submitted_at=md(10, 2, 9, 4))) == md(
        10, 2, 9, 4
    )
    assert rules.graded_at(earlier_mock(md(10, 2, 8), md(10, 2, 9), md(10, 2, 9, 3))) == md(10, 2, 9, 3)


@pytest.mark.parametrize(
    ("r", "hidden"),
    [
        (earlier_mock(md(10, 5, 8), md(10, 5, 8), md(10, 5, 9, 30), answered=False), True),
        (earlier_mock(md(10, 5, 8), md(10, 5, 8), md(10, 5, 9), answered=False), True),  # at `since`: >=
        (earlier_mock(md(10, 5, 8), md(10, 5, 8), md(10, 5, 8, 59), answered=False), False),  # before it
        (earlier_mock(md(10, 5, 8), md(10, 5, 8), md(10, 5, 9, 30), answered=True), False),  # a real answer
        (row(mode="daily", submitted_at=md(10, 5, 9, 30), answered=False), False),  # only mock runs hide
        (practice(md(10, 5, 9, 30)), False),
    ],
    ids=["after", "at-since", "before", "answered", "daily-timeout", "practice"],
)
def test_hidden_mock(r: rules.Row, hidden: bool) -> None:
    assert rules.hidden_mock(r, md(10, 5, 9)) is hidden


def test_season_anchor_is_the_run_start_for_a_mock_answer() -> None:
    assert rules.season_anchor(earlier_mock(md(8, 31, 20), md(9, 2, 10), md(9, 2, 10, 1))) == md(8, 31, 20)
    assert rules.season_anchor(row(created_at=md(9, 2, 10))) == md(9, 2, 10)


def test_running_since_is_the_draw_or_midnight_whichever_is_later() -> None:
    assert rules.running_since(DAY, "elec", DRAWN) == md(10, 5, 9)
    assert rules.running_since(DAY, "elec", {}) == md(10, 5, 0)  # drawn before drawn_at existed
    assert rules.running_since(DAY, "mech", DRAWN) == md(10, 5, 0)  # another area
    assert rules.running_since(DAY, "elec", {(DAY, "elec"): md(10, 4, 23)}) == md(
        10, 5, 0
    )  # never before midnight


_P = daily_play()
_M = mock_play()
_T = row(
    id=3,
    mode="daily",
    day=date(2026, 8, 31),
    created_at=md(8, 31, 23, 50),
    submitted_at=md(9, 1, 3),  # closed by the nightly job
    answered=False,
    late=True,
    correct=False,
)
_LAST = row(mode="practice", created_at=md(8, 31, 10), submitted_at=None)


@pytest.mark.parametrize(
    ("case", "p", "others", "expected"),
    [
        ("nothing else", _P, [], False),
        ("a practice answer before", _P, [practice(md(10, 3, 12))], True),
        ("a practice answer earlier the same day", _P, [practice(md(10, 5, 8))], True),
        ("a practice answer created after this play was graded", _P, [practice(md(10, 5, 10, 6))], False),
        (
            "a practice answer created at the very moment: not yet there",
            _P,
            [practice(md(10, 5, 10, 5))],
            False,
        ),
        (
            "an ungraded practice answer: never seen the answer",
            _P,
            [practice(md(10, 3, 12), correct=None)],
            False,
        ),
        ("another question", _P, [practice(md(10, 3, 12), question_id=8)], False),
        (
            "a live answer before",
            _P,
            [row(mode="live", created_at=md(10, 4, 9), submitted_at=md(10, 4, 9))],
            True,
        ),
        (
            "a daily graded last season",
            _P,
            [row(created_at=md(8, 30, 10), submitted_at=md(8, 30, 10, 5), day=date(2026, 8, 30))],
            False,
        ),
        (
            "the season starts at Madrid midnight, inclusive",
            _P,
            [row(created_at=md(9, 1, 0), submitted_at=md(9, 1, 0, 5), day=date(2026, 9, 1))],
            True,
        ),
        (
            "created the second before: last season even though graded after midnight",
            _P,
            [row(created_at=md(8, 31, 23, 59, 59), submitted_at=md(9, 1, 0, 5), day=date(2026, 8, 31))],
            False,
        ),
        (
            "a mock answer of a run started last season, answered this one: the run's season",
            _P,
            [earlier_mock(md(8, 31, 20), md(9, 2, 10), md(9, 2, 10, 1))],
            False,
        ),
        (
            "a mock answer of a run started this season",
            _P,
            [earlier_mock(md(9, 1, 8), md(9, 1, 8), md(9, 1, 8, 1))],
            True,
        ),
        (
            "a mock answer graded after this play was",
            _P,
            [earlier_mock(md(10, 5, 10, 30), md(10, 5, 10, 30), md(10, 5, 11))],
            False,
        ),
        (
            "a mock timeout since the daily started running is hidden from a daily play",
            _P,
            [
                earlier_mock(
                    md(10, 5, 8, 40), md(10, 5, 8, 50), md(10, 5, 9, 30), answered=False, correct=False
                )
            ],
            False,
        ),
        (
            "a mock timeout before the daily started running counts",
            _P,
            [
                earlier_mock(
                    md(10, 5, 8, 0), md(10, 5, 8, 10), md(10, 5, 8, 30), answered=False, correct=False
                )
            ],
            True,
        ),
        (
            "a mock row answered since the daily started running is seen",
            _P,
            [earlier_mock(md(10, 5, 8, 40), md(10, 5, 8, 50), md(10, 5, 9, 30))],
            True,
        ),
        (
            "rows still running (no answer yet) are not seen",
            _P,
            [
                row(mode="daily", day=date(2026, 10, 4), submitted_at=None, correct=None, answered=False),
                earlier_mock(md(10, 4, 8), md(10, 4, 8), None, answered=False, correct=None),
            ],
            False,
        ),
        ("the daily timeout takes its season from its own (the job's) clock", _T, [_LAST], False),
        (
            "a daily answered the minute before the season ends is still in the old one",
            row(
                id=4,
                mode="daily",
                day=date(2026, 8, 31),
                created_at=md(8, 31, 23, 50),
                submitted_at=md(8, 31, 23, 59),
            ),
            [_LAST],
            True,
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_is_repeat_mirrors_last_seen(
    case: str, p: rules.Row, others: list[rules.Row], expected: bool
) -> None:
    assert rules.is_repeat(p, [p, *others], DRAWN) is expected, case
    assert rules.is_repeat(p, [*others], DRAWN) is expected, f"{case} (history without the play itself)"


@pytest.mark.parametrize(
    ("case", "others", "expected"),
    [
        (
            "a mock timeout hidden from the daily is a repeat for the run",
            [
                earlier_mock(
                    md(10, 5, 8, 40), md(10, 5, 8, 50), md(10, 5, 9, 30), answered=False, correct=False
                )
            ],
            True,
        ),
        (
            "a mock run started last season has no say on a mock play started this one",
            [earlier_mock(md(8, 31, 20), md(9, 2, 10), md(9, 2, 10, 1))],
            False,
        ),
        ("nothing else", [], False),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_is_repeat_for_a_mock_play_has_no_hidden_filter(
    case: str, others: list[rules.Row], expected: bool
) -> None:
    assert rules.is_repeat(_M, [_M, *others], DRAWN) is expected, case


def test_a_mock_answer_takes_its_season_from_the_run_start() -> None:
    old = [practice(md(6, 15, 12))]  # last season
    started_last_season = mock_play(
        run_started_at=md(8, 31, 22), created_at=md(8, 31, 23), submitted_at=md(9, 1, 0, 30)
    )
    started_this_season = mock_play(
        run_started_at=md(9, 1, 8), created_at=md(9, 1, 8, 5), submitted_at=md(9, 1, 8, 10)
    )
    assert rules.is_repeat(started_last_season, [started_last_season, *old], {}) is True
    assert rules.is_repeat(started_this_season, [started_this_season, *old], {}) is False


@pytest.mark.parametrize(
    ("case", "p", "others", "expected"),
    [
        ("nothing else", _P, [], False),
        ("a practice answer today before the submit", _P, [practice(md(10, 5, 8))], True),
        ("a practice answer from yesterday", _P, [practice(md(10, 4, 23, 59, 59))], False),
        ("a practice answer at Madrid midnight, inclusive", _P, [practice(md(10, 5, 0, 0, 0))], True),
        ("a practice answer after the submit", _P, [practice(md(10, 5, 10, 6))], False),
        ("practice counts graded or not", _P, [practice(md(10, 5, 8), correct=None)], True),
        ("another question", _P, [practice(md(10, 5, 8), question_id=8)], False),
        (
            "created yesterday 23:59, submitted today: the created_at rule",
            _P,
            [
                row(
                    mode="daily",
                    day=date(2026, 10, 4),
                    created_at=md(10, 4, 23, 59),
                    submitted_at=md(10, 5, 0, 3),
                )
            ],
            False,
        ),
        (
            "a mock answer today before the submit",
            _P,
            [earlier_mock(md(10, 5, 8), md(10, 5, 9), md(10, 5, 9, 10))],
            True,
        ),
        (
            "a mock row still running does not count",
            _P,
            [earlier_mock(md(10, 5, 8), md(10, 5, 9), None, answered=False, correct=None)],
            False,
        ),
        (
            "a mock answer submitted after",
            _P,
            [earlier_mock(md(10, 5, 10), md(10, 5, 10, 1), md(10, 5, 10, 30))],
            False,
        ),
        (
            "a mock timeout hidden from a daily answer is not an answer today",
            _P,
            [earlier_mock(md(10, 5, 8, 40), md(10, 5, 9), md(10, 5, 9, 30), answered=False, correct=False)],
            False,
        ),
        (
            "a live answer today",
            _P,
            [row(mode="live", created_at=md(10, 5, 9), submitted_at=md(10, 5, 9))],
            True,
        ),
        (
            "a daily timeout never passes again_today, whatever happened today",
            row(
                id=5,
                mode="daily",
                day=DAY,
                created_at=md(10, 4, 23, 50),
                submitted_at=md(10, 5, 3),
                answered=False,
                late=True,
                correct=False,
            ),
            [practice(md(10, 5, 1))],
            False,
        ),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_is_again_today_mirrors_answered_today(
    case: str, p: rules.Row, others: list[rules.Row], expected: bool
) -> None:
    assert rules.is_again_today(p, [p, *others], DRAWN) is expected, case
    assert rules.is_again_today(p, [*others], DRAWN) is expected, f"{case} (history without the play itself)"


def test_a_mock_timeout_computes_again_today_where_a_daily_timeout_does_not() -> None:
    first = practice(md(10, 5, 1))
    mock_timeout = row(
        id=6,
        mode="mock",
        run_started_at=md(10, 4, 23, 50),
        created_at=md(10, 4, 23, 50),
        submitted_at=md(10, 5, 3),
        answered=False,
        late=True,
        correct=False,
    )
    assert rules.is_again_today(mock_timeout, [mock_timeout, first], DRAWN) is True
    hidden = earlier_mock(md(10, 5, 8), md(10, 5, 9), md(10, 5, 9, 30), answered=False, correct=False)
    assert rules.is_again_today(_M, [_M, hidden], DRAWN) is True  # no hidden filter for the run


def test_pre_seen_is_any_earlier_graded_row_of_any_season() -> None:
    assert rules.pre_seen(_P, [_P]) is False
    assert rules.pre_seen(_P, [_P, practice(md(10, 3, 12))]) is True
    assert rules.pre_seen(_P, [_P, practice(md(2, 3, 12, year=2025))]) is True  # unlike a repeat, any season
    assert rules.pre_seen(_P, [_P, practice(md(10, 6, 12))]) is False  # later
    assert rules.pre_seen(_P, [_P, practice(md(10, 3, 12), correct=None)]) is False
    assert rules.pre_seen(_P, [_P, practice(md(10, 3, 12), question_id=9)]) is False
    # a mock question that ran out unseen, since the day started, never showed its answer
    gone = earlier_mock(md(10, 5, 11), md(10, 5, 11, 1), md(10, 5, 11, 40), answered=False, correct=False)
    late_daily = daily_play(created_at=md(10, 5, 11, 30), submitted_at=md(10, 5, 12))
    assert rules.pre_seen(late_daily, [late_daily, gone]) is False


def test_pre_seen_lp_share_is_the_share_of_positive_lp_earned_on_pre_seen_questions() -> None:
    assert rules.pre_seen_lp_share([(5.0, True), (5.0, False), (-3.0, True)]) == (0.5, 2)
    assert rules.pre_seen_lp_share([(4.0, False), (6.0, False)]) == (0.0, 0)
    assert rules.pre_seen_lp_share([(4.0, True), (6.0, True)]) == (1.0, 2)


INFO = rules.QuestionInfo(
    area="elec",
    answer_kind="choice-one",
    difficulty=3,
    options=4,
    right_options=1,
    text_len=120,
    graded=True,
    has_images=False,
)


def test_to_play_carries_the_flags_and_forgets_the_hint_of_a_timeout() -> None:
    hinted = daily_play(hint_used=True, lp=6.13)
    got = rules.to_play(hinted, [hinted, practice(md(10, 3, 12))], DRAWN, INFO)
    assert (got.mode, got.ranked, got.area, got.answer_kind, got.difficulty) == (
        "daily",
        True,
        "elec",
        "choice-one",
        3,
    )
    assert (got.options, got.right_options, got.correct, got.lp) == (4, 1, True, 6.13)
    assert (got.hint, got.repeat, got.again_today, got.late, got.passed) == (True, True, False, False, False)

    timeout = row(
        id=8,
        mode="daily",
        day=DAY,
        created_at=md(10, 4, 23, 50),
        submitted_at=md(10, 5, 3),
        answered=False,
        correct=False,
        late=True,
        hint_used=True,
    )
    lost = rules.to_play(timeout, [timeout, practice(md(10, 5, 1))], DRAWN, INFO)
    assert (lost.hint, lost.late, lost.again_today) == (False, True, False)  # grant got neither

    uncounted = mock_play(counted=False, passed=True, correct=False)
    run = rules.to_play(uncounted, [uncounted], DRAWN, INFO)
    assert (run.mode, run.ranked, run.passed) == ("mock", False, True)


# --- baselines and cohort statistics -----------------------------------------------------------------------------


def test_difficulty_baseline_is_the_raw_first_answer_rate() -> None:
    rates = rules.difficulty_baseline([(2, True), (2, True), (2, False), (4, False), (4, False)])
    assert rates[2] == pytest.approx(2 / 3) and rates[4] == 0.0


def test_peer_rate() -> None:
    assert rules.peer_rate(8, 10, True, 0.5, 5) == pytest.approx((8 - 1 + 2.5) / (9 + 5))
    assert rules.peer_rate(8, 10, False, 0.5, 5) == pytest.approx((8 + 2.5) / (9 + 5))
    assert rules.peer_rate(1, 1, True, 0.4, 5) == pytest.approx(0.4)  # alone on the question: the baseline
    assert rules.peer_rate(0, 1, False, 0.4, 5) == pytest.approx(0.4)


def test_ability_shift_is_how_much_better_than_the_peers() -> None:
    assert rules.ability_shift([])[0] == 0.0
    level, _ = rules.ability_shift([(True, 0.5), (False, 0.5)] * 10)
    assert level == pytest.approx(0.0, abs=1e-9)
    strong, var = rules.ability_shift([(True, 0.5)] * 9 + [(False, 0.5)] * 3)
    assert 0.8 < strong < math.log(3) and 0 < var < 1  # shrunk a little towards 0
    perfect, _ = rules.ability_shift([(True, 0.8)] * 20)
    assert 1.5 < perfect < 4  # finite: the prior keeps a perfect record from running away


@pytest.mark.parametrize(
    ("base", "test", "flagged"),
    [
        # strong everywhere, hard items included: a strong player, not an anomaly
        ([(True, 0.8)] * 20, [(True, 0.45)] * 20, False),
        ([(True, 0.75)] * 18 + [(False, 0.75)] * 2, [(True, 0.45)] * 15 + [(False, 0.45)] * 5, False),
        # weak on the easy items and right on every hard one: the look-it-up signature
        ([(True, 0.75)] * 10 + [(False, 0.75)] * 10, [(True, 0.45)] * 20, True),
        ([(True, 0.75)] * 10 + [(False, 0.75)] * 10, [(True, 0.45)] * 16 + [(False, 0.45)] * 4, True),
        # as their record predicts
        ([(True, 0.75)] * 10 + [(False, 0.75)] * 10, [(True, 0.45)] * 5 + [(False, 0.45)] * 15, False),
    ],
)
def test_anomaly_is_within_person(
    base: list[tuple[bool, float]], test: list[tuple[bool, float]], flagged: bool
) -> None:
    a = rules.anomaly(base, test)
    assert (a.n, a.base_n, a.right) == (len(test), len(base), sum(y for y, _ in test))
    z = a.z()
    assert z is not None and (z >= 2.5) is flagged, z
    assert rules.anomaly(base, []).z() is None


def test_a_cohort_of_honest_players_of_unequal_ability_raises_about_chance_alone() -> None:
    """The finding the within-person test answers: 60 honest players with abilities 1 logit apart, each against
    the leave-one-out peer rate. A residual against the peers flagged several of them; this flags no more than the
    one-sided tail predicts."""
    flags = 0
    for seed in range(5):
        rng = random.Random(seed)
        theta = [rng.gauss(0.5, 1.0) for _ in range(60)]
        b = [rng.gauss(1.0 if q % 2 else -1.0, 0.6) for q in range(120)]
        plays = {u: rng.sample(range(120), 80) for u in range(60)}
        y = {(u, q): rng.random() < 1 / (1 + math.exp(b[q] - theta[u])) for u in plays for q in plays[u]}
        right, n = [0] * 120, [0] * 120
        for (_, q), v in y.items():
            right[q] += v
            n[q] += 1
        for u, qs in plays.items():
            rated = [(q % 2 == 1, (y[u, q], rules.peer_rate(right[q], n[q], y[u, q], 0.5, 5))) for q in qs]
            z = rules.anomaly([x for h, x in rated if not h], [x for h, x in rated if h]).z()
            flags += z is not None and z >= 2.5
    assert flags <= math.ceil(5 * rules.expected_false_flags(60, 2.5))


def test_permutation_is_seeded_and_sane() -> None:
    same = [0.1, 0.3, -0.2, 0.0, 0.2, -0.1, 0.05, 0.15]
    a = rules.permutation_p(same, same, rounds=2000, seed=3)
    assert a is not None and a == rules.permutation_p(same, same, rounds=2000, seed=3) and a > 0.3
    clear = rules.permutation_p([0.4] * 8, [-0.1] * 8, rounds=2000, seed=3)
    assert clear is not None and 0 < clear < 0.05
    assert rules.permutation_p([0.4, 0.5, 0.45], [], rounds=100, seed=1) is None
    assert rules.permutation_p([], [0.4], rounds=100, seed=1) is None
    wrong_way = rules.permutation_p([-0.1] * 8, [0.4] * 8, rounds=2000, seed=3)
    assert wrong_way is not None and wrong_way > 0.95  # one-sided: a >= b only


def test_gradient_is_hard_over_easy_and_needs_both_sides() -> None:
    by_difficulty = {1: (18, 20), 2: (17, 20), 4: (9, 20), 5: (8, 20)}
    assert rules.gradient(by_difficulty, 10) == pytest.approx(0.486, abs=1e-3)
    assert rules.gradient({4: (9, 20), 5: (8, 20)}, 10) is None  # no easy side
    assert rules.gradient({1: (18, 20), 2: (17, 20)}, 10) is None  # no hard side
    assert rules.gradient(by_difficulty, 41) is None  # each side holds 40


def test_top_composition_counts_the_top_k_by_group() -> None:
    group = {i: "A" if i <= 4 else "B" if i <= 8 else "C" for i in range(1, 13)}
    assert rules.top_composition(list(range(1, 13)), group, 6) == {"A": 4, "B": 2}
    assert rules.top_composition([12, 11, 10, 1], group, 3) == {"C": 3}


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ({"E": [1, 2, 3], "M": [4, 5, 6]}, {"E": [1, 2, 3], "M": [4, 5, 6]}),
        # two small ones make an 'other' of three
        ({"E": [1, 2, 3], "B": [4, 5], "C": [6]}, {"E": [1, 2, 3], "other": [4, 5, 6]}),
        # one person alone joins the largest group: no column of one, nothing left out
        ({"E": [1, 2, 3, 4], "M": [5, 6, 7], "B": [8]}, {"E + other": [1, 2, 3, 4, 8], "M": [5, 6, 7]}),
        ({"B": [1], "C": [2]}, {}),
        ({"B": [1], "C": [2], "D": [3]}, {"other": [1, 2, 3]}),
    ],
)
def test_merge_groups_keeps_every_group_at_min_group(
    groups: dict[str, list[int]], expected: dict[str, list[int]]
) -> None:
    merged = rules.merge_groups(groups, 3)
    assert {g: sorted(m) for g, m in merged.items()} == expected
    if merged:
        assert sorted(u for m in merged.values() for u in m) == sorted(u for m in groups.values() for u in m)


def test_a_lone_vertical_never_has_a_composition_column_to_subtract() -> None:
    """With a `<3` cell of its own, 10 minus the other cells gave a lone player's place in the top 10."""
    merged = rules.merge_groups({"E": [1, 2, 3, 4, 5], "M": [6, 7, 8, 9], "Board": [10]}, 3)
    group = {u: g for g, m in merged.items() for u in m}
    composition = rules.top_composition(list(range(1, 11)), group, 10)
    assert "Board" not in composition and composition == {"E + other": 6, "M": 4}


def test_two_tables_over_the_same_people_must_not_single_anyone_out() -> None:
    # 4 Electronics + 3 Mechanical by vertical, 6 members + 1 technical director by position: merged, the director
    # joins the members and nothing is recoverable
    vertical = rules.merge_groups({"Electronics": [1, 2, 3, 4], "Mechanical": [5, 6, 7]}, 3)
    position = rules.merge_groups({"member": [1, 2, 3, 5, 6, 7], "technical_director": [4]}, 3)
    assert "technical_director" not in position
    assert not rules.discloses([vertical, position], 3)
    # three directors who are all in a vertical of four: the vertical minus the directors is one member
    nested = {"technical_director": [1, 2, 3], "member": [4, 5, 6, 7]}
    assert rules.discloses([vertical, nested], 3)
    assert not rules.discloses([vertical], 3) and not rules.discloses([nested], 3)
    # a small vertical inside a fully printed position table is pooled first, so the sums match and hide it
    small = rules.merge_groups({"Electronics": [1, 2, 3, 4], "Mechanical": [5, 6, 7], "Board": [8]}, 3)
    positions = {"member": [1, 2, 3, 4, 5, 6, 7, 8]}
    assert not rules.discloses([small, positions], 3)
    # without pooling, the position total minus the printed verticals is the one Board member
    assert rules.discloses([{"Electronics": [1, 2, 3, 4], "Mechanical": [5, 6, 7]}, positions], 3)


# --- follow-the-leader ----------------------------------------------------------------------------------------


def canon(pos: int) -> str:
    return f"o:{pos}"


def answer(
    user: int, i: int, when: datetime, pos: int, *, key: int = 1, passed: bool = False, took: int = 60
) -> rules.DailyAnswer:
    return rules.DailyAnswer(
        user=user,
        question_id=i + 1,
        started_at=when - timedelta(seconds=took),
        submitted_at=when,
        answer="pass" if passed else canon(pos),
        right=pos == key and not passed,
        passed=passed,
    )


BASE = datetime(2026, 9, 1, tzinfo=MADRID)


def day_at(i: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return BASE + timedelta(days=i, hours=hour, minutes=minute, seconds=second)


def others_at_8pm(n_questions: int, first_user: int = 11) -> list[rules.DailyAnswer]:
    """Ten honest players an hour apart from 13:00, far from everyone: each right 60 % of the time, wrong with
    'o:2', 'o:3' or 'o:4' otherwise (seeded)."""
    rng = random.Random(n_questions)
    return [
        answer(first_user + k, i, day_at(i, 13 + k), 1 if rng.random() < 0.6 else rng.choice([2, 3, 4]))
        for i in range(n_questions)
        for k in range(10)
    ]


def follow_of(answers: list[rules.DailyAnswer], **over: Any) -> rules.Follow:
    t = thresholds(**over)
    copies, relays = rules.follow_pairs(answers, t.follow_within, t.follow_min, t.shrink_m)
    return rules.follow_flags(copies, relays, t)


def copies_by_ids(f: rules.Follow) -> dict[tuple[int, int], rules.CopyPair]:
    return {(c.a, c.b): c for c in f.copies}


def relays_by_ids(f: rules.Follow) -> dict[tuple[int, int], rules.Relay]:
    return {(r.leader, r.follower): r for r in f.relays}


A_WRONG = {i for i in range(60) if i % 5 in (0, 1)}


def a_pos(i: int) -> int:
    return (2 if i % 2 == 0 else 3) if i in A_WRONG else 1


def toy_series() -> list[rules.DailyAnswer]:
    """A (1) answers at 10:00 and is wrong on 12 of 30; B (2) copies A five minutes later, wrong answers and all;
    C (3) answers alone at 09:00; D (4) is a strong honest player 10 minutes after A on 20 days and at 08:00 on
    the other 10."""
    c_wrong = {0, 5, 10, 15, 20}
    d_wrong = {2, 7, 22}
    out: list[rules.DailyAnswer] = []
    for i in range(30):
        out.append(answer(1, i, day_at(i, 10), a_pos(i)))
        out.append(answer(2, i, day_at(i, 10, 5), a_pos(i)))
        out.append(answer(3, i, day_at(i, 9), 4 if i in c_wrong else 1))
        out.append(answer(4, i, day_at(i, 10, 10) if i < 20 else day_at(i, 8), 4 if i in d_wrong else 1))
    return [*out, *others_at_8pm(30)]


def test_a_copy_pair_on_a_toy_series() -> None:
    f = follow_of(toy_series(), follow_within=timedelta(hours=3))
    copy = copies_by_ids(f)[(1, 2)]
    assert (copy.items, copy.both_wrong, copy.shared_wrong) == (30, 12, 12)
    assert (copy.a_submitted_first, copy.a_started_first) == (30, 30)
    assert copy.median_dt_s == pytest.approx(300.0)
    assert 0 < copy.expected < 12 and copy.p < 1e-3
    assert cast(float, copy.z()) > 3.5
    assert f.copy_flagged == [copy]
    # a copy flag names the pair: both of them, the copied one too
    assert f.flagged == {1, 2}
    assert not [r for r in f.relay_flagged]
    honest = copies_by_ids(f).get((1, 4))
    assert honest is None or honest.shared_wrong <= 1


def test_the_copier_who_submits_first_still_flags_the_pair() -> None:
    """Submit order is not who copied: a reader of someone's screen can press submit a minute before them."""
    out: list[rules.DailyAnswer] = []
    for i in range(30):
        out.append(answer(1, i, day_at(i, 10), a_pos(i)))
        out.append(answer(3, i, day_at(i, 9, 59), a_pos(i), took=30))  # the copier, a minute ahead
    f = follow_of([*out, *others_at_8pm(30)])
    (pair,) = f.copy_flagged
    assert (pair.a, pair.b) == (1, 3) and pair.a_submitted_first == 0
    assert f.flagged == {1, 3}


def relay_series(delay: timedelta, own: Any) -> list[rules.DailyAnswer]:
    """A (1) answers at 10:00, wrong on 24 of 60. E (5) always answers after A, `delay` later: right where A was
    wrong (A saw the key on submitting and passed it on), on its own otherwise (`own(i)` says whether right)."""
    out: list[rules.DailyAnswer] = []
    for i in range(60):
        out.append(answer(1, i, day_at(i, 10), a_pos(i)))
        right = i in A_WRONG or own(i)
        out.append(answer(5, i, day_at(i, 10) + delay, 1 if right else 4))
    return [*out, *others_at_8pm(60)]


@pytest.mark.parametrize("delay", [timedelta(minutes=9), timedelta(hours=2)])
def test_a_relay_needs_no_window_and_no_plays_away_from_the_leader(delay: timedelta) -> None:
    f = follow_of(relay_series(delay, lambda i: i % 2 == 0))
    relay = relays_by_ids(f)[(1, 5)]
    assert relay.after == 60 and relay.test.n == 24 and relay.test.right == 24
    assert relay.test.base_n == 36  # E's other answers, every one of them after A
    assert cast(float, relay.test.z()) >= 2.5
    assert f.relay_flagged == [relay] and f.flagged == {5}
    assert not copies_by_ids(f).get((1, 5)) or not f.copy_flagged


def test_a_relayer_right_on_everything_looks_like_a_strong_player() -> None:
    """The limit: right on all 30, with nothing of their own to compare with, is what a strong player does."""
    f = follow_of(relay_series(timedelta(minutes=9), lambda i: True))
    assert relays_by_ids(f)[(1, 5)] not in f.relay_flagged


def test_a_strong_honest_player_after_the_leader_is_not_a_relay() -> None:
    f = follow_of(toy_series(), follow_within=timedelta(hours=3))
    d = relays_by_ids(f)[(1, 4)]
    assert d.test.n == 8 and d.test.right == 8  # right where A was wrong: D is strong
    assert d not in f.relay_flagged
    assert 4 not in f.flagged


def test_copy_needs_the_window_and_leaves_out_passes() -> None:
    """|dt| = within is inside, one second more is not; a pass is not a wrong answer."""
    within = timedelta(minutes=30)
    answers: list[rules.DailyAnswer] = []
    for i in range(10):
        answers.append(answer(1, i, day_at(i, 10), 2))
        delay = [0, 0, 1800, 1800, 1800, 1800, 1801, 1801, 1801, 1801][i]
        answers.append(answer(2, i, day_at(i, 10, 0, delay), 3))
    answers += others_at_8pm(10)
    copies, relays = rules.follow_pairs(answers, within, 4, 5.0)
    (x,) = [c for c in copies if (c.a, c.b) == (1, 2)]
    assert x.items == 6 and x.both_wrong == 6 and x.shared_wrong == 0
    assert x.median_dt_s == pytest.approx(1800.0)
    (r,) = [r for r in relays if (r.leader, r.follower) == (1, 2)]
    assert r.after == 8  # a relay has no window; at the same second nobody is first

    passing = [answer(1, i, day_at(i, 10), 2, passed=True) for i in range(6)]
    passing += [answer(1, i + 6, day_at(i + 6, 10), 2) for i in range(6)]
    passing += [answer(2, i, day_at(i, 10, 5), 3) for i in range(12)]
    passing += others_at_8pm(12)
    copies, relays = rules.follow_pairs(passing, within, 5, 5.0)
    (mixed,) = [c for c in copies if (c.a, c.b) == (1, 2)]
    assert mixed.items == 12 and mixed.both_wrong == 6  # the six passes are not wrong answers
    (relay,) = [r for r in relays if (r.leader, r.follower) == (1, 2)]
    assert relay.test.n == 6


def test_follow_survives_having_nobody_else_to_compare_with() -> None:
    answers = [answer(1, i, day_at(i, 10), 2) for i in range(8)] + [
        answer(2, i, day_at(i, 10, 5), 2) for i in range(8)
    ]
    f = follow_of(answers)
    assert isinstance(f.flagged, set) and f.tested <= {1, 2}


def null_cohort(seed: int, people: int = 60, days: int = 40) -> list[rules.DailyAnswer]:
    """Honest players only: each at a habitual hour around lunch, of their own ability, three shared questions a
    day, wrong answers drawn from a spread of the question's own (the leader's included)."""
    rng = random.Random(seed)
    habit = [rng.gauss(14 * 60, 150) for _ in range(people)]
    skill = [rng.uniform(0.45, 0.9) for _ in range(people)]
    out = []
    for q in range(days * 3):
        day, area = divmod(q, 3)
        harder = rng.uniform(-0.25, 0.15)
        w = [rng.random() for _ in range(3)]
        for u in range(people):
            if rng.random() > 0.8:
                continue
            start = BASE + timedelta(days=day, minutes=habit[u] + rng.gauss(0, 40) + 3 * area)
            right = rng.random() < min(0.98, max(0.05, skill[u] + harder))
            pos = 1 if right else rng.choices([2, 3, 4], w)[0]
            out.append(
                rules.DailyAnswer(
                    u, q, start, start + timedelta(seconds=rng.uniform(20, 120)), canon(pos), right, False
                )
            )
    return out


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_a_cohort_of_honest_players_flags_no_one(seed: int) -> None:
    """The review's null world: 60 honest players over 40 days. Hundreds of copy pairs and some two thousand
    relay pairs are tested; Holm keeps the chance of any false pair at the configured level per test."""
    t = thresholds()
    f = follow_of(null_cohort(seed))
    assert len(f.copies) > 50 and len(f.relays) > 1000
    assert f.expected_false(t) == pytest.approx(2 * rules.tail(t.follow_z) + rules.tail(t.follow_relay_z))
    assert len(f.flagged) <= math.floor(f.expected_false(t))  # that is, nobody
    # and a planted copier and relayer among them still come out
    honest = null_cohort(seed)
    lead = [a for a in honest if a.user == 0]
    planted = []
    for a in lead:
        later = a.submitted_at + timedelta(minutes=9)
        planted.append(replace(a, user=900, started_at=later - timedelta(minutes=1), submitted_at=later))
        right = a.wrong or a.question_id % 2 == 0
        planted.append(
            rules.DailyAnswer(
                901, a.question_id, later, later + timedelta(hours=2), canon(1 if right else 4), right, False
            )
        )
    found = follow_of(honest + planted)
    assert {0, 900, 901} <= found.flagged and len(found.flagged) == 3


@pytest.mark.parametrize(
    ("given", "kind", "expected"),
    [
        ({"options": [4, 1], "value": None, "unsure": False}, "choice-many", "o:1,4"),
        ({"options": [4], "value": None, "unsure": False}, "choice-one", "o:4"),
        ({"options": None, "value": " 12,5 ", "unsure": False}, "number", "n:12.5"),
        ({"options": None, "value": "12.50", "unsure": False}, "number", "n:12.5"),
        ({"options": None, "value": "12,5; 3", "unsure": False}, "numbers", "n:12.5|3"),
        ({"options": [1], "value": None, "unsure": True}, "choice-one", "pass"),
        ({"options": None, "value": "Hello  World", "unsure": False}, "text", "v:helloworld"),
        ({"options": None, "value": "no number here", "unsure": False}, "number", "v:nonumberhere"),
        ({}, "choice-one", None),
    ],
)
def test_canonical_answer(given: dict[str, Any], kind: str, expected: str | None) -> None:
    assert rules.canonical_answer(given, kind) == expected


# --- latency ------------------------------------------------------------------------------------------------


def test_latency_profile() -> None:
    t = thresholds()
    constant = rules.latency_profile([(30.0, length) for length in range(100, 501, 50)], t)
    assert constant.n == 9 and constant.sd_log == pytest.approx(0.0, abs=1e-12)
    assert constant.corr_length is None  # one side is constant
    assert constant.median_s == pytest.approx(30.0)
    assert constant.below_floor == 1  # only the 500-character text asks for more than 30 s (500 / 15)

    proportional = rules.latency_profile([(length / 10, length) for length in range(150, 501, 50)], t)
    assert proportional.corr_length == pytest.approx(1.0)
    assert proportional.below_floor == 0
    assert proportional.median_s == pytest.approx(32.5)

    floors = rules.latency_profile([(5.0, 100), (11.9, 100), (12.0, 100), (19.9, 300), (20.0, 300)], t)
    assert floors.below_floor == 3  # strictly below max(12, length / 15)

    clamped = rules.latency_profile([(0.1, 100), (0.5, 100), (0.0, 100)], t)
    assert clamped.sd_log == pytest.approx(0.0, abs=1e-12)  # ln clamps at 0.5 s
    spread = rules.latency_profile([(1.0, 100), (math.e, 100)], t)
    assert spread.sd_log == pytest.approx(0.5)  # population sd of ln

    assert rules.latency_profile([(30.0, 100)], t).sd_log is None


def lat(**kw: Any) -> rules.Latency:
    base: dict[str, Any] = {"n": 20, "sd_log": 0.9, "corr_length": 0.6, "below_floor": 2, "median_s": 40.0}
    return rules.Latency(**{**base, **kw})


@pytest.mark.parametrize(
    ("latency", "expected"),
    [
        (lat(n=9, below_floor=9), None),  # under min_n: not judged
        (lat(below_floor=12), True),  # 60 % below the floor
        (lat(below_floor=2), False),
        (lat(below_floor=0, sd_log=0.05, corr_length=0.02), True),  # narrow and blind to length
        (lat(below_floor=0, sd_log=0.15, corr_length=0.1), True),  # "at or below"
        (lat(below_floor=0, sd_log=0.05, corr_length=-0.08), True),  # the sign does not matter
        (lat(below_floor=0, sd_log=0.05, corr_length=0.9), False),  # narrow but it tracks length: reading
        (lat(below_floor=0, sd_log=0.9, corr_length=0.02), False),  # blind to length but wide
    ],
)
def test_timing_positive(latency: rules.Latency, expected: bool | None) -> None:
    assert rules.timing_positive(latency, thresholds()) is expected


# --- the person, the families and the two-family rule ---------------------------------------------------------


def person(**kw: Any) -> rules.Person:
    base: dict[str, Any] = {
        "key": 1,
        "n": 40,
        "right": 28,
        "timeouts": 0,
        "late": 0,
        "n_first": 40,
        "n_preseen": 0,
        "pre_seen_lp_share": 0.0,
        "hard_z": 0.3,
        "hard_n": 20,
        "hard_base_n": 20,
        "gradient": 0.8,
        "away_z": None,
        "away_n": 0,
        "home_n": 0,
        "latency": lat(),
        "following": False,
        "upstream_matches": 0,
        "upstream_expected": 0.4,
        "upstream_p": 1.0,
        "upstream_n": 8,
        "upstream_typed": 0,
    }
    return rules.Person(**{**base, **kw})


def test_families_and_the_two_family_rule() -> None:
    t = thresholds()
    both = person(hard_z=3.0, latency=lat(below_floor=12))
    flags = rules.families(both, t, False)
    assert set(flags) == set(rules.FAMILIES)
    assert flags["performance"] is True and flags["timing"] is True
    assert flags["supervised"] is None
    assert rules.conversation(flags) is True
    assert rules.independent(flags) is False  # performance and timing share a cause

    follower = rules.families(person(), t, True)
    assert follower["provenance"] is True and follower["performance"] is False and follower["timing"] is False
    assert rules.conversation(follower) is False
    assert rules.independent(follower) is True

    quiet = rules.families(person(), t, False)
    assert not any(v is True for v in quiet.values())
    assert rules.conversation(quiet) is False and rules.independent(quiet) is False


def test_the_hard_test_needs_enough_easier_plays_to_compare_with() -> None:
    assert rules.families(person(hard_z=4.0, hard_base_n=9), thresholds(), False)["performance"] is None
    assert rules.families(person(hard_z=4.0, hard_base_n=10), thresholds(), False)["performance"] is True


def test_insufficient_is_not_false() -> None:
    t = thresholds()
    few = person(n_first=5, hard_n=5, away_n=5, home_n=5, hard_z=9.0, latency=lat(n=5, below_floor=5))
    flags = rules.families(few, t, False)
    assert flags["performance"] is None and flags["timing"] is None
    assert rules.conversation(flags) is False
    assert (
        rules.conversation({"performance": None, "timing": True, "provenance": None, "supervised": None})
        is False
    )


@pytest.mark.parametrize(("hard_z", "expected"), [(2.5, True), (2.49, False), (3.0, True), (-1.0, False)])
def test_the_hard_residual_threshold_is_at_or_above(hard_z: float, expected: bool) -> None:
    assert rules.families(person(hard_z=hard_z), thresholds(), False)["performance"] is expected


def test_home_away_counts_for_performance_when_hard_items_do_not() -> None:
    away = person(hard_z=None, hard_n=0, away_z=2.0, away_n=15, home_n=15)
    assert rules.families(away, thresholds(), False)["performance"] is True


def test_provenance_from_upstream_keys_needs_enough_items() -> None:
    t = thresholds()
    ps = [0.06] * 8
    follows_upstream = person(upstream_matches=8, upstream_p=rules.poisson_binomial_sf(ps, 8), upstream_n=8)
    z = follows_upstream.upstream_z()
    assert z is not None and z == pytest.approx(rules.z_of(0.06**8))
    assert rules.families(follows_upstream, t, False)["provenance"] is True
    thin = person(upstream_matches=4, upstream_p=rules.poisson_binomial_sf(ps[:4], 4), upstream_n=4)
    assert rules.families(thin, t, False)["provenance"] is not True
    assert person(upstream_n=0).upstream_z() is None
    control = person(upstream_matches=1, upstream_p=rules.poisson_binomial_sf(ps, 1), upstream_n=8)
    assert rules.families(control, t, False)["provenance"] is not True


def test_expected_false_flags() -> None:
    assert rules.expected_false_flags(70, 1.96) == pytest.approx(1.75, abs=0.01)
    assert rules.expected_false_flags(0, 1.96) == 0.0


def test_canary_evidence_is_a_stub() -> None:
    with pytest.raises(NotImplementedError, match="feat/35"):
        rules.canary_evidence()
    with pytest.raises(NotImplementedError):
        rules.canary_evidence(1, [2], key="value")


# --- what the modules may touch ------------------------------------------------------------------------------

IDENTITY = {"email", "display_name", "password_hash", "position_lifts", "details"}
WRITES = {"commit", "flush", "merge", "with_for_update"}
DML = {"text", "insert", "update", "delete", "DDL"}


def tree_of(relative: str) -> ast.Module:
    return ast.parse((SRC / relative).read_text())


def attributes(tree: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}


def imported(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            names |= {a.name for a in n.names}
            names.add(n.module or "")
        elif isinstance(n, ast.Import):
            names |= {a.name for a in n.names}
    return names


def read_attributes(tree: ast.AST) -> set[str]:
    """Attributes the module reads, except a JSON key test (`AuditLog.details.has_key(...)`): that returns a
    boolean, never the audit details themselves."""
    tested = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "has_key"}
    return {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and id(n) not in tested}


@pytest.mark.parametrize("module", ["domain/integrity.py", "services/integrity.py"])
def test_integrity_modules_never_touch_identity_or_expected(module: str) -> None:
    tree = tree_of(module)
    assert not read_attributes(tree) & IDENTITY, f"{module} reads {read_attributes(tree) & IDENTITY}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "expected" and isinstance(node.value, ast.Name):
            assert node.value.id not in {"rank", "rank_rules", "rank_module"}, (
                "rank.expected is rank-conditioned"
            )
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == "rank":
            assert "expected" not in {a.name for a in node.names}
    assert not imported(tree) & {"session_factory", "get_engine"}, "the report builds its own engine"


def test_the_service_only_reads() -> None:
    tree = tree_of("services/integrity.py")
    assert not attributes(tree) & WRITES, f"writes or locks: {attributes(tree) & WRITES}"
    assert not imported(tree) & DML, "raw SQL text, DML or DDL"
    assert not imported(tree) & {"xp", "hints"}, "no player locks, no hint salt"
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in {"lock", "salt"}
            and isinstance(node.value, ast.Name)
        ):
            assert node.value.id not in {"xp", "hints"}


def test_only_the_reveal_module_selects_a_name() -> None:
    tree = tree_of("services/integrity_reveal.py")
    assert "display_name" in attributes(tree)
    assert not attributes(tree) & (IDENTITY - {"display_name"})
    assert not attributes(tree) & WRITES
    for other in ("services/integrity.py", "domain/integrity.py"):
        assert "display_name" not in attributes(tree_of(other))


def test_the_cli_command_builds_its_own_engine_and_disposes_it() -> None:
    tree = tree_of("cli.py")
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_integrity" in functions, "cli.py has no _integrity command"
    command = functions["_integrity"]
    seen = (
        {n.id for n in ast.walk(command) if isinstance(n, ast.Name)} | attributes(command) | imported(command)
    )
    assert "read_only_engine" in seen
    assert not seen & {"session_factory", "get_engine", "get_settings"}
    disposed = [
        n
        for t in ast.walk(command)
        if isinstance(t, ast.Try)
        for n in ast.walk(ast.Module(body=t.finalbody, type_ignores=[]))
        if isinstance(n, ast.Attribute) and n.attr == "dispose"
    ]
    assert disposed, "the engine is disposed in a finally"


# --- settings ----------------------------------------------------------------------------------------------------

DECISION = {
    "MIN_N": "10",
    "FOLLOW_WITHIN_MIN": "30",
    "FOLLOW_MIN": "5",
    "FOLLOW_Z": "2.5",
    "FOLLOW_RELAY_Z": "2.5",
    "READING_FLOOR_S": "12",
    "READING_CPS": "15",
    "BELOW_FLOOR_SHARE": "0.5",
    "NARROW_SD_LOG": "0.15",
    "FLAT_CORR": "0.1",
    "HARD_RESIDUAL_Z": "2.5",
    "AWAY_Z": "2.0",
    "UPSTREAM_MIN": "5",
    "UPSTREAM_Z": "2.5",
}


def clean_environment(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for name in [n for n in os.environ if n.startswith("IFS_INTEGRITY_")]:
        monkeypatch.delenv(name)
    for name, value in env.items():
        monkeypatch.setenv(f"IFS_INTEGRITY_{name}", value)


def build_settings() -> IntegritySettings:
    """Without the .env file and without mypy's view of the required fields: they come from the environment."""
    cls: Any = IntegritySettings
    return cast(IntegritySettings, cls(_env_file=None))


def test_integrity_settings_require_every_decision_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(
        monkeypatch, Z="2.5", MIN_GROUP="4", SEED="9", FIXED_RANK="500", DSN="postgresql+psycopg://x@db/q"
    )
    with pytest.raises(ValidationError) as e:
        build_settings()
    assert {str(err["loc"][0]) for err in e.value.errors()} == {n.lower() for n in DECISION}
    assert "min_n" in str(e.value)


@pytest.mark.parametrize("missing", sorted(DECISION))
def test_each_decision_threshold_is_required_on_its_own(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    clean_environment(monkeypatch, **{k: v for k, v in DECISION.items() if k != missing})
    with pytest.raises(ValidationError) as e:
        build_settings()
    assert [str(err["loc"][0]) for err in e.value.errors()] == [missing.lower()]


def test_the_neutral_knobs_have_defaults_and_the_salt_is_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(monkeypatch, **DECISION)
    s = build_settings()
    assert (s.z, s.min_group, s.permutation_rounds, s.bootstrap_rounds, s.seed, s.fixed_rank, s.shrink_m) == (
        1.96,
        3,
        5000,
        2000,
        0,
        350.0,
        5.0,
    )
    assert s.dsn is None and s.salt is None

    clean_environment(
        monkeypatch,
        **DECISION,
        SALT="correct-horse-battery-staple-0123456789",
        DSN="postgresql+psycopg://r@db/q",
    )
    s = build_settings()
    assert isinstance(s.salt, SecretStr) and s.dsn == "postgresql+psycopg://r@db/q"
    assert s.salt.get_secret_value() == "correct-horse-battery-staple-0123456789"
    assert "correct-horse" not in repr(s) and "correct-horse" not in str(s)


def test_thresholds_map_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(monkeypatch, **DECISION)
    s = build_settings()
    t = service.thresholds(s)
    assert isinstance(t, rules.Thresholds)
    assert t.follow_within == timedelta(minutes=30)
    assert (t.min_n, t.follow_min, t.upstream_min, t.fixed_rank, t.split) == (10, 5, 5, 350.0, None)
    assert (t.follow_z, t.below_floor_share, t.narrow_sd_log, t.away_z) == (2.5, 0.5, 0.15, 2.0)
    over = service.thresholds(s, fixed_rank=500.0, split=date(2026, 9, 20))
    assert (over.fixed_rank, over.split) == (500.0, date(2026, 9, 20))
    assert over.follow_within == timedelta(minutes=30)
