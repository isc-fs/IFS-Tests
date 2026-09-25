from __future__ import annotations

from typing import Any

import pytest

from ifs_tests.domain.grading import correction, grade, tolerance, unreadable
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
        ("input", "118, 122", "numbers"),
        ("input", "580000, 129", "numbers"),
        ("input", "29,87, 133,86, 35,352", "numbers"),
        ("input", "388,8", "number"),
        ("input", "118 or 122", "number"),
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


# A comma and a space separate values; a bare comma between digits is a decimal comma.
@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("1, 7", [1, 7]),
        ("560, 30", [560, 30]),
        ("118, 122", [118, 122]),
        ("580000, 129", [580000, 129]),
        ("70,79, 4,52", [70.79, 4.52]),
        ("1125000, 3657,5, 119", [1125000, 3657.5, 119]),
    ],
)
def test_a_comma_and_a_space_separate_values(text: str, values: list[float]) -> None:
    key = build_key("input", ans(text))
    assert key is not None and key["kind"] == "numbers"
    assert [v["v"] for v in key["accept"][0]["values"]] == values
    assert number(text) is None


@pytest.mark.parametrize(("text", "value"), [("388,8", 388.8), ("64,107", 64.107), ("1 000", 1000.0)])
def test_a_bare_comma_is_a_decimal_comma(text: str, value: float) -> None:
    n = number(text)
    assert n is not None and n["v"] == value


@pytest.mark.parametrize(
    ("key_text", "given", "ok"),
    [
        ("560, 30", "560; 30", True),
        ("560, 30", "560, 30", True),
        ("560, 30", "560.3", False),
        ("580000, 129", "580000; 129", True),
        ("580000, 129", "580000.129", False),
        ("118 or 122", "118", True),
        ("118 or 122", "122", True),
        ("118 or 122", "120", False),
        ("3.8-3.9 or 4.1-4.2", "4.15", True),
        ("Qxc8 or Qxd8", "qxd8", True),
    ],
)
def test_pairs_and_alternatives(key_text: str, given: str, ok: bool) -> None:
    assert grade(build_key("input", ans(key_text)), value=given) is ok


def test_a_choice_question_with_a_single_option_is_not_graded() -> None:
    assert build_key("single-choice", ans("Upload is not supported (This answer is correct)")) == {
        "kind": "self"
    }
    assert build_key("multi-choice", ans("19.5-19.7")) == {"kind": "self"}
    assert answer_kind("single-choice", {"kind": "self"}) == "choice-one"
    assert display("single-choice", ans("19.5-19.7")) == "19.5-19.7"


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
    assert tolerance({"v": 64107, "d": 0}) == pytest.approx(0.5)  # BANK-05: whole numbers are exact
    assert tolerance({"v": 0.0, "d": 2}) == 0


# BANK-05: whole numbers (counts, 2^15, a binary string, "round to the nearest one") and zero are exact.
@pytest.mark.parametrize(
    ("key_text", "given", "ok"),
    [
        ("32768", "32768", True),
        ("32768", "32768.4", True),
        ("32768", "32767", False),
        ("32768", "32800", False),
        ("111111111101100", "111111111101100", True),
        ("111111111101100", "111111111101101", False),
        ("111111111101100", "111111111100000", False),
        ("64107", "64050", False),
        ("0", "0", True),
        ("0", "0.00", True),
        ("0", "-0", True),
        ("0", "0.4", False),
        ("0", "-0.4", False),
        ("0.0", "0.04", False),
        ("82.9", "82.98", True),  # a key with decimals keeps the 0.1 %
        ("509.85", "510.2", True),
    ],
)
def test_exact_answers(key_text: str, given: str, ok: bool) -> None:
    assert grade(build_key("input", ans(key_text)), value=given) is ok


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


@pytest.mark.parametrize(
    ("given", "ok"),
    [
        ("11.7", True),
        ("12.1", True),
        ("11,9", True),
        ("12.2", False),
        ("11.699999999", True),  # both bounds count, down to float noise
        ("12.100000001", True),
        ("11.69999999", False),
        ("12.10000001", False),
    ],
)
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


# BANK-04 / DOM-11: forms a player obviously means are read; anything else is refused, never graded wrong.
@pytest.mark.parametrize(
    ("key_text", "given"),
    [
        ("0.23", ".23"),
        ("0.23", "0,23"),
        ("3.5", "3.5e0"),
        ("0.23", "2.3E-1"),
        ("-0.5", "-.5"),
        ("64107", "64 107"),
    ],
)
def test_obvious_number_forms_are_read(key_text: str, given: str) -> None:
    key = build_key("input", ans(key_text))
    assert unreadable(key, given) is None
    assert grade(key, value=given) is True


