"""Option order for the daily (ADR 0010): which questions are shuffled and which stay in bank order, and that the
shuffle is a pure, key-dependent permutation. Add a row when a real question is wrongly shuffled or wrongly kept."""

from __future__ import annotations

import itertools
import json
import random
import re
import signal
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.domain.shuffle import ORDER_REASONS, Choice, keep_reason, order

ANY = "any"  # kept, whatever the reason
KEY = bytes(range(32))


def choices(*texts: str, retired: tuple[int, ...] = ()) -> list[Choice]:
    """Options in bank order with ids 101, 102, ...; `retired` lists 0-based positions."""
    return [Choice(101 + i, t, i in retired) for i, t in enumerate(texts)]


def reason(
    *texts: str,
    kind: str = "choice-one",
    stem: str = "",
    solutions: tuple[str, ...] = (),
    has_images: bool = False,
) -> str | None:
    return keep_reason(choices(*texts), kind, stem, solutions, has_images=has_images)


def check(texts: tuple[str, ...], want: str | None) -> None:
    got = reason(*texts)
    if want is None:
        assert got is None, f"{texts} kept as {got!r}"
    elif want == ANY:
        assert got is not None, f"{texts} would be shuffled"
    else:
        assert got == want, f"{texts}: {got!r}"


# ---------------------------------------------------------------------------------------------------------------
# Options that depend on the others or on an order stay where they are


@pytest.mark.parametrize(
    "texts",
    [
        ("All of the above", "Cell balancing", "Pre-charge"),
        ("None of the above", "Cell balancing", "Pre-charge"),
        ("Both of the above", "Cell balancing", "Pre-charge"),
        ("Neither of these", "Cell balancing", "Pre-charge"),
        ("Cell balancing", "Pre-charge", "None of the following"),
        ("Cell balancing", "Pre-charge", "All of the following"),
        ("Cell balancing", "Pre-charge", "Neither of the two"),
        ("Cell balancing", "Pre-charge", "Any of these"),
        ("ALL OF THE ABOVE.", "Cell balancing", "Pre-charge"),  # case and a full stop do not hide it
        ("All of the above", "Cell balancing", "Pre-charge"),  # nor a hard space
        ("The first two options", "Cell balancing", "Pre-charge"),
        ("All answers are correct", "Cell balancing", "Pre-charge"),
        ("All except the last", "Cell balancing", "Pre-charge"),
        ("The previous statement", "Cell balancing", "Pre-charge"),
        ("The preceding statement", "Cell balancing", "Pre-charge"),
        ("The preceding statements", "Cell balancing", "Pre-charge"),
        ("Previous answer", "Cell balancing", "Pre-charge"),
        ("The above statement", "Cell balancing", "Pre-charge"),
        ("The following option", "Cell balancing", "Pre-charge"),
        ("Cell balancing", "Pre-charge", "THE PREVIOUS CHOICE."),
        ("Cell balancing", "Pre-charge", "The\u00a0previous\u00a0statement"),
        ("The first two", "Red", "Blue"),
        ("The last two", "Red", "Blue"),
        ("The first and third", "Red", "Blue"),
        ("First and second", "Red", "Blue"),
        ("1st and 2nd", "Red", "Blue"),
        ("Second and third", "Red", "Blue"),
        ("The first and the second", "Red", "Blue"),
        ("The previous one", "Red", "Blue"),
        ("The next one", "Red", "Blue"),
        ("The one above", "Red", "Blue"),
        ("Only the first and third", "Red", "Blue"),
        ("Red", "Blue", "THE LAST TWO."),
        ("Brake bias", "Tyre pressure", "Wing angle", "Any combination of the above"),
        ("Brake bias", "Tyre pressure", "Wing angle", "A combination of the above"),
        ("Brake bias", "Tyre pressure", "Wing angle", "Combination of the above"),
        ("Brake bias", "Tyre pressure", "Wing angle", "Mix of the above"),
        ("Brake bias", "Tyre pressure", "Wing angle", "Combination of the below"),
        ("Brake bias", "Tyre pressure", "Wing angle", "The above"),
        ("Brake bias", "Tyre pressure", "Wing angle", "The above two"),
        ("Brake bias", "Tyre pressure", "Wing angle", "Above two"),
        ("Brake bias", "Tyre pressure", "Wing angle", "Only the above"),
        ("Brake bias", "Tyre pressure", "Wing angle", "None from above"),
        ("Brake bias", "Tyre pressure", "Wing angle", "All from above"),
        ("Brake bias", "Tyre pressure", "Wing angle", "Everything above"),
        ("Brake bias", "Tyre pressure", "Wing angle", "Combination above"),
        ("Brake bias", "Tyre pressure", "Wing angle", "Nothing above"),
        ("Brake bias", "Tyre pressure", "Wing angle", "The other two"),
        ("Brake bias", "Tyre pressure", "Wing angle", "The others"),
        ("Brake bias", "Tyre pressure", "Wing angle", "The remaining"),
        ("Brake bias", "Tyre pressure", "Wing angle", "Both of the first two"),
        ("Brake bias", "Tyre pressure", "Wing angle", "Neither of the first two"),
        ("Brake bias", "Tyre pressure", "Wing angle", "Same as previous"),
        ("Brake bias", "Tyre pressure", "Wing angle", "None apply"),
        ("Brake bias", "Tyre pressure", "Wing angle", "All apply"),
        ("Brake bias", "Tyre pressure", "Wing angle", "These are all correct"),
    ],
)
def test_options_that_refer_to_the_others_stay_in_order(texts: tuple[str, ...]) -> None:
    assert reason(*texts) == "relative"


@pytest.mark.parametrize(
    "texts",
    [
        ("Foo", "Bar", "None"),
        ("Foo", "Bar", "Both"),
        ("Foo", "Bar", "Other"),
        ("Foo", "Bar", "Both are valid"),
        ("Foo", "Bar", "The former"),
        ("Foo", "Bar", "The last one"),
        ("Foo", "Bar", "Only the second one"),
        ("Foo", "Bar", "It depends"),
        ("Foo", "Bar", "Cannot be determined"),
        ("Foo", "Bar", "Same as above"),
    ],
)
def test_a_bare_relative_option_keeps_the_order(texts: tuple[str, ...]) -> None:
    check(texts, ANY)


