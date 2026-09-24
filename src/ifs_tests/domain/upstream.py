"""FS-Quiz's own notes that a question was removed from its quiz after it was held (a wrong answer, a bad
wording). A quiz's `information` says it by position ("Questions 3, 5 and 12 were later removed"); some
solutions say it of their own question ("Question has been removed from the quiz"). Only those phrasings
count: a solution that says "the aero package was removed" is about something else."""

from __future__ import annotations

import re
from typing import Any

_REMOVED = r"(?:has|have|was|were)\s+(?:been\s+)?(?:later\s+)?(?:removed|deleted)\b[^.\n]*"
_IN_QUIZ = re.compile(rf"\bquestions?\s+(\d+(?:\s*(?:,|and|&)\s*\d+)*)\s+{_REMOVED}", re.IGNORECASE)
_IN_SOLUTION = re.compile(rf"\bquestion(?:\s+\d+)?\s+{_REMOVED}", re.IGNORECASE)


def removed_positions(information: str | None) -> dict[int, str]:
    """Positions (as FS-Quiz numbers them, from 1) a quiz note says were removed -> the sentence saying so."""
    found: dict[int, str] = {}
    for m in _IN_QUIZ.finditer(information or ""):
        for n in re.findall(r"\d+", m.group(1)):
            found.setdefault(int(n), m.group(0).strip())
    return found


def says_removed(solution: str | None) -> str | None:
    m = _IN_SOLUTION.search(solution or "")
    return m.group(0).strip() if m else None


def notes(bank: dict[str, Any]) -> dict[int, str]:
    """FS-Quiz question ID -> why FS-Quiz says it was removed, for a normalised bank."""
    at = {
        (place["quiz_id"], place["position"]): q["question_id"]
        for q in bank["questions"]
        for place in q["quizzes"]
    }
    found: dict[int, str] = {}
    for quiz in bank["quizzes"]:
        for position, why in removed_positions(quiz.get("information")).items():
            question = at.get((quiz["quiz_id"], position))
            if question is not None:
                found.setdefault(question, f"FS-Quiz: {why}")
    for q in bank["questions"]:
        for s in q["solutions"]:
            said = says_removed(s["text"])
            if said:
                found.setdefault(q["question_id"], f"FS-Quiz's solution: {said}")
    return found
