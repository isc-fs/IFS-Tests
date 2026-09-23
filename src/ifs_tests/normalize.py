"""Turn raw FS-Quiz responses into one consistent, de-duplicated bank.

Live responses differ from the OpenAPI spec (see docs/fsquiz-api.md):
IDs and years sometimes come as strings, questions carry `solution`
instead of `solutions`, events use `event_id` or `id` depending on the
endpoint, some texts hold a literal backslash-n instead of a newline,
and `time: 0` means "not recorded".
"""
from __future__ import annotations

import re

LICENSE = "ODbL-1.0"
SOURCE = "FS-Quiz (https://fs-quiz.eu), by Yannik Ottens, via API v2"


def _int(v):
    return int(v) if v not in (None, "") else None


def clean_text(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    return s.replace("\xa0", " ").strip()


def event(e: dict) -> dict:
    return {
        "event_id": _int(e.get("event_id", e.get("id"))),
        "short_name": e["short_name"],
        "name": e.get("event_name"),
        "country": e.get("country"),
        "website": e.get("website"),
    }


def solution(s: dict) -> dict:
    return {
        "solution_id": _int(s["solution_id"]),
        "text": clean_text(s.get("text")),
        "images": [i["path"] for i in s.get("images") or []],
    }


def question(q: dict) -> dict:
    answers = [
        {"answer_id": _int(a["answer_id"]), "text": clean_text(a["answer_text"]), "is_correct": bool(a["is_correct"])}
        for a in q.get("answers") or []
    ]
    return {
        "question_id": _int(q["question_id"]),
        "type": q["type"],
        "text": clean_text(q["text"]),
        "time": _int(q.get("time")) or None,
        "answers": answers,
        "images": [i["path"] for i in q.get("images") or []],
        "solutions": [solution(s) for s in q.get("solutions") or q.get("solution") or []],
    }


_RANGE = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*-\s*(-?\d+(?:[.,]\d+)?)\s*$")


def parse_range(text: str) -> tuple[float, float] | None:
    """'11.7-12.1' -> (11.7, 12.1); also handles negative bounds ('-3--1')."""
    m = _RANGE.match(text or "")
    if not m:
        return None
    lo, hi = (float(x.replace(",", ".")) for x in m.groups())
    return (min(lo, hi), max(lo, hi))


def document(d: dict) -> dict:
    return {
        "doc_id": _int(d["doc_id"]),
        "type": d["type"],
        "year": _int(d.get("year")),
        "version": d.get("version"),
        "path": d["path"],
        "event_ids": sorted({_int(e.get("id", e.get("event_id"))) for e in d.get("event") or []}),
    }


def build_bank(events, quizzes, orphans, documents, last_qualifiers) -> dict:
    lq_by_quiz = {_int(lq["quiz_id"]): lq for lq in last_qualifiers}
    questions: dict[int, dict] = {}
    quiz_rows = []

    for quiz in sorted(quizzes, key=lambda q: _int(q["quiz_id"])):
        qid = _int(quiz["quiz_id"])
        ordered = sorted(quiz.get("questions") or [], key=lambda q: _int(q.get("position_index")) or 0)
        for raw in ordered:
            q = questions.setdefault(_int(raw["question_id"]), question(raw) | {"quizzes": []})
            q["quizzes"].append({"quiz_id": qid, "position": _int(raw.get("position_index"))})
        lq = quiz.get("last_qualifier") or lq_by_quiz.get(qid)
        quiz_rows.append({
            "quiz_id": qid,
            "year": _int(quiz["year"]),
            "class": quiz["class"],
            "date": quiz.get("date"),
            "status": quiz["status"],
            "information": clean_text(quiz.get("information")) or None,
            "event_ids": sorted({_int(e.get("event_id", e.get("id"))) for e in quiz.get("event") or []}),
            "question_ids": [_int(q["question_id"]) for q in ordered],
            "document_ids": [_int(d["doc_id"]) for d in quiz.get("documents") or []],
            "last_qualifier": {
                "method": lq["method"],
                "time_s": _int(lq.get("time")),
                "score": _int(lq.get("score")),
                "correct_answers": _int(lq.get("correct_answers")),
            } if lq else None,
        })

    for raw in orphans:
        questions.setdefault(_int(raw["question_id"]), question(raw) | {"quizzes": []})

    return {
        "source": SOURCE,
        "license": LICENSE,
        "events": sorted((event(e) for e in events), key=lambda e: e["event_id"]),
        "quizzes": quiz_rows,
        "questions": [questions[k] for k in sorted(questions)],
        "documents": sorted((document(d) for d in documents), key=lambda d: d["doc_id"]),
    }