@pytest.mark.parametrize(
    "texts",
    [
        ("Both A and B", "C", "D"),
        ("A and C", "B", "D"),
        ("Option C", "Option D"),
        ("I and II", "II and III", "III"),
        ("Only III", "I", "II"),
        ("1, 3", "2", "4"),
        ("A only", "B only", "A and B"),
        ("A & B only", "B", "C"),
        ("1 and 2 only", "3", "4"),
        ("A) 5 V", "B) 12 V"),
        ("Circuit A", "Circuit B", "Circuit C"),
        ("Curve 2", "Curve 3"),
        ("Point C", "Point D"),
        ("A", "B", "C"),
        ("Neither A nor B", "C", "D"),
        ("Neither A", "B", "C"),
        ("b) and c) are correct", "a)", "d)"),
        ("a) 5 V", "b) 12 V"),
        ("(a) and (b)", "c", "d"),
        ("a and b", "c", "d"),
        ("Both a and b", "c", "d"),
        ("Both (i) and (ii)", "(i) only", "(ii) only"),
        ("II", "III", "IV"),
        ("I only", "II only"),
        ("I, II and VI", "II and V", "IX"),
        ("(3)", "(4)", "(5)"),
        ("Equal to 2", "Same as 3", "x"),
        ("Fig. A", "Fig. B", "Fig. C"),
        ("Fig. 1", "Fig. 2", "Fig. 3"),
        ("Graph a", "Graph b", "Graph c"),
        ("a", "b", "c", "d"),
        ("i", "ii", "iii", "iv"),
        ("i and ii", "ii and iii", "i and iii"),
        ("Type A", "Type B", "Type C"),
        ("Diagram 1", "Diagram 2", "Diagram 3", "Diagram 4"),
        ("A - Front wing", "B - Rear wing", "C - Floor"),
        ("A \u2013 Front wing", "B \u2013 Rear wing", "C \u2013 Floor"),
        ("A \u2014 Front wing", "B \u2014 Rear wing", "C \u2014 Floor"),
        ("A Front wing", "B Rear wing", "C Floor"),
        ("a. Front wing", "b. Rear wing", "c. Floor"),
        ("i) Front", "ii) Rear", "iii) Floor"),
        ("i. Front", "ii. Rear", "iii. Floor"),
        ("I. Front", "II. Rear", "III. Floor"),
    ],
)
def test_options_that_name_a_letter_or_a_label_stay_in_order(texts: tuple[str, ...]) -> None:
    assert reason(*texts) == "label"


@pytest.mark.parametrize(
    "texts",
    [
        ("B and D are correct", "A", "C"),
        ("A, B and D are correct", "C", "E"),
        ("All except C", "Cell balancing", "Pre-charge"),
        ("Same as B", "Cell balancing", "Pre-charge"),
        ("1 and 3 are true", "2", "4"),
        ("Statements 1 and 2 are correct", "Statement 3 is correct", "None"),
        ("Neither A nor C", "B", "D"),
    ],
)
def test_options_that_say_which_others_are_right_stay_in_order(texts: tuple[str, ...]) -> None:
    check(texts, ANY)


@pytest.mark.parametrize(
    "texts",
    [
        ("At least 2", "At most 2", "Exactly 2"),
        ("Up to 3", "About 5", "At most 4"),
        ("Exactly 4", "At least 2", "About 3"),
        ("At least 2 wheels", "At most 2 wheels", "Exactly 2 wheels"),
    ],
)
def test_quantity_words_are_not_labels(texts: tuple[str, ...]) -> None:
    check(texts, None)


@pytest.mark.parametrize("texts", [("Yes", "No"), ("True", "False"), ("yes", "no"), ("TRUE", "FALSE")])
def test_yes_no_pairs_stay_in_order(texts: tuple[str, ...]) -> None:
    assert reason(*texts) == "yes-no"


# ---------------------------------------------------------------------------------------------------------------
# Scales


@pytest.mark.parametrize(
    "texts",
    [
        ("1 s", "2 s", "5 s", "10 s"),
        ("10 s", "5 s", "2 s", "1 s"),
        ("12 V", "24 V", "60 V DC", "600 V DC"),
        ("500 kg", "1,000 kg", "2,000 kg"),
        ("1/2 s", "1 s", "2 s"),
        ("½ s", "1 s", "2 s"),
    ],
)
def test_plain_sorted_quantities_are_a_scale(texts: tuple[str, ...]) -> None:
    assert reason(*texts) == "ladder-sorted"


@pytest.mark.parametrize(
    "texts",
    [
        ("<5 V", "5-10 V", ">10 V"),
        ("Less than 5 V", "Between 5 and 10 V", "More than 10 V"),
        ("T 11.2.1", "T 11.2.2", "T 11.2.3"),
    ],
)
def test_bounded_or_labelled_ranges_are_a_scale(texts: tuple[str, ...]) -> None:
    assert reason(*texts) == "ladder-range"


@pytest.mark.parametrize("minus", ["-", "−"])
def test_signed_values_are_a_scale_with_either_minus(minus: str) -> None:
    got = reason(f"{minus}20 °C", "0 °C", "20 °C")
    assert got in ("ladder-sorted", "ladder-range")


@pytest.mark.parametrize(
    "texts", [("Low", "Medium", "High"), ("Never", "Sometimes", "Always"), ("Less", "Same", "More")]
)
def test_word_scales_stay_in_order(texts: tuple[str, ...]) -> None:
    assert reason(*texts) == "ladder-word"


@pytest.mark.parametrize(
    "texts",
    [
        ("0.713 m", "0.837 m", "0.775 m", "0.620 m"),  # numbers, but in no order
        ("0.6 kNm", "1.2 kNm", "2.4 kNm", "0.3 kNm"),
        ("5 A", "10 A", "3 A"),  # a slash or a unit does not make a ladder
        ("V/A", "W/V", "A/W"),
        ("1/4", "3/4", "1/2"),
        ("1 s", "5 s", "2 s"),
        ("3", "5", "2", "4"),  # small counts say nothing about the others
        ("2,5/1 gear ratio", "1 gear ratio", "4 gear ratio"),  # a comma decimal in a fraction is a number
        ("1,5/2 s", "1 s", "0,5/3 s"),
    ],
)
def test_numbers_in_no_order_are_shuffled(texts: tuple[str, ...]) -> None:
    check(texts, None)


