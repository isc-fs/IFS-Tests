from __future__ import annotations

import random

import pytest

from ifs_tests.domain.xp import (
    RANKS,
    TIERS,
    award,
    difficulty,
    floor_for,
    level_for,
    streak_multiplier,
    tier,
    xp_for_level,
)


def test_the_curve_rises_ever_more_steeply() -> None:
    steps = [xp_for_level(n + 1) - xp_for_level(n) for n in range(40)]
    assert xp_for_level(0) == 0
    assert all(b > a for a, b in zip(steps, steps[1:], strict=False))


@pytest.mark.parametrize("level", [0, 1, 4, 8, 12, 16, 20, 30])
def test_level_boundaries(level: int) -> None:
    assert level_for(xp_for_level(level)) == level
    if level:
        assert level_for(xp_for_level(level) - 1) == level - 1


@pytest.mark.parametrize(
    ("level", "name", "formulas", "learn_more", "hint", "penalty"),
    [
        (0, "Mingo", True, True, True, 0.0),
        (3, "Mingo", True, True, True, 0.0),
        (4, "Rookie", True, True, True, 0.0),
        (8, "Engineer", True, False, True, 0.1),
        (12, "Department Head", False, False, True, 0.25),
        (16, "Senior", False, False, False, 0.5),
        (20, "Technical Director", False, False, False, 0.75),
        (40, "Technical Director", False, False, False, 0.75),
    ],
)
def test_training_wheels_come_off_level_by_level(
    level: int, name: str, formulas: bool, learn_more: bool, hint: bool, penalty: float
) -> None:
    t = tier(level)
    assert (t.name, t.formulas, t.learn_more, t.hint, t.penalty) == (
        name,
        formulas,
        learn_more,
        hint,
        penalty,
    )


def test_each_aid_once_removed_stays_removed() -> None:
    for aid in ("formulas", "learn_more", "hint"):
        flags = [getattr(t, aid) for t in TIERS]
        assert flags == sorted(flags, reverse=True), aid
    assert [t.penalty for t in TIERS] == sorted(t.penalty for t in TIERS)


def test_ranks_start_in_their_band() -> None:
    assert {r: tier(level).name for r, level in RANKS.items()} == {
        "mingo": "Mingo",
        "member": "Engineer",
        "department_head": "Department Head",
        "technical_director": "Technical Director",
    }
    assert floor_for("mingo") == 0 and floor_for("technical_director") == xp_for_level(20)


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
        ({"correct": False, "difficulty": 3, "mode": "daily", "level": 8}, -5),
        ({"correct": False, "difficulty": 3, "mode": "daily", "level": 12}, -12),
        ({"correct": False, "difficulty": 3, "mode": "daily", "level": 20}, -38),
        ({"correct": False, "difficulty": 3, "mode": "daily", "level": 20, "streak_days": 11}, -38),
        ({"correct": True, "difficulty": 3, "mode": "daily", "level": 20, "late": True}, -38),
        ({"correct": True, "difficulty": 3, "mode": "daily", "level": 0, "late": True}, 0),
        ({"correct": False, "difficulty": 3, "mode": "mock", "level": 12, "late": True}, -9),
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
    """A seeded season of play: dailies, some practice, a mock now and then; skill improves slowly."""
    rng = random.Random(3)
    xp, streak = xp_for_level(start), 0
    reached: dict[int, int] = {}
    for day in range(1, 181):
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
        for mark in (8, 12, 16, 20):
            if level_for(xp) >= mark:
                reached.setdefault(mark, day)
    return reached


def test_pacing_matches_the_design() -> None:
    active = _days_to(0, active=0.9, practice=10, mock_every=7, skill=0.5)
    typical = _days_to(0, active=0.6, practice=3, mock_every=14, skill=0.45)
    assert 20 <= active[12] <= 50, active  # Department Head band in about five weeks
    assert 90 <= active[20] <= 150, active  # Technical Director band around the January quizzes
    assert 90 <= typical[12] <= 150 and 20 not in typical, typical
