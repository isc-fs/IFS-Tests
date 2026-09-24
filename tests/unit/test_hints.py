from __future__ import annotations

import re

import pytest

from ifs_tests.domain.hints import hint


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