@pytest.mark.parametrize("texts", [("2,5/1 gear ratio", "3 kg", "4 kg"), ("1,5/2 s", "3 s", "4 s")])
def test_a_comma_decimal_fraction_is_read_as_a_number_and_never_raises(texts: tuple[str, ...]) -> None:
    assert reason(*texts) == "ladder-sorted"
    assert reason("1/0 s", "2 s", "3 s") is None  # a zero denominator is no number


@pytest.mark.parametrize(
    "texts",
    [
        ("-1.2.3", "2", "3"),
        ("+1.2.3 V", "+1.2.4 V", "+2.0.0 V"),
        ("\u22121.2.3", "2", "3"),
        ("1.2.3", "1.2.4", "1.3.0"),
        ("-1.2.3 V", "-1.2.4 V", "-1.3.0 V"),
    ],
)
def test_a_signed_dotted_number_never_raises(texts: tuple[str, ...]) -> None:
    assert reason(*texts) in (None, "ladder-sorted", "ladder-range")


def test_keep_reason_never_raises_on_arbitrary_text() -> None:
    rng = random.Random(7)
    alphabet = "0123456789.,/-+\u2212\u2013 ABabIVx\u00bd()<>:;&"
    for _ in range(20000):
        texts = ["".join(rng.choices(alphabet, k=rng.randint(0, 9))) for _ in range(rng.randint(2, 4))]
        keep_reason(choices(*texts), "choice-one", "".join(rng.choices(alphabet, k=8)), (texts[0],))


def test_two_options_are_never_a_scale() -> None:
    check(("1 s", "2 s"), None)
    check(("Low", "High"), None)


# ---------------------------------------------------------------------------------------------------------------
# Kinds, blanks, stems and solutions


@pytest.mark.parametrize("kind", ["number", "numbers", "range", "text", "self", "drag_sort"])
def test_only_choice_questions_are_shuffled(kind: str) -> None:
    assert reason("Foo", "Bar", "Baz", kind=kind) == "kind"


def test_choice_many_is_shuffled_like_choice_one() -> None:
    assert reason("Foo", "Bar", "Baz", kind="choice-many") is None


def test_fewer_than_two_live_options_is_kept() -> None:
    assert keep_reason(choices("Only one"), "choice-one") == "kind"
    assert keep_reason(choices("Foo", "Bar", retired=(1,)), "choice-one") == "kind"


@pytest.mark.parametrize("blank", ["", "   ", " ", "\n"])
def test_an_empty_option_is_kept(blank: str) -> None:
    assert reason("Foo", blank, "Baz") == "blank"


@pytest.mark.parametrize(
    "stem",
    [
        "Which of options A-C is correct?",
        "Which of options A–C is correct?",
        "Looking at the circuit (A) to (D), which is a buck converter?",
        "Which is correct, answer B or answer C?",
        "Select the first option that applies.",
        "Which is correct? (a), (b) or (c)",
        "Which of the options (A-D) is right?",
    ],
)
def test_a_stem_that_names_the_options_keeps_the_order(stem: str) -> None:
    assert reason("Foo", "Bar", "Baz", stem=stem) == "stem"


@pytest.mark.parametrize(
    "solution",
    [
        "The correct choice is the last one.",
        "The correct one is the second.",
        "Only the first two are wrong.",
        "The first and third are true.",
    ],
)
def test_a_solution_that_cites_a_position_keeps_the_order(solution: str) -> None:
    assert reason("Foo", "Bar", "Baz", solutions=(solution,)) == "solution"


@pytest.mark.parametrize("stem", ["Choose a, b or c", "Select a, b, or c.", "Pick a, b and c"])
def test_a_stem_with_lowercase_letters_keeps_the_order(stem: str) -> None:
    assert reason("Foo", "Bar", "Baz", stem=stem) == "stem"


def test_a_solution_that_cites_a_letter_keeps_the_order() -> None:
    assert reason("Foo", "Bar", "Baz", solutions=("The correct answer is C because ...",)) == "solution"
    assert reason("Foo", "Bar", "Baz", solutions=("Unrelated.", "Option B is correct.")) == "solution"


@pytest.mark.parametrize(
    "solution",
    [
        "Answer b is correct.",
        "Correct: C",
        "Correct: (C).",
        "C. Because the relay opens first.",
        "(B) is right.",
    ],
)
def test_other_ways_a_solution_cites_a_letter_keep_the_order(solution: str) -> None:
    assert reason("Foo", "Bar", "Baz", solutions=(solution,)) == "solution"


@pytest.mark.parametrize(
    ("stem", "solutions"),
    [
        ("Which statement a driver must follow", ()),
        ("Name the answer a judge would accept", ()),
        ("Which is a valid reason?", ("Answer: A driver must ...",)),
        ("What is a typical value?", ("A battery pack is usually rated at 600 V.",)),
        ("What is a typical wheelbase?", ("Correct: A short wheelbase turns faster.",)),
        ("An A-D converter has how many bits?", ()),
        ("A B-E connector pair is used for what?", ()),
        ("Evaluate f(a) at the corner", ()),
    ],
)
def test_ordinary_prose_does_not_trigger_the_letter_rules(stem: str, solutions: tuple[str, ...]) -> None:
    assert reason("Foo", "Bar", "Baz", stem=stem, solutions=solutions) is None


# ---------------------------------------------------------------------------------------------------------------
# Real wording that must still shuffle


@pytest.mark.parametrize(
    "texts",
    [
        ("AS Emergency", "AS Finished", "AS Off", "AS Ready"),
        (
            "Both accumulator isolation relays (AIRs)",
            "The precharge relay",
            "The LV master switch",
            "The brake light",
        ),
        ("The rules", "The event handbook", "The latest published document"),
        ("Above 60 V", "Below 60 V", "Exactly 60 V"),
        ("AMS", "BMS", "IMD"),
        ("Voltage", "Current", "Resistance"),
        ("Ampere", "Volt", "Watt"),
        ("All cells must be within the correct range", "The pack must be isolated", "x"),
        ("Equal to 1 A", "Equal to 5 V", "Equal to 2 times the force"),
        ("Other than 3 phases", "Except 3 s", "Same as 2 kN"),
        ("A driver must wear a helmet", "A marshal must stay behind the barrier", "A team member may help"),
        ("Cell balancing", "Pre-charge", "Isolation monitoring", "Thermal runaway detection"),
        ("First gear", "Second gear", "Third gear"),
        ("The last lap", "The first lap", "A formation lap"),
        ("1st gear", "2nd gear", "Neutral"),
        ("Second", "Fastest", "Slowest"),
        ("Ordinary prose", "The next generation of cells", "The previous season's car"),
        ("Above the driver's head", "Below the floor", "Beside the cockpit"),
        ("Above", "Below", "At the limit"),
        ("Mix of fuel and air", "Combination lock", "Everything the driver needs"),
        ("The other driver", "The remaining fuel", "Others' feedback"),
    ],
)
def test_realistic_options_are_shuffled(texts: tuple[str, ...]) -> None:
    check(texts, None)


