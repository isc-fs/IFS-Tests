"""The mirror builds the bank from what FS-Quiz publishes now, not from everything it ever cached."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from ifs_tests.bank.client import FSQuiz
from ifs_tests.bank.mirror import mirror


def question(qid: int) -> dict[str, Any]:
    return {
        "question_id": qid,
        "type": "input",
        "text": f"Question {qid}",
        "time": 60,
        "position_index": 1,
        "answers": [{"answer_id": qid, "answer_text": "1", "is_correct": True}],
        "images": [],
        "solution": [],
    }


def quiz(qid: int) -> dict[str, Any]:
    return {
        "quiz_id": qid,
        "year": 2025,
        "class": "ev",
        "date": None,
        "status": "done",
        "event": [{"event_id": 1}],
        "questions": [question(qid * 10)],
    }


def fake_fsquiz(listed: list[int], gone: set[int], index: list[int]) -> FSQuiz:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/2")
        if path == "/event/all":
            quizzes = [{"quiz_id": i} for i in listed]
            return httpx.Response(
                200, json={"events": [{"event_id": 1, "short_name": "FSX", "quizzes": quizzes}]}
            )
        kind, _, number = path.strip("/").partition("/")
        if number:
            if int(number) in gone:
                return httpx.Response(404, json={"status": {"code": 404}})
            return httpx.Response(200, json=quiz(int(number)) if kind == "quiz" else question(int(number)))
        start = int(req.url.params.get("start_id", 1))
        if kind == "question":
            rows = [{"question_id": i} for i in index][start - 1 : start + 24]
            return httpx.Response(200, json={"questions": rows})
        return httpx.Response(200, json={"documents": [], "last-qualifier": []})

    return FSQuiz(delay=0, transport=httpx.MockTransport(handler))


def cache(data: Path, quizzes: list[int], questions: list[int]) -> None:
    raw = data / "raw"
    for folder, ids, body in (("quiz", quizzes, quiz), ("question", questions, question)):
        (raw / folder).mkdir(parents=True, exist_ok=True)
        for i in ids:
            (raw / folder / f"{i}.json").write_text(json.dumps(body(i)))
    (raw / "documents.json").write_text("[]")
    (raw / "last_qualifiers.json").write_text("[]")


def test_quizzes_fsquiz_no_longer_lists_or_serves_leave_the_bank(tmp_path: Path) -> None:
    cache(tmp_path, [1, 2, 3], [])
    bank = mirror(fake_fsquiz(listed=[1, 2], gone={2}, index=[]), tmp_path, refresh=True, log=lambda *_: None)
    assert [q["quiz_id"] for q in bank["quizzes"]] == [1]
    assert [q["question_id"] for q in bank["questions"]] == [10]
    assert not (tmp_path / "raw" / "quiz" / "2.json").exists()


def test_questions_gone_from_the_index_leave_the_bank(tmp_path: Path) -> None:
    cache(tmp_path, [1], [11, 12])
    api = fake_fsquiz(listed=[1], gone={13}, index=[10, 11, 13])
    bank = mirror(api, tmp_path, question_index=True, log=lambda *_: None)
    assert [q["question_id"] for q in bank["questions"]] == [10, 11]
    bank = mirror(fake_fsquiz(listed=[1], gone=set(), index=[]), tmp_path, log=lambda *_: None)
    assert [q["question_id"] for q in bank["questions"]] == [10, 11]
