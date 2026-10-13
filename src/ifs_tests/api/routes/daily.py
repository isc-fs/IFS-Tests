from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from ...services import daily, hints, questions, signals
from ..deps import AppSettings, Db, Member, Now
from ..present import decoy_shown, feedback, play_question, sent, signals_sent
from ..schemas import (
    DailyArea,
    DailyResult,
    DailyRevealed,
    DailyStatus,
    HintOut,
    TimedAnswerIn,
    TimedQuestion,
)

router = APIRouter(prefix="/api/daily", tags=["daily"])
Area = Literal["mech", "elec", "rules"]
Id = Annotated[int, Path(ge=1, le=2**63 - 1)]


def _result(db: Db, r: daily.Result, settings: AppSettings) -> DailyResult:
    key = hints.order_key(db, r.attempt_id, r.day, settings.rules_1b_from)
    return DailyResult(
        day=r.day,
        question=play_question(
            questions.show(db, [r.question], r.answer.get("options") or [], order_key=key)[0]
        ),
        feedback=None if r.pending else feedback(r.checked),
        released_at=r.released_at,
        answer=sent(r.answer),
        late=r.late,
        xp=r.xp,
        lp=r.lp,
        streak=r.streak,
    )


@router.get("")
def daily_status(user: Member, db: Db, now: Now, settings: AppSettings) -> DailyStatus:
    s = daily.status(db, user, now, rules_from=settings.rules_1b_from)
    return DailyStatus(
        day=s.day,
        streak=s.streak,
        xp_today=s.xp_today,
        lp_today=s.lp_today,
        areas=[DailyArea.model_validate(asdict(a)) for a in s.areas],
        revealed=[DailyRevealed.model_validate(asdict(x)) for x in s.revealed],
    )


@router.post("/{area}/start")
def start_daily(area: Area, user: Member, db: Db, now: Now, settings: AppSettings) -> TimedQuestion:
    policy = signals.policy(settings, now)
    q, attempt = daily.start(db, user, area, now, policy, rules_from=settings.rules_1b_from)
    assert attempt.deadline_at is not None  # noqa: S101 - set when a daily attempt is created
    assert attempt.day is not None  # noqa: S101 - set when a daily attempt is created
    key = hints.order_key(db, attempt.id, attempt.day, settings.rules_1b_from)
    shown = questions.show(db, [q], order_key=key)[0]
    keep = signals.keeps(attempt, policy)
    return TimedQuestion(
        attempt_id=attempt.id,
        question=play_question(shown),
        deadline_at=attempt.deadline_at,
        server_now=now,
        decoy_option_id=decoy_shown(attempt, shown, policy) if keep else None,
        collect_signals=keep,
        result_at=attempt.released_at if attempt.released_at and attempt.released_at > now else None,
    )


@router.post("/attempts/{attempt_id}/answer")
def answer_daily(
    attempt_id: Id, body: TimedAnswerIn, user: Member, db: Db, now: Now, settings: AppSettings
) -> DailyResult:
    r = daily.answer(
        db,
        user,
        attempt_id,
        body.options,
        body.value,
        now,
        body.unsure,
        signals_sent(body),
        signals.policy(settings, now),
    )
    return _result(db, r, settings)


@router.get("/{area}/review")
def review_daily(
    area: Area,
    user: Member,
    db: Db,
    now: Now,
    settings: AppSettings,
    day: Annotated[date | None, Query()] = None,
) -> DailyResult:
    return _result(db, daily.review(db, user, area, now, day), settings)


@router.post("/attempts/{attempt_id}/hint")
def daily_hint(attempt_id: Id, user: Member, db: Db, now: Now) -> HintOut:
    return HintOut.model_validate(hints.timed(db, user, attempt_id, now))