def test_a_retired_relative_option_still_decides_the_verdict() -> None:
    texts = ("Cell balancing", "Pre-charge", "Isolation monitoring", "All of the above")
    assert keep_reason(choices(*texts, retired=(3,)), "choice-one") == "relative"
    assert keep_reason(choices(*texts[:3]), "choice-one") is None  # the same options without it shuffle


def test_keep_reason_ignores_the_ids() -> None:
    texts = ("AS Emergency", "AS Finished", "AS Off", "AS Ready")
    other = [Choice(9000 - i, t) for i, t in enumerate(texts)]
    assert keep_reason(other, "choice-one") is None


# ---------------------------------------------------------------------------------------------------------------
# order()

SHUFFLED = choices("AS Emergency", "AS Finished", "AS Off", "AS Ready")
KEPT = choices("Cell balancing", "Pre-charge", "All of the above")


def ids(cs: list[Choice]) -> list[int]:
    return [c.id for c in cs]


def test_order_is_deterministic_and_a_permutation() -> None:
    first = order(SHUFFLED, KEY, "choice-one")
    assert first == order(SHUFFLED, KEY, "choice-one")
    assert sorted(first) == sorted(ids(SHUFFLED)) and len(first) == len(SHUFFLED)


def test_a_kept_question_comes_back_in_the_order_it_was_given() -> None:
    assert order(KEPT, KEY, "choice-one") == ids(KEPT)
    reversed_in = list(reversed(KEPT))
    assert order(reversed_in, KEY, "choice-one") == ids(reversed_in)  # no sorting at all
    typed = choices("Foo", "Bar", "Baz")
    assert order(typed, KEY, "drag_sort") == ids(typed)


def test_the_stem_and_the_solutions_decide_in_order_too() -> None:
    plain = choices("Foo", "Bar", "Baz")
    assert order(plain, KEY, "choice-one", "Which of options A-C?") == ids(plain)
    assert order(plain, KEY, "choice-one", "", ("The answer is B.",)) == ids(plain)


def test_the_order_does_not_depend_on_the_order_the_options_arrive_in() -> None:
    assert order(list(reversed(SHUFFLED)), KEY, "choice-one") == order(SHUFFLED, KEY, "choice-one")
    assert order(SHUFFLED[2:] + SHUFFLED[:2], KEY, "choice-one") == order(SHUFFLED, KEY, "choice-one")


def test_removing_an_option_leaves_the_others_where_they_were_relative_to_each_other() -> None:
    full = order(SHUFFLED, KEY, "choice-one")
    for gone in SHUFFLED:
        rest = [c for c in SHUFFLED if c.id != gone.id]
        assert order(rest, KEY, "choice-one") == [i for i in full if i != gone.id]


def test_the_input_is_not_changed() -> None:
    before = list(SHUFFLED)
    order(SHUFFLED, KEY, "choice-one")
    assert before == SHUFFLED


def test_a_retired_option_is_sorted_with_the_rest() -> None:
    texts = ("AS Emergency", "AS Finished", "AS Off", "AS Ready")
    live = order(choices(*texts), KEY, "choice-one")
    with_retired = order(choices(*texts, retired=(1,)), KEY, "choice-one")
    assert with_retired == live  # retiring does not move anyone


def test_different_keys_give_different_orders_and_every_option_leads_about_equally() -> None:
    seen: Counter[tuple[int, ...]] = Counter()
    first: Counter[int] = Counter()
    for i in range(200):  # fixed keys: the numbers below cannot flake
        got = order(SHUFFLED, bytes([i]) * 32, "choice-one")
        seen[tuple(got)] += 1
        first[got[0]] += 1
    assert len(seen) >= 20  # of the 24 permutations of four options
    for option in ids(SHUFFLED):
        assert 0.15 * 200 <= first[option] <= 0.35 * 200, first


def test_the_ids_not_the_texts_drive_the_sort() -> None:
    a = [Choice(1, "the pack"), Choice(2, "the relay"), Choice(3, "third thing"), Choice(4, "fourth thing")]
    b = [Choice(1, "different"), Choice(2, "words"), Choice(3, "entirely here"), Choice(4, "now")]
    assert order(a, KEY, "choice-one") == order(b, KEY, "choice-one")


# ---------------------------------------------------------------------------------------------------------------
# The sample bank: real shapes


def sample() -> dict[int, dict[str, Any]]:
    bank = json.loads((SAMPLE_DIR / "bank.json").read_text())
    return {q["question_id"]: q for q in bank["questions"]}


def verdict(fsquiz_id: int) -> str | None:
    q = sample()[fsquiz_id]
    answers = [a["text"] for a in q["answers"]]
    kind = "choice-many" if q["type"] == "multi-choice" else "choice-one"
    return keep_reason(choices(*answers), kind, q["text"], tuple(s["text"] for s in q["solutions"]))


@pytest.mark.parametrize("fsquiz_id", [90001, 90003, 90006, 90011])
def test_the_sample_questions_with_free_wording_are_shuffled(fsquiz_id: int) -> None:
    assert verdict(fsquiz_id) is None


def test_the_sample_penalty_question_is_a_scale() -> None:
    assert verdict(90008) == "ladder-sorted"


def test_the_sample_rules_and_handbook_question_has_a_reason_code_or_none() -> None:
    got = verdict(90010)
    assert got is None or isinstance(got, str)  # ungraded, never a daily: only that it does not crash


def test_every_permutation_of_the_four_option_sample_is_reachable() -> None:
    texts = ("AS Emergency", "AS Finished", "AS Off", "AS Ready")
    reached = {tuple(order(choices(*texts), i.to_bytes(2, "big") * 16, "choice-one")) for i in range(2000)}
    assert len(reached) == len(list(itertools.permutations(range(4))))


# ---------------------------------------------------------------------------------------------------------------
# A picture: only options or a stem that talk about labels can hide a label printed in the image

