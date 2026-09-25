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


@pytest.mark.parametrize(("v", "seed"), [(0.713, 1), (82.9, 2), (-4.2, 3), (0.05, 4), (1_250_000.0, 5)])
def test_a_number_gets_a_range_that_holds_it_without_being_centred(v: float, seed: int) -> None:
    h = hint({"kind": "number", "accept": [{"v": v, "d": 3}]}, [], seed)
    assert h is not None
    lo, hi = (float(x.replace(",", "")) for x in re.findall(r"-?\d[\d,]*(?:\.\d+)?", h.text)[:2])
    assert lo < v < hi
    assert abs((v - lo) - (hi - v)) > 1e-9


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
    assert n is not None and n.text == "2 values; the first is between 453 and 637."
    t = hint({"kind": "text", "accept": ["ams"]}, [], 1)
    assert t is not None and t.text == '3 characters, starting with "a".'


@pytest.mark.parametrize("key", [None, {"kind": "self"}])
def test_nothing_to_hint_without_a_gradable_key(key: dict[str, object] | None) -> None:
    assert hint(key, [1, 2, 3], 1) is None


@pytest.mark.parametrize(
    ("key", "options"),
    [
        ({"kind": "number", "accept": [{"v": 1.0, "d": 0}]}, []),  # any number in the range would round to 1
        ({"kind": "number", "accept": [{"v": 0.0, "d": 0}]}, []),  # zero: the obvious guess in any range
        ({"kind": "number", "accept": [{"v": 0.0, "d": 2}]}, []),
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


def _ends(text: str) -> tuple[float, float]:
    lo, hi = (float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)[-2:])
    return lo, hi


def _right(n: dict[str, float], x: float) -> bool:
    return bool(grade({"kind": "number", "accept": [n]}, value=f"{x:.10g}"))


# DOM-01 / BANK-12: neither end nor the middle of a hint's range is right, whatever the seed.
@pytest.mark.parametrize(
    "n",
    [{"v": float(v), "d": 0} for v in (4, 5, 6, 9, 17, 58, 425, 3404, 64107, -10368)]
    + [
        {"v": v, "d": d}
        for v, d in ((0.1, 1), (0.23, 2), (0.713, 3), (3.5, 1), (82.9, 1), (509.85, 2), (-4.2, 1))
    ],
)
def test_a_number_hint_is_right_neither_at_its_ends_nor_in_its_middle(n: dict[str, float]) -> None:
    for seed in range(300):
        h = hint({"kind": "number", "accept": [n]}, [], seed)
        assert h is not None
        lo, hi = _ends(h.text)
        assert lo < n["v"] < hi
        assert not any(_right(n, x) for x in (lo, hi, (lo + hi) / 2)), (seed, h.text)


@pytest.mark.parametrize(("lo", "hi"), [(70, 80), (11.7, 12.1), (3.8, 3.9), (898, 901), (-5, 5)])
def test_a_range_hint_holds_the_range_off_centre(lo: float, hi: float) -> None:
    for seed in range(300):
        h = hint({"kind": "range", "accept": [{"lo": lo, "hi": hi}]}, [], seed)
        assert h is not None
        a, b = _ends(h.text)
        assert a < lo <= hi < b and not lo <= (a + b) / 2 <= hi, (seed, h.text)


def test_a_list_hint_gives_a_range_for_its_first_value_not_the_value() -> None:
    first = {"v": 518.4, "d": 1}
    key = {"kind": "numbers", "accept": [{"values": [first, {"v": 604.8, "d": 1}], "ordered": True}]}
    for seed in range(100):
        h = hint(key, [], seed)
        assert h is not None and h.text.startswith("2 values; the first is between ")
        lo, hi = _ends(h.text)
        assert lo < 518.4 < hi and not any(_right(first, x) for x in (lo, hi, (lo + hi) / 2))
    small = {"kind": "numbers", "accept": [{"values": [{"v": 1, "d": 0}, {"v": 7, "d": 0}], "ordered": True}]}
    assert hint(small, [], 1) is None