@pytest.mark.parametrize(
    ("qtype", "key_text", "given", "says"),
    [
        ("input", "3.5", "3.5 mm", "no units"),
        ("input", "46", "46%", "no units, %"),
        ("input", "46", "46 %", "no units, %"),
        ("input", "82.9", "about 83", "just a number"),
        ("input", "82.9", "82.9.1", "just a number"),
        ("input-range", "11.7-12.1", "11.7-12.1", "just a number"),
        ("input-range", "11.7-12.1", "12 V", "no units"),
        ("input", "64107", "64,107", "Is 64,107 64.107 or 64107?"),
        ("input", "3404", "-3,404", "Type the one you mean"),
        ("input", "518.4; 604.8", "518.4", "Type 2 numbers separated by semicolons"),
        ("input", "518.4; 604.8", "518.4 V; 604.8 V", "Type 2 numbers"),
        ("input", "518.4; 604.8", "518.4; 604.8; 1", "Type 2 numbers"),
        ("input", "1125000; 3657.5; 119", "1,125; 3657.5; 119", "Type the one you mean"),
    ],
)
def test_answers_the_grader_cannot_read_are_refused_with_what_to_type(
    qtype: str, key_text: str, given: str, says: str
) -> None:
    problem = unreadable(build_key(qtype, ans(key_text)), given)
    assert problem is not None and says in problem


def test_a_list_whose_accepted_answers_differ_in_length_does_not_reveal_how_many() -> None:
    key = build_key("input", ans("2, 3, 4, 6", "1, 2, 4, 5, 6"))
    assert unreadable(key, "1; 2; 3") is None and grade(key, value="1; 2; 3") is False
    assert (
        unreadable(key, "4")
        == "Type the numbers separated by semicolons, like 12.5; 40: no units or other text."
    )


@pytest.mark.parametrize(
    ("key", "given"),
    [
        (None, "3.5 mm"),
        ({"kind": "self"}, "anything"),
        ({"kind": "text", "accept": ["qxc8"]}, "Q x c8!"),
        ({"kind": "number", "accept": [{"v": 3.5, "d": 1}]}, ""),  # no answer: graded wrong, not refused
        ({"kind": "number", "accept": [{"v": 3.5, "d": 1}]}, None),
        ({"kind": "number", "accept": [{"v": 0.125, "d": 3}]}, "0,125"),  # a leading zero is no thousands
    ],
)
def test_what_is_never_refused(key: dict[str, Any] | None, given: str | None) -> None:
    assert unreadable(key, given) is None


# BANK-06 / UI-03: a reviewer's correction is read for the question's own type, and players must be able to type
# it back and be graded right.
@pytest.mark.parametrize(
    ("qtype", "text", "kind"),
    [
        ("input-range", "3.8-3.9", "range"),
        ("input-range", "3.8-3.9 or 4.1-4.2", "range"),
        ("input", "118 or 122", "number"),
        ("input", "82.9", "number"),
        ("input", "70-80", "range"),
        ("input", "518.4; 604.8", "numbers"),
        ("input", "Qxc8", "text"),
        ("input", "6/7", "text"),
        ("drag_sort", "12; 24; 60; 600", "numbers"),  # a drag-sort's correction is typed like an input's
    ],
)
def test_corrections_that_players_can_be_graded_against(qtype: str, text: str, kind: str) -> None:
    key = correction(qtype, text)
    assert key is not None and key["kind"] == kind


@pytest.mark.parametrize(
    ("qtype", "text"),
    [
        ("input-range", "3.8 to 3.9"),
        ("input-range", "12 V"),
        ("input-range", "3.85"),  # a range question takes a range
        ("input", "12.5 kW"),
        ("input", "3.5mm"),
        ("input", "46%"),
        ("input", "3.8 to 3.9"),
        ("input", "1,500"),  # players typing 1,500 would be asked whether they mean 1.5 or 1500
        ("input", "lowest, then the others"),
        ("input", ""),
    ],
)
def test_corrections_players_could_not_be_graded_against_are_refused(qtype: str, text: str) -> None:
    assert correction(qtype, text) is None


def test_a_number_with_a_unit_is_no_text_key() -> None:
    assert build_key("input", ans("12.5 kW")) == {"kind": "self"}
    assert build_key("input", ans("Qxc8"))["kind"] == "text"  # type: ignore[index]


# A pair answers two things in the order the question asks (Q452 "1, 7": days for the first deadline, then for
# the second); three or more ascending whole numbers are a "which of these" set (Q701, Q843, Q854).
@pytest.mark.parametrize(
    ("key_text", "given", "ok"),
    [
        ("1, 7", "1; 7", True),
        ("1, 7", "7; 1", False),
        ("1, 3, 5", "5; 3; 1", True),
        ("1-2-3", "3-2-1", True),
    ],
)
def test_only_three_or_more_ascending_whole_numbers_are_a_set(key_text: str, given: str, ok: bool) -> None:
    assert grade(build_key("input", ans(key_text)), value=given) is ok