LONG_OPTIONS = (
    "The precharge relay closes before the contactors",
    "The contactors close before the precharge relay",
    "The order depends on the temperature",
)
FREE_OPTIONS = [
    ("Cell balancing", "Pre-charge", "Isolation monitoring", "Thermal runaway detection"),
    ("AS Emergency", "AS Finished", "AS Off", "AS Ready"),
    ("Voltage", "Current", "Resistance"),
    ("A buck converter with a freewheeling diode across the load", "Boost", "A flyback with feedback loop"),
    ("9531 N", "10885 N", "8250 N", "9112 N"),
    ("t = 9.028 mm", "t = 8.114 mm", "t = 10.392 mm", "t = 9.765 mm"),
    ("0.6 kNm", "1.2 kNm", "2.4 kNm", "0.3 kNm"),
    ("0.713 m", "0.837 m", "0.775 m", "0.620 m"),
]
LABEL_OPTIONS = [
    ("A", "B", "C", "D"),
    ("a", "b", "c"),
    ("1", "2", "3", "4"),
    ("I", "II", "III"),
    ("i", "ii", "iii", "iv"),
    ("Fig. A", "Fig. B", "Fig. C"),
    ("Fig. 1", "Fig. 2", "Fig. 3"),
]
OTHER_LABELS = [
    ("Figure 1", "Figure 2", "Figure 3"),
    ("Diagram 1", "Diagram 2", "Diagram 3"),
    ("Graph A", "Graph B", "Graph C"),
    ("Curve 1", "Curve 2", "Curve 3"),
    ("Option A", "Option B", "Option C"),
    ("Case 1", "Case 2", "Case 3"),
]
LABEL_STEMS = [
    "Which component is labelled on the diagram?",
    "Name the part marked on the picture.",
    "Which of the lettered parts is the damper?",
    "Which of the numbered items is the damper?",
]
LABEL_STEMS_WITH_A_LETTER = [
    "The part shown as A in the figure is what?",
    "What is the load at point B of the graph?",
]


@pytest.mark.parametrize("texts", FREE_OPTIONS)
def test_a_figure_alone_no_longer_keeps_short_or_numeric_options(texts: tuple[str, ...]) -> None:
    assert reason(*texts, has_images=True) is None
    assert reason(*texts, has_images=True, stem="Which statement about the figure is true?") is None
    assert reason(*texts) is None


def test_calculation_options_under_a_figure_stem_are_shuffled() -> None:
    stem = "Calculate the value for the geometry shown in the figure."
    assert reason("9531 N", "10885 N", "8250 N", "9112 N", has_images=True, stem=stem) is None
    assert (
        reason("t = 9.028 mm", "t = 8.114 mm", "t = 10.392 mm", "t = 9.765 mm", has_images=True, stem=stem)
        is None
    )


@pytest.mark.parametrize("texts", LABEL_OPTIONS)
def test_label_like_options_with_a_picture_stay_in_order_as_a_figure(texts: tuple[str, ...]) -> None:
    assert reason(*texts, has_images=True) == "figure"


@pytest.mark.parametrize("texts", OTHER_LABELS)
def test_named_label_options_with_a_picture_stay_in_order(texts: tuple[str, ...]) -> None:
    assert reason(*texts, has_images=True) in ("figure", "label")


@pytest.mark.parametrize("stem", LABEL_STEMS)
def test_a_stem_that_talks_about_labels_with_a_picture_keeps_the_order_whatever_the_options(
    stem: str,
) -> None:
    assert reason(*LONG_OPTIONS, stem=stem, has_images=True) == "figure"
    assert (
        reason("Cell balancing", "Pre-charge", "Isolation monitoring", stem=stem, has_images=True) == "figure"
    )
    assert reason(*LONG_OPTIONS, stem=stem) is None  # no image attached: only wording, nothing to hide


@pytest.mark.parametrize("stem", LABEL_STEMS_WITH_A_LETTER)
def test_a_stem_that_names_a_label_is_kept_with_a_picture_for_one_reason_or_another(stem: str) -> None:
    assert reason(*LONG_OPTIONS, stem=stem, has_images=True) in ("figure", "stem")


@pytest.mark.parametrize(
    "stem",
    [
        "Which statement about the circuit shown is correct?",
        "Which statement about this diagram is true?",
        "What does the graph tell you about the pack?",
        "Which statement about the curve is true?",
        "Which statement about the figure is true?",
        "Which statement about the image is true?",
        "Which statement about the Circuit is true?",
        "Which circuit is shown in the figure?",
    ],
)
def test_a_stem_that_merely_points_at_the_picture_does_not_keep_the_order(stem: str) -> None:
    assert reason(*LONG_OPTIONS, stem=stem, has_images=True) is None
    assert reason(*FREE_OPTIONS[0], stem=stem, has_images=True) is None


def test_a_picture_with_long_free_wording_is_still_shuffled() -> None:
    stem = "Which statement about the precharge sequence is true?"
    assert reason(*LONG_OPTIONS, stem=stem, has_images=True) is None


def test_label_like_options_without_a_picture_are_not_the_figure_code() -> None:
    for texts in LABEL_OPTIONS:
        assert reason(*texts) != "figure"
    for stem in LABEL_STEMS:
        assert reason(*LONG_OPTIONS, stem=stem) != "figure"


def test_an_image_does_not_hide_a_better_reason_for_keeping_the_order() -> None:
    assert reason("All of the above", "Boost", "Buck", has_images=True) is not None
    assert reason("Foo", "Bar", "Baz", kind="drag_sort", has_images=True) == "kind"
    assert reason("Foo", "", "Baz", has_images=True) in ("blank", "figure")


def test_order_keeps_a_figure_question_in_the_order_it_was_given() -> None:
    given = choices(*LABEL_OPTIONS[0])
    for i in range(20):
        assert order(given, bytes([i]) * 32, "choice-one", has_images=True) == ids(given)
    words = choices(*FREE_OPTIONS[1])
    moved = {tuple(order(words, bytes([i]) * 32, "choice-one", has_images=True)) for i in range(20)}
    assert len(moved) > 1  # a picture with free wording is shuffled


# ---------------------------------------------------------------------------------------------------------------
# Catch-alls, "no answer", references in mid-sentence and currencies


