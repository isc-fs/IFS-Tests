from __future__ import annotations

import random

import pytest

from ifs_tests.domain.live import (
    CODE_ALPHABET,
    SUBDEPARTMENTS,
    Player,
    captain,
    new_code,
    owner,
    seat_by_subdepartment,
    speed_points,
)


def test_codes_are_six_characters_without_look_alikes() -> None:
    codes = {new_code(random.Random(i)) for i in range(200)}
    assert all(len(c) == 6 and set(c) <= set(CODE_ALPHABET) for c in codes)
    assert not set("01OIL") & set(CODE_ALPHABET)
    assert len(codes) == 200


def test_every_subdepartment_has_a_vertical_and_known_topics() -> None:
    topics = {"dynamics", "aero", "structures", "powertrain", "hv", "electronics", "dv", "scoring"}
    for code, (name, vertical, owns) in SUBDEPARTMENTS.items():
        assert name and vertical and set(owns) <= topics, code


def test_tables_follow_each_players_first_subdepartment_never_balanced() -> None:
    players = [
        Player(1, ("AE",), 350.0),  # rank points: the best-ranked member captains
        Player(2, ("AE", "CH"), 550.0),  # the first sub-department seats them
        Player(3, ("BT",), 50.0),
        Player(4, (), 1050.0),
        Player(5, ("??",), 0.0),  # unknown codes are ignored
        Player(6, ("AE",), 550.0),  # ties go to the earlier member
        Player(7, ("BT",), 50.25),  # a fraction of an LP is enough
    ]
    tables = seat_by_subdepartment(players)
    assert [(t.name, sorted(t.member_ids), t.captain_id, t.topics) for t in tables] == [
        ("Aerodynamics", [1, 2, 6], 2, ["aero"]),
        ("Batteries", [3, 7], 7, ["hv"]),
        ("Everyone else", [4, 5], 4, []),
    ]


@pytest.mark.parametrize(
    ("topic", "expected"),
    [("aero", 10), ("hv", 11), ("dv", 99), (None, 99)],
)
def test_a_question_goes_to_the_table_owning_its_topic_or_the_catch_all(
    topic: str | None, expected: int
) -> None:
    tables = [(10, ["aero"]), (11, ["hv", "powertrain"]), (12, ["hv"])]
    assert owner(topic, tables, catch_all=99) == expected


@pytest.mark.parametrize(
    ("correct", "elapsed", "budget", "points"),
    [
        (True, 0, 60, 1000),
        (True, 30, 60, 750),
        (True, 60, 60, 500),
        (True, 90, 60, 500),
        (True, 5, None, 1000),
        (False, 0, 60, 0),
        (None, 0, 60, 0),
    ],
)
def test_speed_points(correct: bool | None, elapsed: float, budget: int | None, points: int) -> None:
    assert speed_points(correct, elapsed, budget) == points


@pytest.mark.parametrize(
    ("ranks", "expected"),
    [
        ({1: 350.0, 2: 550.0, 3: 50.0}, 2),
        ({6: 550.0, 2: 550.0}, 2),  # a tie goes to the earlier member
        ({7: 50.25, 3: 50.0}, 7),
        ({}, None),  # an empty table has nobody to captain it
    ],
)
def test_the_captain_is_the_best_ranked_member(ranks: dict[int, float], expected: int | None) -> None:
    assert captain(ranks) == expected
