"""Hints on demand: one per question, before answering, for the levels that still get them."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DB

from ..db.models import AnswerKey, AnswerOption, Attempt, MockSession, PracticeHint, Question, Setting, User
from ..domain import daily as timing
from ..domain import hints as rules
from ..domain import xp as xp_rules
from .errors import UserError
from .questions import not_running, playable


def _seed(db: DB, question_id: int) -> int:
    """The same seed for a question every time, but not one anyone can recompute: a hint drawn from the public
    question id alone could be run backwards to the answer."""
    db.execute(
        insert(Setting)
        .values(key="hint_salt", value={"salt": secrets.token_hex(32)})
        .on_conflict_do_nothing()
    )
    salt = db.get_one(Setting, "hint_salt").value["salt"]
    digest = hmac.new(bytes.fromhex(salt), str(question_id).encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big")


def _hint(db: DB, user: User, q: Question) -> rules.Hint:
    if not xp_rules.at(xp_rules.level_for(user.xp)).hint:
        raise UserError("Hints end at DT I: from there it's the quiz as it is on the day.", 403)
    key = db.get(AnswerKey, q.id)
    options = list(
        db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == q.id).order_by("position"))
    )
    h = rules.hint(key.effective if key and q.graded else None, options, seed=_seed(db, q.id))
    if h is None:
        raise UserError("There's no hint for this question.", 404)
    return h


def practice(db: DB, user: User, question_id: int, now: datetime) -> rules.Hint:
    not_running(db, user.id, question_id, now)
    h = _hint(db, user, playable(db, question_id))
    db.execute(
        insert(PracticeHint)
        .values(user_id=user.id, question_id=question_id, created_at=now)
        .on_conflict_do_nothing()
    )
    db.commit()
    return h


def spend_practice(db: DB, user_id: int, question_id: int) -> bool:
    """Whether a hint was taken for this answer; it is used up either way."""
    gone = db.execute(
        delete(PracticeHint)
        .where(PracticeHint.user_id == user_id, PracticeHint.question_id == question_id)
        .returning(PracticeHint.user_id)
    ).first()
    return gone is not None


def timed(db: DB, user: User, attempt_id: int, now: datetime, session_id: int | None = None) -> rules.Hint:
    """A hint on a running daily or mock question: recorded on the attempt, which then earns half XP."""
    stmt = select(Attempt).where(Attempt.id == attempt_id, Attempt.user_id == user.id)
    if session_id is not None:
        stmt = stmt.join(MockSession, MockSession.id == Attempt.session_id).where(
            MockSession.id == session_id
        )
    else:
        stmt = stmt.where(Attempt.mode == "daily")
    a = db.scalar(stmt)
    if a is None or a.deadline_at is None:
        raise UserError("That question isn't running.", 404)
    if a.submitted_at is not None or timing.is_late(now, a.deadline_at):
        raise UserError("Hints come before answering.", 409)
    h = _hint(db, user, db.get_one(Question, a.question_id))
    db.execute(update(Attempt).where(Attempt.id == a.id).values(hint_used=True))
    db.commit()
    return h