@pytest.mark.parametrize(
    "texts",
    [
        ("Graph 1 is steeper", "Graph 2 is steeper", "None of the graphs"),
        ("Graph 1 is steeper", "Graph 2 is steeper", "There is no correct answer"),
        ("Cell balancing", "Pre-charge", "None of the circuits"),
        ("Cell balancing", "Pre-charge", "Neither of the two circuits"),
        ("Cell balancing", "Pre-charge", "All of the relays"),
        ("Cell balancing", "Pre-charge", "Both of the diagrams"),
        ("Cell balancing", "Pre-charge", "No correct answer"),
        ("Cell balancing", "Pre-charge", "No answer is correct"),
        ("Cell balancing", "Pre-charge", "There are no correct answers"),
        ("Cell balancing", "Pre-charge", "No option applies"),
        ("Cell balancing", "Pre-charge", "No options are valid"),
        ("None of the circuits", "Cell balancing", "Pre-charge"),
    ],
)
def test_a_catch_all_option_keeps_the_order(texts: tuple[str, ...]) -> None:
    assert reason(*texts) == "relative"


@pytest.mark.parametrize(
    "texts",
    [
        ("It is always true", "It is never true", "It is only true if the previous statement holds"),
        ("Valid only if the preceding statements are false", "Always valid", "Never valid"),
        ("Holds when the previous answer is wrong", "Holds always", "Holds never"),
        ("Only if the next option is wrong", "Cell balancing", "Pre-charge"),
        ("True unless the above statement is false", "Always true", "Never true"),
        ("Right when the prior choices are wrong", "Always right", "Never right"),
    ],
)
def test_a_reference_in_the_middle_of_an_option_keeps_the_order(texts: tuple[str, ...]) -> None:
    assert reason(*texts) == "relative"


@pytest.mark.parametrize(
    "texts",
    [
        ("The cell voltage rises above the limit", "The pack is isolated", "The next lap is slower"),
        (
            "The temperature stays above 60 degrees",
            "The temperature drops below 20 degrees",
            "It never changes",
        ),
        (
            "The car takes the next corner flat",
            "The car brakes before the corner",
            "The car stays on the straight",
        ),
        ("The previous season's chassis", "The current chassis", "A prototype chassis"),
        ("Above-average cooling", "Standard cooling", "No active cooling"),
    ],
)
def test_prose_with_next_previous_or_above_that_points_at_no_option_is_shuffled(
    texts: tuple[str, ...],
) -> None:
    check(texts, None)


@pytest.mark.parametrize(
    "texts",
    [
        ("\u20ac1,000", "\u20ac2,000", "\u20ac5,000"),
        ("$10", "$20", "$50"),
        ("\u00a3100", "\u00a3250", "\u00a3500"),
        ("\u20ac1,000", "\u20ac2,000", "\u20ac5,000", "\u20ac10,000"),
    ],
)
def test_amounts_with_a_currency_prefix_are_a_scale_like_any_unit(texts: tuple[str, ...]) -> None:
    assert (reason(*texts) or "").startswith("ladder")
    assert (reason("5 V", "12 V", "24 V") or "").startswith("ladder")


def test_amounts_with_a_currency_prefix_in_no_order_are_shuffled() -> None:
    check(("\u20ac5,000", "\u20ac1,000", "\u20ac2,000", "\u20ac1,500"), None)
    check(("$50", "$10", "$20"), None)


@pytest.mark.parametrize(
    ("stem", "want"),
    [
        ("Which of the statements below is correct?", None),
        ("Which of the rules listed below applies?", None),
        ("Which of the statements above is correct?", "stem"),
        ("As stated above, what happens next?", "stem"),
        ("Which is true of the option above?", "stem"),
    ],
)
def test_below_in_a_stem_is_position_free_but_above_is_not(stem: str, want: str | None) -> None:
    assert reason("Foo", "Bar", "Baz", stem=stem) == want


# ---------------------------------------------------------------------------------------------------------------
# The verdict is judged on the order the options are given in


def ladder(*texts: str) -> list[Choice]:
    return [Choice(i + 1, t) for i, t in enumerate(texts)]


def test_the_same_options_are_a_scale_in_one_order_and_not_in_another() -> None:
    assert reason("1 s", "2 s", "5 s", "10 s") == "ladder-sorted"
    assert reason("5 s", "1 s", "10 s", "2 s") is None
    assert reason("5 s", "1 s", "10 s", "2 s") != reason("1 s", "2 s", "5 s", "10 s")


def test_order_follows_the_given_sequence_for_a_scale_and_shuffles_the_same_values_given_scrambled() -> None:
    sorted_in = [Choice(2, "1 s"), Choice(4, "2 s"), Choice(1, "5 s"), Choice(3, "10 s")]
    assert order(sorted_in, KEY, "choice-one") == [2, 4, 1, 3]
    scrambled = [Choice(1, "5 s"), Choice(2, "1 s"), Choice(3, "10 s"), Choice(4, "2 s")]
    again = list(reversed(scrambled))  # 2 s, 10 s, 1 s, 5 s: not a scale either
    assert order(scrambled, KEY, "choice-one") == order(again, KEY, "choice-one")
    moved = {tuple(order(scrambled, bytes([i]) * 32, "choice-one")) for i in range(20)}
    assert len(moved) > 1


def test_dropping_an_option_of_a_scale_can_change_nothing_but_the_verdict_of_what_is_left() -> None:
    full = ladder("1 s", "2 s", "5 s", "10 s")
    assert order(full, KEY, "choice-one") == ids(full)
    rest = [c for c in full if c.id != 2]
    assert order(rest, KEY, "choice-one") == ids(rest)  # still increasing: still kept, in the same sequence


# ---------------------------------------------------------------------------------------------------------------
# Unicode spaces and hostile input


@pytest.mark.parametrize("space", [" ", " ", " ", "　", " ", " "])
def test_unicode_spaces_do_not_hide_a_kept_option(space: str) -> None:
    assert reason(f"All{space}of{space}the{space}above", "Cell balancing", "Pre-charge") == "relative"
    assert reason(f"Option{space}C", f"Option{space}D") == "label"
    assert reason(f"{space}Yes{space}", f"{space}No{space}") == "yes-no"
    assert reason("Foo", space, "Baz") == "blank"
    assert reason(f"Fig.{space}A", f"Fig.{space}B", f"Fig.{space}C") == "label"
    assert reason(f"Cell{space}balancing", f"Pre-charge{space}", f"{space}Isolation monitoring") is None


