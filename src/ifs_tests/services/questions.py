"""Questions as players see them, and checking an answer. Shared by practice, daily and mock modes."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from ..db.models import AnswerKey, AnswerOption, Event, Question, Quiz, QuizQuestion, Solution, quiz_events
from ..domain.grading import grade
from .errors import UserError

MAX_QUIZ_LABELS = 4


@dataclass
class Shown:
    question: Question
    options: list[AnswerOption]
    quizzes: list[str]
    values: int | None


@dataclass
class Checked:
    correct: bool | None
    official: str | None
    correct_options: list[int]
    solutions: list[tuple[str | None, list[str]]]


def _quiz_labels(db: DB, ids: list[int]) -> dict[int, list[str]]:
    rows = db.execute(
        select(QuizQuestion.question_id, Event.short_name, Quiz.year, Quiz.vehicle_class)
        .join(Quiz, Quiz.id == QuizQuestion.quiz_id)
        .join(quiz_events, quiz_events.c.quiz_id == Quiz.id)
        .join(Event, Event.id == quiz_events.c.event_id)
        .where(QuizQuestion.question_id.in_(ids))
        .order_by(Quiz.year.desc(), Event.short_name)
    )
    labels: dict[int, list[str]] = defaultdict(list)
    for qid, event, year, vehicle in rows:
        label = f"{event} {year} {vehicle.upper()}"
        if label not in labels[qid] and len(labels[qid]) < MAX_QUIZ_LABELS:
            labels[qid].append(label)
    return labels


def _value_count(key: dict[str, Any] | None) -> int | None:
    """How many values a "numbers" answer needs, when every accepted answer agrees."""
    if not key or key["kind"] != "numbers":
        return None
    counts = {len(a["values"]) for a in key["accept"]}
    return counts.pop() if len(counts) == 1 else None


def show(db: DB, questions: list[Question]) -> list[Shown]:
    ids = [q.id for q in questions]
    options: dict[int, list[AnswerOption]] = defaultdict(list)
    for o in db.scalars(
        select(AnswerOption).where(AnswerOption.question_id.in_(ids)).order_by(AnswerOption.position)
    ):
        options[o.question_id].append(o)
    rows = db.execute(select(AnswerKey.question_id, AnswerKey.key).where(AnswerKey.question_id.in_(ids)))
    keys = {qid: key for qid, key in rows}
    labels = _quiz_labels(db, ids)
    return [Shown(q, options[q.id], labels[q.id], _value_count(keys.get(q.id))) for q in questions]


def playable(db: DB, question_id: int) -> Question:
    q = db.get(Question, question_id)
    if q is None or not q.playable:
        raise UserError("That question doesn't exist.", 404)
    return q


def check(db: DB, q: Question, options: list[int] | None, value: str | None) -> Checked:
    """Grade an answer and return everything needed to explain it. Never call before the player answered."""
    choices = db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == q.id)).all()
    if options and not set(options) <= set(choices):
        raise UserError("Pick one of the listed answers.")
    key = db.get(AnswerKey, q.id)
    k = key.key if key else None
    correct = grade(k, options=options, value=value) if q.graded else None
    solutions = db.scalars(select(Solution).where(Solution.question_id == q.id).order_by(Solution.id)).all()
    return Checked(
        correct=correct,
        official=key.display if key else None,
        correct_options=list(k["options"]) if k and k["kind"] == "choice" else [],
        solutions=[(s.text, list(s.images)) for s in solutions],
    )
