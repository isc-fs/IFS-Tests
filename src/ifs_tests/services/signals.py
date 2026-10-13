"""Ranked-play signals: the policy for a request, the canary draw, the retention purge. This module never
imports the key model: the decoy is drawn from the options table alone (tests/api/test_signals.py guards it)."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, and_, or_, select, update
from sqlalchemy.orm import Session as DB

from ..db.models import AnswerOption, Attempt, MockSession, Question
from ..domain import signals as rules
from ..domain.daily import madrid_day, per_player
from ..settings import Settings
from . import xp


def policy(settings: Settings, now: datetime) -> rules.Policy:
    collect = per_player(madrid_day(now), settings.rules_1b_from)
    return rules.Policy(collect=collect, canary=collect and settings.canary)


def decoy_for(
    db: DB,
    q: Question,
    policy: rules.Policy,
    choice: Callable[[Sequence[int]], int] = secrets.choice,
) -> int | None:
    """One of the options as questions.show offers them (not retired, by position then id)."""
    if not policy.canary:
        return None
    ids = db.scalars(
        select(AnswerOption.id)
        .where(AnswerOption.question_id == q.id, AnswerOption.retired.is_(False))
        .order_by(AnswerOption.position, AnswerOption.id)
    ).all()
    return rules.decoy(q.answer_kind, ids, choice)


def _old(kept: int) -> ColumnElement[bool]:
    """Attempts whose season ended over 90 days ago."""
    return or_(
        and_(Attempt.mode == "daily", Attempt.day < date(kept, 9, 1)),
        Attempt.session_id.in_(select(MockSession.id).where(MockSession.season < kept)),
    )


def purge(db: DB, now: datetime) -> int:
    """Nightly: forget the signals of attempts whose season ended over 90 days ago (ADR 0006 retention).
    One player per transaction, player lock first: the order deleting an account takes."""
    old = and_(_old(rules.kept_from(now)), Attempt.resumes.is_not(None))
    users = db.scalars(select(Attempt.user_id).where(old).distinct().order_by(Attempt.user_id)).all()
    n = 0
    for uid in users:
        xp.lock(db, uid)
        result = db.execute(
            update(Attempt).where(Attempt.user_id == uid, old).values(**dict.fromkeys(rules.COLUMNS))
        )
        n += cast(CursorResult[Any], result).rowcount
        db.commit()
    return n