def test_exotic_text_never_raises() -> None:
    odd = ("\u0000", "🚗🏁", "ÁÉÍÓÚ ñ", "١٢٣", "ⅷ", "﻿", "Á", "a" * 5000)
    for kind in ("choice-one", "choice-many"):
        for a, b, c in itertools.permutations(odd, 3):
            got = keep_reason(choices(a, b, c), kind, "\u0000", ("🚗",))
            assert got is None or isinstance(got, str)
            assert sorted(order(choices(a, b, c), KEY, kind)) == [101, 102, 103]


def test_hostile_repeated_tokens_are_judged_quickly() -> None:
    """Option, stem and solution text come from FS-Quiz, not from an attacker: this only guards against a pattern
    turning quadratic. The alarm turns a runaway pattern into a failure instead of a hung run."""
    hostile = ["first, " * 20_000, "a)" * 20_000, " " * 50_000, "All of the " * 5_000, "1 s " * 10_000]

    def runaway(*_: object) -> None:
        raise AssertionError("keep_reason is running away on repeated tokens")

    old = signal.signal(signal.SIGALRM, runaway)
    signal.setitimer(signal.ITIMER_REAL, 5)
    try:
        for text in hostile:
            keep_reason(choices(text, "Foo", "Bar"), "choice-one")
            keep_reason(choices("Foo", "Bar", "Baz"), "choice-many", text)
            keep_reason(choices("Foo", "Bar", "Baz"), "choice-one", "", (text,))
            keep_reason(choices(text, "Foo", "Bar"), "choice-one", "Which is labelled?", has_images=True)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


# ---------------------------------------------------------------------------------------------------------------
# The reason codes: one table


CODES = {
    "kind",
    "blank",
    "relative",
    "label",
    "figure",
    "yes-no",
    "ladder-range",
    "ladder-sorted",
    "ladder-word",
    "stem",
    "solution",
}


def test_the_reason_table_holds_every_code_once() -> None:
    assert len(ORDER_REASONS) == len(set(ORDER_REASONS))
    assert set(ORDER_REASONS) >= CODES


def test_every_reason_the_rules_give_is_in_the_table() -> None:
    rows: list[dict[str, Any]] = [
        {"texts": ("Foo", "Bar", "Baz"), "kind": "drag_sort"},
        {"texts": ("Foo", "", "Baz")},
        {"texts": ("All of the above", "Foo", "Bar")},
        {"texts": ("Option C", "Option D")},
        {"texts": ("A", "B", "C"), "has_images": True},
        {"texts": ("Yes", "No")},
        {"texts": ("<5 V", "5-10 V", ">10 V")},
        {"texts": ("1 s", "2 s", "5 s", "10 s")},
        {"texts": ("Low", "Medium", "High")},
        {"texts": ("Foo", "Bar", "Baz"), "stem": "Which of the options above?"},
        {"texts": ("Foo", "Bar", "Baz"), "solutions": ("The answer is B.",)},
    ]
    got = set()
    for row in rows:
        kind, texts = row.pop("kind", "choice-one"), row.pop("texts")
        r = keep_reason(choices(*texts), kind, **row)
        assert r in ORDER_REASONS
        got.add(r)
    assert got == CODES  # the rows above exercise every code the table promises


# ---------------------------------------------------------------------------------------------------------------
# More ways to refer to the other options, and number words that name a position


RELATIVE_PHRASES = [
    "One of the above",
    "At least two of the above",
    "Each of them",
    "Every one of them",
    "Only one of them",
    "More than one",
    "Two of them",
    "The two above",
    "See above",
    "The answer is above",
    "Everything",
]


@pytest.mark.parametrize("phrase", RELATIVE_PHRASES)
@pytest.mark.parametrize("variant", ["{}", "{}.", "  {}  ", "THE {}"])
def test_the_added_relative_phrases_keep_the_order(phrase: str, variant: str) -> None:
    if variant.startswith("THE"):
        phrase = phrase.upper()
        variant = "{}"
    text = variant.format(phrase)
    assert reason("Cell balancing", "Pre-charge", text) == "relative", text
    assert reason(text, "Cell balancing", "Pre-charge") == "relative", text
    assert reason("Cell balancing", text, "Pre-charge") == "relative", text


@pytest.mark.parametrize(
    "phrase",
    [
        "At least three of these",
        "Some of the others",
        "Most of the options",
        "Three of those",
        "Each of the answers",
        "Only one of the options",
    ],
)
def test_relative_phrases_that_name_the_group_keep_the_order(phrase: str) -> None:
    assert reason("Cell balancing", "Pre-charge", phrase) == "relative"


def test_relative_phrases_are_found_in_a_longer_option_too() -> None:
    assert reason("Cell balancing", "Pre-charge", "Valid for one of the above only") == "relative"
    assert reason("Cell balancing", "Pre-charge", "True of at least two of the above") == "relative"


@pytest.mark.parametrize(
    "texts",
    [
        ("Above the driver's head", "Beside the driver", "Behind the driver"),
        ("Cell balancing", "Pre-charge", "Nobody"),
        ("Cell balancing", "Pre-charge", "Anything else"),
        ("Above the driver's head", "Nobody", "Anything else"),
        ("Below the floor line", "Cell balancing", "Pre-charge"),
        ("Above 60 degrees", "Below 20 degrees", "Between 20 and 60 degrees"),
        ("Close to them", "Far from the car", "On the wall"),
    ],
)
def test_short_options_that_merely_contain_above_below_or_them_are_still_shuffled(
    texts: tuple[str, ...],
) -> None:
    got = reason(*texts)
    assert got is None or got.startswith("ladder"), f"{texts}: {got!r}"  # a bounded scale is the one excuse


@pytest.mark.parametrize(
    "texts",
    [
        ("Above the driver's head", "Beside the driver", "Behind the driver"),
        ("Cell balancing", "Pre-charge", "Nobody"),
        ("Cell balancing", "Pre-charge", "Anything else"),
        ("Above the driver's head", "Nobody", "Anything else"),
    ],
)
def test_the_counter_rows_of_the_spec_are_shuffled(texts: tuple[str, ...]) -> None:
    check(texts, None)


@pytest.mark.parametrize(
    "text",
    [
        "Option one",
        "Option two",
        "Option three",
        "Answer two",
        "Answer one",
        "Choice three",
        "Choice two",
        "choice THREE",
        "OPTION ONE.",
    ],
)
def test_a_number_word_after_a_noun_names_a_position(text: str) -> None:
    assert reason("Cell balancing", "Pre-charge", text) == "label", text
    assert reason(text, "Cell balancing", "Pre-charge") == "label", text


