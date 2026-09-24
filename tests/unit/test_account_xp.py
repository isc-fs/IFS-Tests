from __future__ import annotations

import pytest

from ifs_tests.domain.xp import account_level, difficulty, streak_bonus, to_next, xp_award


@pytest.mark.parametrize(
    ("kwargs", "xp", "bonuses"),
    [
        ({"correct": True, "difficulty": 3, "mode": "daily"}, 50, {}),
        ({"correct": True, "difficulty": 3, "mode": "practice"}, 19, {}),
        ({"correct": True, "difficulty": 5, "mode": "mock"}, 90, {}),
        ({"correct": True, "difficulty": 3, "mode": "daily", "hint": True}, 25, {}),
        ({"correct": True, "difficulty": 1, "mode": "practice", "repeat": True}, 2, {}),
        ({"correct": True, "difficulty": 3, "mode": "daily", "first_win": True}, 75, {"first_win": 25}),
        ({"correct": True, "difficulty": 3, "mode": "daily", "combo": 9}, 75, {"combo": 25}),
        ({"correct": True, "difficulty": 3, "mode": "daily", "streak_days": 11}, 75, {"streak": 25}),
        ({"correct": True, "difficulty": 3, "mode": "daily", "crit": True}, 100, {"crit": 50}),
        # Bonuses add up, they don't multiply.
        (
            {
                "correct": True,
                "difficulty": 3,
                "mode": "daily",
                "first_win": True,
                "combo": 5,
                "streak_days": 11,
            },
            125,
            {"first_win": 25, "combo": 25, "streak": 25},
        ),
        ({"correct": False, "difficulty": 3, "mode": "daily"}, 15, {}),  # League pays for losses too
        ({"correct": False, "difficulty": 3, "mode": "daily", "passed": True}, 5, {}),
        ({"correct": None, "difficulty": 3, "mode": "daily"}, 5, {}),
        ({"correct": True, "difficulty": 3, "mode": "daily", "late": True}, 15, {}),
        ({"correct": False, "difficulty": 3, "mode": "daily", "answered": False}, 0, {}),  # left to run out
        ({"correct": True, "difficulty": 3, "mode": "practice", "again_today": True}, 0, {}),
    ],
)
def test_xp_award(kwargs: dict[str, object], xp: int, bonuses: dict[str, int]) -> None:
    got = xp_award(**kwargs)  # type: ignore[arg-type]
    assert (got.amount, got.bonuses) == (xp, bonuses)


def test_xp_never_goes_negative() -> None:
    for correct in (True, False, None):
        for d in range(1, 6):
            for mode in ("practice", "daily", "mock", "live"):
                assert xp_award(correct, d, mode, late=True, repeat=True, hint=True).amount >= 0


def test_account_levels_come_fast_then_steady() -> None:
    assert [to_next(n) for n in (1, 2, 10, 25, 60)] == [300, 350, 750, 1500, 1500]
    assert account_level(0) == (1, 0, 300)
    assert account_level(299) == (1, 299, 300)
    assert account_level(300) == (2, 0, 350)
    assert account_level(4_500)[0] == 10
    assert account_level(21_000)[0] == 25


@pytest.mark.parametrize(("days", "share"), [(0, 0.0), (1, 0.0), (2, 0.05), (11, 0.5), (60, 0.5)])
def test_streak_bonus(days: int, share: float) -> None:
    assert streak_bonus(days) == pytest.approx(share)


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


def test_rested_xp_banks_while_away_and_doubles_the_base_until_spent() -> None:
    from ifs_tests.domain.xp import rested_bank

    assert [rested_bank(0, d) for d in (-1, 0, 1, 2, 5)] == [0, 0, 150, 300, 450]
    assert rested_bank(400, 1) == 450
    full = xp_award(True, 3, "daily", rested=450)
    assert (full.amount, full.bonuses) == (100, {"rested": 50})
    last = xp_award(True, 3, "daily", rested=20)
    assert (last.amount, last.bonuses) == (70, {"rested": 20})
    assert xp_award(False, 3, "daily", rested=450).bonuses == {}  # only right answers spend it
