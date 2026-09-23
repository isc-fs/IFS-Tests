from __future__ import annotations

import random

import pytest

from ifs_tests.domain.xp import (
    LEVELS,
    RANKS,
    TOP,
    at,
    award,
    difficulty,
    floor_for,
    level_for,
    streak_multiplier,
    title,
    xp_for_level,
)


def test_each_level_asks_500_xp_more_than_the_last() -> None:
    steps = [xp_for_level(n + 1) - xp_for_level(n) for n in range(TOP)]
    assert xp_for_level(0) == 0 and xp_for_level(TOP) == 60_000
    assert steps == list(range(500, 500 * (TOP + 1), 500))


@pytest.mark.parametrize("level", range(TOP + 1))
def test_level_boundaries(level: int) -> None:
    assert level_for(xp_for_level(level)) == level
    if level:
        assert level_for(xp_for_level(level) - 1) == level - 1


def test_the_top_is_the_last_level_however_much_xp() -> None:
    assert level_for(10**9) == TOP == len(LEVELS) - 1


@pytest.mark.parametrize(
    ("vertical", "top"),
    [
        ("Mechanical", "Gigante Noble"),
        ("Electronics", "Villano"),
        ("Tractive System", "Villano"),
        ("Driverless", "Villano"),
        ("Business", "Leyenda"),
        (None, "Leyenda"),
    ],
)
def test_titles_climb_mingo_jefe_dt_and_the_top_depends_on_the_vertical(
    vertical: str | None, top: str
) -> None:
    names = [title(n, vertical) for n in range(TOP + 1)]
    assert names[:TOP] == [f"{t} {d}" for t in ("Mingo", "Jefe", "DT") for d in ("I", "II", "III", "IV", "V")]
    assert names[TOP] == top


@pytest.mark.parametrize(
    ("level", "name", "formulas", "learn_more", "hint", "penalty"),
    [
        (0, "Mingo I", True, True, True, 0.0),
        (2, "Mingo III", True, True, True, 0.0),
        (3, "Mingo IV", True, True, True, 0.05),
        (4, "Mingo V", True, False, True, 0.1),
        (5, "Jefe I", False, False, True, 0.15),
        (9, "Jefe V", False, False, True, 0.35),
        (10, "DT I", False, False, False, 0.45),
        (14, "DT V", False, False, False, 0.7),
        (15, "Villano", False, False, False, 0.75),
    ],
)
def test_training_wheels_come_off_level_by_level(
    level: int, name: str, formulas: bool, learn_more: bool, hint: bool, penalty: float
) -> None:
    lv = at(level)
    assert (title(level, "Electronics"), lv.formulas, lv.learn_more, lv.hint, lv.penalty) == (
        name,
        formulas,
        learn_more,
        hint,
        penalty,
    )


def test_each_aid_once_removed_stays_removed_and_penalties_only_grow() -> None:
    for aid in ("formulas", "learn_more", "hint"):
        flags = [getattr(lv, aid) for lv in LEVELS]
        assert flags == sorted(flags, reverse=True), aid
    assert [lv.penalty for lv in LEVELS] == sorted(lv.penalty for lv in LEVELS)


def test_ranks_start_at_the_bottom_of_their_band() -> None:
    assert {r: title(level, None) for r, level in RANKS.items()} == {
        "mingo": "Mingo I",
        "member": "Mingo IV",
        "department_head": "Jefe I",
        "technical_director": "DT I",
    }
    assert floor_for("mingo") == 0 and floor_for("technical_director") == xp_for_level(10) == 27_500


@pytest.mark.parametrize(
    ("kind", "time_s", "answered", "right", "expected"),
    [
        ("choice-one", None, 0, 0, 2),
        ("choice-many", None, 0, 0, 3),
        ("number", 600, 0, 0, 4),
        ("numbers", 600, 0, 0, 5),
        ("choice-one", 45, 0, 0, 1),
        ("choice-one", None, 19, 0, 2),  # too few answers to trust the rate
        ("choice-one", None, 40, 2, 4),  # 5 % right: much harder than it looks
        ("numbers", 600, 50, 48, 2),  # 96 % right: easier than it looks
    ],
)
def test_difficulty(kind: str, time_s: int | None, answered: int, right: int, expected: int) -> None:
    assert difficulty(kind, time_s, answered, right) == expected