def test_number_word_labels_in_a_full_set_are_labels() -> None:
    assert reason("Option one", "Option two", "Option three") == "label"
    assert reason("Answer one", "Answer two") == "label"
    assert reason("Choice one", "Choice two", "Choice three", "Choice four") == "label"


# ---------------------------------------------------------------------------------------------------------------
# Each text is capped at 2000 characters before the patterns run


def test_a_reference_at_the_start_of_a_very_long_option_is_still_seen() -> None:
    long_tail = " filler" * 2000
    assert reason("Cell balancing", "Pre-charge", "All of the above." + long_tail) == "relative"
    assert reason("Cell balancing", "Pre-charge", "Option C: " + long_tail) == "label"


def test_a_reference_past_the_cap_is_not_looked_for() -> None:
    padding = "Cell balancing " * 200  # 3000 characters
    assert len(padding) > 2000
    check(("Pre-charge", "Isolation monitoring", padding + "and all of the above"), None)
    check(("Pre-charge", "Isolation monitoring", padding + "See above"), None)


def test_the_stem_and_the_solutions_are_capped_too() -> None:
    padding = "The accumulator pack is charged slowly. " * 80  # about 3200 characters
    assert len(padding) > 2000
    assert reason("Foo", "Bar", "Baz", stem="Which of options A-C? " + padding) == "stem"
    assert reason("Foo", "Bar", "Baz", stem=padding + "Which of options A-C?") is None
    assert reason("Foo", "Bar", "Baz", solutions=("The answer is B. " + padding,)) == "solution"
    assert reason("Foo", "Bar", "Baz", solutions=(padding + "The answer is B.",)) is None


def test_long_options_are_still_a_permutation() -> None:
    long = [Choice(i, f"Option text {i} " + "word " * 1000) for i in range(1, 5)]
    got = order(long, KEY, "choice-one")
    assert sorted(got) == [1, 2, 3, 4]


def test_the_new_patterns_are_linear_on_hostile_input() -> None:
    """The cap keeps every pattern on at most 2000 characters; the alarm fails the test instead of hanging it."""
    hostile = [
        "at least " * 100_000,
        "one of the " * 100_000,
        "the two " * 100_000,
        "every one " * 100_000,
        "only one of " * 100_000,
        "more than " * 100_000,
        "see " * 100_000,
        "option " * 100_000,
        "choice " * 100_000,
        "each of them " * 50_000,
    ]

    def runaway(*_: object) -> None:
        raise AssertionError("keep_reason is running away on the added patterns")

    old = signal.signal(signal.SIGALRM, runaway)
    signal.setitimer(signal.ITIMER_REAL, 10)
    try:
        for text in hostile:
            keep_reason(choices(text, "Foo", "Bar"), "choice-one")
            keep_reason(choices("Foo", "Bar", "Baz"), "choice-many", text)
            keep_reason(choices("Foo", "Bar", "Baz"), "choice-one", "", (text,))
            keep_reason(choices(text, text + "x", "Bar"), "choice-one", "Which is labelled?", has_images=True)
            order(choices(text, "Foo", "Bar"), KEY, "choice-one", text, (text,))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


# ---------------------------------------------------------------------------------------------------------------
# Criterion 5: the input is the bank order; the verdict reads that sequence


def test_a_kept_question_returns_exactly_the_input_order_whatever_the_ids() -> None:
    kept = [Choice(9, "All of the above"), Choice(2, "Foo"), Choice(5, "Bar"), Choice(1, "Baz")]
    for rotation in range(4):
        given = kept[rotation:] + kept[:rotation]
        want = reason(*[c.text for c in given])
        if want is not None:
            assert order(given, KEY, "choice-one") == [c.id for c in given]


def test_the_ladder_verdict_reads_the_bank_sequence_not_the_ids() -> None:
    values = ["1 s", "2 s", "5 s", "10 s"]
    sorted_in = [Choice(40 - i, t) for i, t in enumerate(values)]  # ids run the other way
    assert keep_reason(sorted_in, "choice-one") == "ladder-sorted"
    assert order(sorted_in, KEY, "choice-one") == [c.id for c in sorted_in]
    scrambled = [sorted_in[2], sorted_in[0], sorted_in[3], sorted_in[1]]
    assert keep_reason(scrambled, "choice-one") is None
    got = order(scrambled, KEY, "choice-one")
    assert sorted(got) == sorted(c.id for c in sorted_in)


def test_a_shuffled_question_depends_only_on_the_set_of_ids_and_the_key() -> None:
    base = [Choice(11, "Cell balancing"), Choice(12, "Pre-charge"), Choice(13, "Isolation monitoring")]
    want = order(base, KEY, "choice-one")
    for perm in itertools.permutations(base):
        assert order(list(perm), KEY, "choice-one") == want
    words = ["Torque vectoring", "Regenerative braking", "Traction control"]
    other_texts = [Choice(c.id, w) for c, w in zip(base, words, strict=True)]
    assert order(other_texts, KEY, "choice-one") == want


# ---------------------------------------------------------------------------------------------------------------
# One table: the schema, the client and the review screen follow ORDER_REASONS

ROOT = Path(__file__).resolve().parents[2]


def _enum_of(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        if "enum" in node:
            found |= set(node["enum"])
        for v in node.values():
            found |= _enum_of(v)
    elif isinstance(node, list):
        for v in node:
            found |= _enum_of(v)
    return found


def test_the_generated_schema_lists_exactly_the_reason_codes() -> None:
    spec = json.loads((ROOT / "web" / "openapi.json").read_text())
    prop = spec["components"]["schemas"]["ReviewQuestion"]["properties"]["option_order_reason"]
    assert _enum_of(prop) == set(ORDER_REASONS)


def test_the_generated_client_lists_every_reason_code() -> None:
    types = (ROOT / "web" / "src" / "api" / "types.gen.ts").read_text()
    for code in ORDER_REASONS:
        assert f'"{code}"' in types or f"'{code}'" in types, code


def test_the_review_screen_words_every_reason_code() -> None:
    screen = (ROOT / "web" / "src" / "routes" / "Review.tsx").read_text()
    for code in ORDER_REASONS:
        assert re.search(rf"""['"]?{re.escape(code)}['"]?\s*:""", screen), (
            f"no text for {code!r} in Review.tsx"
        )
