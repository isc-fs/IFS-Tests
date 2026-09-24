from __future__ import annotations

from typing import Any

import pytest

from ifs_tests.domain.upstream import notes, removed_positions, says_removed


# Real quiz notes from FS-Quiz (September 2026).
@pytest.mark.parametrize(
    ("information", "positions"),
    [
        ("Question 15 was later deleted because no answer was correct", [15]),
        ("Question 10 was later removed", [10]),
        ("Questions 1, 6, 8 have been removed after the quiz", [1, 6, 8]),
        ("Question 4 was later removed due to the wording", [4]),
        ("Question 1 has been removed from the quiz due to contradictory information", [1]),
        ("Retake.\n\nQuestions 3, 5 and 12 were later removed", [3, 5, 12]),
        ("Question 3, 4 and 11 has been removed from the quiz", [3, 4, 11]),
        ("Retake of the quiz from January 31, 2025. The first quiz had technical issues.", []),
        ("This quiz required an upload in the 2 and 4 question.", []),
        ("In this quiz, commas are used instead of dots for decimal places.", []),
        ("Testquiz", []),
        (None, []),
    ],
)
def test_removed_positions(information: str | None, positions: list[int]) -> None:
    assert sorted(removed_positions(information)) == positions


@pytest.mark.parametrize(
    ("solution", "removed"),
    [
        ("This question was later deleted because no answer was correct", True),
        ("Question 3 was later deleted because wording \n\nFront wheel rate = ...", True),
        ("... less than 10 s at 30 A. Therefore, question has been removed from the quiz.", True),
        ("Question was removed", True),
        ("This Question has been removed from the quiz", True),
        ("For 2025, it has been removed (refer to the respective changelog entry).", False),
        ("Your aero team decides to remove the aero package that weighs 20 kg", False),
        ("A is wrong, there is no rule that states this.", False),
        (None, False),
    ],
)
def test_says_removed(solution: str | None, removed: bool) -> None:
    assert (says_removed(solution) is not None) is removed


def question(qid: int, *places: tuple[int, int], solution: str | None = None) -> dict[str, Any]:
    return {
        "question_id": qid,
        "quizzes": [{"quiz_id": z, "position": p} for z, p in places],
        "solutions": [{"text": solution}] if solution else [],
    }


def test_notes_map_positions_to_each_quizs_own_question() -> None:
    bank = {
        "quizzes": [
            {"quiz_id": 76, "information": "Question 2 was later deleted because the answer was wrong"},
            {"quiz_id": 81, "information": "Question 2 was later deleted because the answer was wrong"},
            {"quiz_id": 90, "information": None},
        ],
        "questions": [
            question(723, (76, 1), (81, 2)),
            question(724, (76, 2), (81, 1)),
            question(800, (90, 1), solution="Question has been removed from the quiz"),
            question(801, (90, 2)),
        ],
    }
    assert notes(bank) == {
        723: "FS-Quiz: Question 2 was later deleted because the answer was wrong",
        724: "FS-Quiz: Question 2 was later deleted because the answer was wrong",
        800: "FS-Quiz's solution: Question has been removed from the quiz",
    }