@pytest.mark.parametrize(("days", "multiplier"), [(0, 1.0), (1, 1.0), (2, 1.05), (11, 1.5), (60, 1.5)])
def test_streak_bonus(days: int, multiplier: float) -> None:
    assert streak_multiplier(days) == pytest.approx(multiplier)


@pytest.mark.parametrize(
    ("kwargs", "xp"),
    [
        ({"correct": True, "difficulty": 3, "mode": "daily", "level": 0}, 50),
        ({"correct": True, "difficulty": 3, "mode": "practice", "level": 0}, 12),
        ({"correct": True, "difficulty": 5, "mode": "mock", "level": 0}, 90),
        ({"correct": True, "difficulty": 3, "mode": "daily", "level": 0, "streak_days": 11}, 75),
        ({"correct": True, "difficulty": 3, "mode": "daily", "level": 0, "hint": True}, 25),
        ({"correct": True, "difficulty": 1, "mode": "practice", "level": 0, "repeat": True}, 1),
        ({"correct": False, "difficulty": 3, "mode": "daily", "level": 0}, 0),
        ({"correct": False, "difficulty": 3, "mode": "daily", "level": 3}, -2),
        ({"correct": False, "difficulty": 3, "mode": "daily", "level": 5}, -8),
        ({"correct": False, "difficulty": 3, "mode": "daily", "level": 15}, -38),
        ({"correct": False, "difficulty": 3, "mode": "daily", "level": 15, "streak_days": 11}, -38),
        ({"correct": True, "difficulty": 3, "mode": "daily", "level": 20, "late": True}, -38),
        ({"correct": True, "difficulty": 3, "mode": "daily", "level": 0, "late": True}, 0),
        ({"correct": False, "difficulty": 3, "mode": "mock", "level": 5, "late": True}, -6),
        (
            {
                "correct": True,
                "difficulty": 3,
                "mode": "practice",
                "level": 0,
                "repeat": True,
                "again_today": True,
            },
            0,
        ),
        (
            {
                "correct": False,
                "difficulty": 3,
                "mode": "practice",
                "level": 20,
                "repeat": True,
                "again_today": True,
            },
            -1,
        ),
        ({"correct": None, "difficulty": 3, "mode": "daily", "level": 20, "late": True}, 0),
        ({"correct": None, "difficulty": 3, "mode": "daily", "level": 20}, 0),
    ],
)
def test_award(kwargs: dict[str, object], xp: int) -> None:
    assert award(**kwargs) == xp  # type: ignore[arg-type]


def _days_to(start: int, active: float, practice: int, mock_every: int, skill: float) -> dict[int, int]:
    """A seeded season (September to August) of play: dailies, some practice, a mock now and then; skill
    improves slowly."""
    rng = random.Random(3)
    xp, streak = xp_for_level(start), 0
    reached: dict[int, int] = {}
    for day in range(1, 366):
        level = level_for(xp)
        played = rng.random() < active
        streak = streak + 1 if played else 0
        if played:
            plays = [("daily", 3), ("practice", practice)] + ([("mock", 10)] if day % mock_every == 0 else [])
            for mode, n in plays:
                for _ in range(n):
                    d = rng.choice([1, 2, 2, 3, 3, 3, 4, 4, 5])
                    right = rng.random() < min(0.88, skill + day * 0.0015) - 0.06 * (d - 3)
                    xp = max(xp_for_level(start), xp + award(right, d, mode, level, streak))
        for mark in (5, 10, 15):
            if level_for(xp) >= mark:
                reached.setdefault(mark, day)
    return reached


def test_pacing_matches_the_design() -> None:
    active = _days_to(0, active=0.9, practice=10, mock_every=7, skill=0.5)
    typical = _days_to(0, active=0.6, practice=3, mock_every=14, skill=0.45)
    assert 20 <= active[5] <= 50, active  # Jefe in about five weeks
    assert 90 <= active[10] <= 150, active  # DT around the January registration quizzes
    assert 200 <= active[15] <= 270, active  # the top in spring, before the summer events
    assert 90 <= typical[5] <= 150 and 15 not in typical, typical  # a steady player: Jefe by winter, no top
