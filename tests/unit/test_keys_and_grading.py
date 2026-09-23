from __future__ import annotations

from typing import Any

import pytest

from ifs_tests.domain.grading import grade, tolerance
from ifs_tests.domain.keys import answer_kind, build_key, display, number, split_values


def ans(*texts: str, correct: bool = True) -> list[dict[str, Any]]:
    return [{"text": t, "is_correct": correct} for t in texts]


# Real answer formats found in the FS-Quiz bank (September 2026).
@pytest.mark.parametrize(
    ("qtype", "text", "kind"),
    [
        ("input", "82.9", "number"),
        ("input", "3.5\u200b", "number"),
        ("input", "+2851", "number"),
        ("input", "-0.5", "number"),
        ("input", "63.4, 110.8", "numbers"),
        ("input", "0,98; 156,9", "numbers"),
        ("input", "5.800; 14.768; 30.750", "numbers"),
        ("input", "1-2-3", "numbers"),
        ("input", "70-80", "range"),
        ("input-range", "11.7-12.1", "range"),
        ("input-range", "898-901", "range"),
        ("input", "Qxc8", "text"),
        ("input", "6/7", "text"),
        ("input", "A-B-H-J-M-N", "text"),
        ("input-range", "36.387736.7", "self"),
        ("input-range", "8,40 x No", "self"),
        ("input", "0,10 x A, 0,03 x A, 0,17 x A", "self"),
        ("input", "(G1+G5+G1G2)/(1+G3-G1G3G4-G1G2G3G4)", "self"),
        ("drag_sort", "Li, Mg, Al, Ti, Fe, Cu, Ag, Pb", "self"),
    ],
)
def test_real_key_formats(qtype: str, text: str, kind: str) -> None:
    key = build_key(qtype, ans(text))
    assert key is not None and key["kind"] == kind


def test_no_correct_answer_means_no_key() -> None:
    assert build_key("single-choice", ans("A", "B", correct=False)) is None
    assert build_key("input", []) is None
    assert answer_kind("input", None) == "self"


def test_choice_keys_use_our_option_ids() -> None:
    answers = [{"text": "A", "is_correct": False}, {"text": "B", "is_correct": True}]
    key = build_key("multi-choice", answers, option_ids=[10, 11])
    assert key == {"kind": "choice", "mode": "all", "options": [11]}
    assert display("multi-choice", answers) == "B"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("63.4, 110.8", ["63.4", "110.8"]),
        ("0,98; 156,9", ["0,98", "156,9"]),
        ("63.4,110.8", ["63.4", "110.8"]),
        ("1,3,5", ["1", "3", "5"]),
        ("1,7", ["1,7"]),
        ("0,98 156,9", ["0,98", "156,9"]),
    ],
)
def test_split_values(text: str, expected: list[str]) -> None:
    assert split_values(text) == expected


def test_a_single_bare_comma_splits_only_when_several_values_are_expected() -> None:
    assert split_values("1,7", expected=2) == ["1", "7"]


def test_tolerance_follows_the_keys_precision() -> None:
    assert tolerance({"v": 82.9, "d": 1}) == pytest.approx(0.0829)
    assert tolerance({"v": 0.23, "d": 2}) == pytest.approx(0.005)
    assert tolerance({"v": 64107, "d": 0}) == pytest.approx(64.107)


@pytest.mark.parametrize(
    ("key_text", "given", "ok"),
    [
        ("82.9", "82.9", True),
        ("82.9", "82,94", True),
        ("82.9", "82.98", True),
        ("82.9", "83.0", False),
        ("0.70", "0.7", True),
        ("60", "60.4", True),
        ("60", "61", False),
        ("3.5\u200b", "3.5", True),
        ("+2851", "2851", True),
        ("82.9", "", False),
        ("82.9", "about 83", False),
    ],
)
def test_number_answers(key_text: str, given: str, ok: bool) -> None:
    assert grade(build_key("input", ans(key_text)), value=given) is ok


@pytest.mark.parametrize(
    ("key_text", "given", "ok"),
    [
        ("63.4, 110.8", "63.4; 110.8", True),
        ("63.4, 110.8", "63.4, 110.8", True),
        ("63.4, 110.8", "110.8; 63.4", False),
        ("0,98; 156,9", "0.98; 156.9", True),
        ("2, 3, 4, 6", "6, 4, 3, 2", True),
        ("2, 3, 4, 6", "2, 3, 4", False),
        ("1, 7", "1,7", True),
        ("1-2-3", "1, 2, 3", True),
    ],
)
def test_list_answers(key_text: str, given: str, ok: bool) -> None:
    assert grade(build_key("input", ans(key_text)), value=given) is ok


def test_either_of_two_accepted_answers_counts() -> None:
    key = build_key("input", ans("2, 3, 4, 6", "1, 2, 4, 5, 6"))
    assert grade(key, value="1;2;4;5;6") is True
    assert grade(key, value="2;3;4;6") is True
    assert grade(key, value="1;2;3") is False


@pytest.mark.parametrize(("given", "ok"), [("11.7", True), ("12.1", True), ("11,9", True), ("12.2", False)])
def test_range_answers(given: str, ok: bool) -> None:
    assert grade(build_key("input-range", ans("11.7-12.1")), value=given) is ok


@pytest.mark.parametrize(("given", "ok"), [("qxc8", True), (" Q x c8 ", True), ("Qxc7", False)])
def test_text_answers(given: str, ok: bool) -> None:
    assert grade(build_key("input", ans("Qxc8")), value=given) is ok


def test_single_choice_needs_exactly_one_correct_option() -> None:
    key = {"kind": "choice", "mode": "one", "options": [2]}
    assert grade(key, options=[2]) is True
    assert grade(key, options=[1]) is False
    assert grade(key, options=[1, 2]) is False
    assert grade(key, options=[]) is False


def test_single_choice_with_two_marked_answers_accepts_either() -> None:
    key = {"kind": "choice", "mode": "one", "options": [2, 3]}
    assert grade(key, options=[3]) is True


def test_multi_choice_needs_the_exact_set() -> None:
    key = {"kind": "choice", "mode": "all", "options": [1, 3]}
    assert grade(key, options=[3, 1]) is True
    assert grade(key, options=[1]) is False
    assert grade(key, options=[1, 2, 3]) is False


def test_reveal_only_and_missing_keys_are_not_graded() -> None:
    assert grade({"kind": "self"}, value="anything") is None
    assert grade(None, options=[1]) is None


def test_number_parser_rejects_garbage() -> None:
    assert number("1.2.3") is None
    assert number("12 kN") is None
    assert number("1 000") == {"v": 1000.0, "d": 0}
