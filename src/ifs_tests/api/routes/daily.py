from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Path

from ...services import daily, hints, questions
from ..deps import Db, Member, Now
from ..present import feedback, play_question, sent
from ..schemas import AnswerIn, DailyArea, DailyResult, DailyStatus, HintOut, TimedQuestion

router = APIRouter(prefix="/api/daily", tags=["daily"])
Area = Literal["mech", "elec", "rules"]
Id = Annotated[int, Path(ge=1, le=2**63 - 1)]


def _result(db: Db, r: daily.Result) -> DailyResult:
    return DailyResult(
        question=play_question(questions.show(db, [r.question], r.answer.get("options") or [])[0]),
        feedback=feedback(r.checked),
        answer=sent(r.answer),
        late=r.late,
        xp=r.xp,
        lp=r.lp,
        streak=r.streak,
    )


@router.get("")
def daily_status(user: Member, db: Db, now: Now) -> DailyStatus:
    s = daily.status(db, user, now)
    return DailyStatus(
        day=s.day,
        streak=s.streak,
        xp_today=s.xp_today,
        lp_today=s.lp_today,
        areas=[DailyArea.model_validate(asdict(a)) for a in s.areas],
    )


@router.post("/{area}/start")
def start_daily(area: Area, user: Member, db: Db, now: Now) -> TimedQuestion:
    q, attempt = daily.start(db, user, area, now)
    assert attempt.deadline_at is not None  # noqa: S101 - set when a daily attempt is created
    return TimedQuestion(
        attempt_id=attempt.id,
        question=play_question(questions.show(db, [q])[0]),
        deadline_at=attempt.deadline_at,
        server_now=now,
    )


@router.post("/attempts/{attempt_id}/answer")
def answer_daily(attempt_id: Id, body: AnswerIn, user: Member, db: Db, now: Now) -> DailyResult:
    return _result(db, daily.answer(db, user, attempt_id, body.options, body.value, now, body.unsure))


@router.get("/{area}/review")
def review_daily(area: Area, user: Member, db: Db, now: Now) -> DailyResult:
    return _result(db, daily.review(db, user, area, now))


@router.post("/attempts/{attempt_id}/hint")
def daily_hint(attempt_id: Id, user: Member, db: Db, now: Now) -> HintOut:
    return HintOut.model_validate(hints.timed(db, user, attempt_id, now))
