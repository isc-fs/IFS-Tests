from __future__ import annotations

import re

import pytest

from ifs_tests.domain.grading import grade, unreadable
from ifs_tests.domain.hints import hint
from ifs_tests.domain.keys import number


def test_single_choice_keeps_two_options_one_of_them_right() -> None:
    key = {"kind": "choice", "mode": "one", "options": [12]}
    h = hint(key, [10, 11, 12, 13], seed=7)
    assert h is not None and len(h.removed_options) == 2 and 12 not in h.removed_options
    assert hint(key, [10, 11, 12, 13], seed=7) == h  # the same hint every time


@pytest.mark.parametrize("options", [[12], [11, 12]])
def test_no_hint_when_removing_options_would_give_the_answer_away(options: list[int]) -> None:
    assert hint({"kind": "choice", "mode": "one", "options": [12]}, options, seed=1) is None


def test_multiple_choice_says_how_many_are_right() -> None:
    h = hint({"kind": "choice", "mode": "all", "options": [1, 3]}, [1, 2, 3, 4, 5], seed=1)
    assert h is not None and (h.text, h.removed_options) == ("2 of the 5 options are right.", [])


@pytest.mark.parametrize(("v", "seed"), [(0.713, 1), (82.9, 2), (-4.2, 3), (0.0, 4), (1_250_000.0, 5)])
def test_a_number_gets_a_range_that_holds_it_without_being_centred(v: float, seed: int) -> None:
    h = hint({"kind": "number", "accept": [{"v": v, "d": 3}]}, [], seed)
    assert h is not None
    lo, hi = (float(x.replace(",", "")) for x in re.findall(r"-?\d[\d,]*(?:\.\d+)?", h.text)[:2])
    assert lo < v < hi
    assert abs((v - lo) - (hi - v)) > 1e-9 or v == 0


def test_ranges_lists_and_text() -> None:
    r = hint({"kind": "range", "accept": [{"lo": 11.7, "hi": 12.1}]}, [], 1)
    assert r is not None and r.text.startswith("Between ")
    n = hint(
        {
            "kind": "numbers",
            "accept": [{"values": [{"v": 518.4, "d": 1}, {"v": 604.8, "d": 1}], "ordered": True}],
        },
        [],
        1,
    )
    assert n is not None and n.text == "2 values; the first is 518."
    t = hint({"kind": "text", "accept": ["ams"]}, [], 1)
    assert t is not None and t.text == '3 characters, starting with "a".'


@pytest.mark.parametrize("key", [None, {"kind": "self"}])
def test_nothing_to_hint_without_a_gradable_key(key: dict[str, object] | None) -> None:
    assert hint(key, [1, 2, 3], 1) is None


@pytest.mark.parametrize(
    ("key", "options"),
    [
        ({"kind": "number", "accept": [{"v": 1.0, "d": 0}]}, []),  # any number in the range would round to 1
        ({"kind": "number", "accept": [{"v": 0.0, "d": 0}]}, []),
        ({"kind": "text", "accept": ["c"]}, []),  # the first letter is the answer
        ({"kind": "text", "accept": ["ab"]}, []),
        ({"kind": "choice", "mode": "one", "options": [11, 12]}, [10, 11, 12, 13]),  # both options left right
        ({"kind": "choice", "mode": "one", "options": [11, 12, 13]}, [10, 11, 12, 13]),
    ],
)
def test_no_hint_when_it_would_give_the_answer_away(key: dict[str, object], options: list[int]) -> None:
    for seed in range(20):
        assert hint(key, options, seed) is None


def test_a_small_number_still_gets_a_range_wider_than_the_grading_tolerance() -> None:
    key = {"kind": "number", "accept": [{"v": 0.1, "d": 1}]}  # right means within 0.05 of 0.1
    for seed in range(20):
        h = hint(key, [], seed)
        assert h is not None
        lo, hi = (float(x) for x in re.findall(r"-?\d[\d,]*(?:\.\d+)?", h.text)[:2])
        assert not (grade(key, value=str(lo)) and grade(key, value=str(hi)))


# UI-02: a hint's numbers are typed back as they're printed, and the field reads a comma as a decimal comma.
@pytest.mark.parametrize("v", [2778.0, 64107.0, 1_250_000.0, -10368.0, 0.000015, 0.713, 518.4])
def test_hint_numbers_read_back_as_printed(v: float) -> None:
    key = {"kind": "number", "accept": [{"v": v, "d": 0 if v.is_integer() else 6}]}
    for seed in range(50):
        h = hint(key, [], seed)
        assert h is not None and "," not in h.text and "e" not in h.text.lower().replace("between", "")
        for printed in re.findall(r"-?\d+(?:\.\d+)?", h.text):
            assert unreadable(key, printed) is None
            parsed = number(printed)
            assert parsed is not None and parsed["v"] == float(printed)
