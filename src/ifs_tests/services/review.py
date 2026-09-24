"""Reviewer tools: queues of questions that need a human, label fixes, exclusions, answer corrections and
players' problem reports. Every change a reviewer makes is audited."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, case, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DB

from ..bank.topics import AREAS as TOPICS_BY_AREA
from ..db.models import (
    AnswerKey,
    AnswerOption,
    Attempt,
    Question,
    Quiz,
    QuizQuestion,
    Report,
    User,
)
from ..domain import keys
from .accounts import audit
from .errors import UserError
from .mock import labels
from .questions import running_for

Queue = Literal["all", "reports", "changed", "unclassified", "ungraded", "excluded"]
PAGE = 30


def _open_reports() -> Any:
    return exists().where(Report.question_id == Question.id, Report.resolved_at.is_(None))


def _queue(stmt: Select[Any], queue: Queue) -> Select[Any]:
    return {
        "all": stmt,
        "reports": stmt.where(_open_reports()),
        "changed": stmt.where(Question.key_changed_at.is_not(None)),
        "unclassified": stmt.where(Question.area == "unclassified", Question.labels_reviewed.is_(False)),
        "ungraded": stmt.where(Question.graded.is_(False), Question.excluded.is_(False)),
        "excluded": stmt.where(Question.excluded),
    }[queue]


def queue_sizes(db: DB) -> dict[str, int]:
    return {
        q: db.scalar(_queue(select(func.count()).select_from(Question), q)) or 0
        for q in ("reports", "changed", "unclassified", "ungraded", "excluded")
    }


@dataclass
class Row:
    question: Question
    reports: int


def search(
    db: DB,
    queue: Queue = "all",
    area: str | None = None,
    topic: str | None = None,
    text: str | None = None,
    offset: int = 0,
) -> tuple[list[Row], int]:
    stmt = _queue(select(Question), queue)
    if area:
        stmt = stmt.where(Question.area == area)
    if topic:
        stmt = stmt.where(Question.topic == topic)
    if text:
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Question.text.ilike(f"%{escaped}%", escape="\\"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    reports = (
        select(func.count())
        .where(Report.question_id == Question.id, Report.resolved_at.is_(None))
        .correlate(Question)
        .scalar_subquery()
    )
    order = (Question.key_changed_at.desc().nulls_last(), Question.id)
    rows = db.execute(stmt.add_columns(reports).order_by(*order).offset(offset).limit(PAGE)).all()
    return [Row(q, n) for q, n in rows], total


@dataclass
class Detail:
    question: Question
    key: AnswerKey | None
    options: list[AnswerOption]
    reports: list[tuple[Report, str | None]]
    answered: int
    right: int
    # The reviewer is playing this question right now (today's daily or an open mock run): answers withheld.
    answer_hidden: bool
    # FS-Quiz's notes on the quizzes it appeared in ("Question 3 was later removed"), each with its quiz.
    quiz_notes: list[str]


def _question(db: DB, question_id: int) -> Question:
    q = db.get(Question, question_id, with_for_update=True)
    if q is None:
        raise UserError("That question doesn't exist.", 404)
    return q


def detail(db: DB, reviewer: User, question_id: int, now: datetime) -> Detail:
    q = db.get(Question, question_id)
    if q is None:
        raise UserError("That question doesn't exist.", 404)
    options = db.scalars(
        select(AnswerOption)
        .where(AnswerOption.question_id == q.id, AnswerOption.retired.is_(False))
        .order_by(AnswerOption.position)
    ).all()
    reports = db.execute(
        select(Report, User.display_name)
        .outerjoin(User, User.id == Report.user_id)
        .where(Report.question_id == q.id, Report.resolved_at.is_(None))
        .order_by(Report.created_at)
    ).all()
    answered, right = db.execute(
        select(func.count(), func.count(case((Attempt.correct.is_(True), 1)))).where(
            Attempt.question_id == q.id, Attempt.submitted_at.is_not(None) | (Attempt.mode == "practice")
        )
    ).one()
    hidden = running_for(db, reviewer.id, q.id, now)
    noted = db.scalars(
        select(Quiz)
        .join(QuizQuestion, QuizQuestion.quiz_id == Quiz.id)
        .where(QuizQuestion.question_id == q.id, Quiz.information.is_not(None))
        .order_by(Quiz.year.desc(), Quiz.id)
    ).all()
    names = labels(db, list(noted))
    notes = [] if hidden else list(dict.fromkeys(f"{names[z.id]}: {z.information}" for z in noted))
    key = db.get(AnswerKey, q.id)
    return Detail(q, key, list(options), [(r, n) for r, n in reports], answered, right, hidden, notes)


def _serve(q: Question) -> None:
    q.playable = not q.images_missing and not q.excluded


def update(db: DB, reviewer: User, question_id: int, changes: dict[str, Any], now: datetime) -> Question:
    """Labels, exclusion and "I've checked the upstream change". Only the fields in `changes` are touched."""
    # null means "leave as is", except for topic and note, where it clears them.
    changes = {k: v for k, v in changes.items() if v is not None or k in ("topic", "exclusion_note")}
    q = _question(db, question_id)
    before = {k: getattr(q, k) for k in ("area", "topic", "labels_reviewed", "excluded", "exclusion_note")}
    if "area" in changes or "topic" in changes:
        area = changes.get("area", q.area)
        allowed = TOPICS_BY_AREA.get(area, [])
        topic = changes.get("topic", q.topic if q.topic in allowed else None)
        if area not in ("mech", "elec", "rules", "unclassified"):
            raise UserError("Pick an area from the list.", fields={"area": "Pick an area from the list."})
        if topic and topic not in allowed:
            raise UserError(
                "That topic isn't part of that area.", fields={"topic": "Pick a topic of this area."}
            )
        q.area, q.topic, q.labels_reviewed = area, topic or None, True
    if "labels_reviewed" in changes:
        q.labels_reviewed = bool(changes["labels_reviewed"])
    if "excluded" in changes:
        q.excluded = bool(changes["excluded"])
        note = (changes.get("exclusion_note") or "").strip()[:200]
        q.exclusion_note = (note or None) if q.excluded else None
    acknowledged = bool(changes.get("acknowledge_change")) and q.key_changed_at is not None
    if acknowledged:
        q.key_changed_at = None
    _serve(q)
    after = {k: getattr(q, k) for k in before}
    diff = {k: [before[k], after[k]] for k in before if before[k] != after[k]}
    if acknowledged:
        diff["upstream_change"] = ["flagged", "checked"]
    if diff:
        q.updated_at = now
        audit(db, reviewer, "question.update", f"question:{q.id}", **diff)
    db.commit()
    return q


def set_answer(
    db: DB, reviewer: User, question_id: int, options: list[int] | None, value: str | None, now: datetime
) -> Question:
    """Replace FS-Quiz's answer with a reviewer's. Choice questions take option IDs; others a typed value
    in the same formats players use (number, list, range or short code)."""
    q = _question(db, question_id)
    key = db.get(AnswerKey, q.id)
    if key is None:
        raise UserError("That question has no answer record.", 409)
    choices = db.scalars(
        select(AnswerOption)
        .where(AnswerOption.question_id == q.id, AnswerOption.retired.is_(False))
        .order_by(AnswerOption.position)
    ).all()
    if q.type in ("single-choice", "multi-choice"):
        if len(choices) < 2:
            raise UserError("A question with a single option can't be graded.", 409)
        picked = [o for o in choices if o.id in set(options or [])]
        if not picked or len(picked) != len(set(options or [])):
            raise UserError(
                "Pick the correct answers from the listed options.", fields={"options": "Pick at least one."}
            )
        if q.type == "single-choice" and len(picked) > 1:
            raise UserError(
                "A single-choice question has one correct answer.", fields={"options": "Pick one."}
            )
        mode = "one" if q.type == "single-choice" else "all"
        override: dict[str, Any] = {"kind": "choice", "mode": mode, "options": [o.id for o in picked]}
        shown = "\n".join(o.text for o in picked)
    else:
        text = (value or "").strip()
        parsed = keys.build_key("input", [{"text": text, "is_correct": True}]) if text else None
        if parsed is None or parsed["kind"] == "self":
            raise UserError(
                "That can't be graded automatically.",
                fields={
                    "value": "Use a number, a range like 11.7-12.1, values separated by ; or a short code."
                },
            )
        override, shown = parsed, keys.clean(text)
        q.answer_kind = override["kind"]
    previous = key.shown
    key.override, key.override_display = override, shown
    q.graded, q.updated_at = True, now
    audit(db, reviewer, "question.answer", f"question:{q.id}", answer=shown, before=previous)
    db.commit()
    return q


def clear_answer(db: DB, reviewer: User, question_id: int, now: datetime) -> Question:
    q = _question(db, question_id)
    key = db.get(AnswerKey, q.id)
    if key is None or key.override is None:
        raise UserError("There is no correction to remove.", 409)
    removed = key.override_display
    key.override = key.override_display = None
    q.answer_kind = keys.answer_kind(q.type, key.key)
    q.graded = key.key is not None and key.key["kind"] != "self"
    q.updated_at = now
    audit(db, reviewer, "question.answer_cleared", f"question:{q.id}", removed=removed)
    db.commit()
    return q


MAX_OPEN_REPORTS = 20


def report(db: DB, user: User, question_id: int, message: str, now: datetime) -> None:
    """A player flags a question. One open report per player and question; a new one replaces the text."""
    text = " ".join(message.split())
    if not 3 <= len(text) <= 500:
        raise UserError("Say briefly what's wrong (up to 500 characters).", fields={"message": "Too short."})
    seen = select(Attempt.id).where(Attempt.user_id == user.id, Attempt.question_id == question_id)
    if not db.scalar(select(exists(seen))):
        # Only questions this player has answered; the same reply as for a missing one reveals nothing.
        raise UserError("That question doesn't exist.", 404)
    open_ = (
        db.scalar(select(func.count()).where(Report.user_id == user.id, Report.resolved_at.is_(None))) or 0
    )
    if open_ >= MAX_OPEN_REPORTS:
        raise UserError(
            "You have many reports waiting for a reviewer. Thanks! Try again once they're handled.", 429
        )
    db.execute(
        insert(Report)
        .values(question_id=question_id, user_id=user.id, message=text, created_at=now)
        .on_conflict_do_update(
            index_elements=["question_id", "user_id"],
            index_where=Report.resolved_at.is_(None),
            set_={"message": text, "created_at": now},
        )
    )
    db.commit()


def resolve(db: DB, reviewer: User, report_id: int, now: datetime) -> None:
    r = db.get(Report, report_id, with_for_update=True)
    if r is None or r.resolved_at is not None:
        raise UserError("That report is already handled.", 404)
    r.resolved_at, r.resolved_by = now, reviewer.id
    audit(db, reviewer, "report.resolve", f"question:{r.question_id}", message=r.message)
    db.commit()
