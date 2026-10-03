from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from ...db.models import Question
from ...services import hints, practice, questions
from ..deps import Db, Member, Now
from ..present import feedback, play_question
from ..schemas import AnswerIn, AreaProgress, Feedback, HintOut, PlayQuestion

router = APIRouter(prefix="/api/practice", tags=["practice"])
Id = Annotated[int, Path(ge=1, le=2**31 - 1)]
Area = Literal["mech", "elec", "rules", "unclassified"]


def _one(db: Db, q: Question) -> PlayQuestion:
    return play_question(questions.show(db, [q])[0])


@router.get("/areas")
def practice_areas(user: Member, db: Db) -> list[AreaProgress]:
    return [AreaProgress.model_validate(a, from_attributes=True) for a in practice.areas(db, user)]


@router.get("/next")
def next_question(
    user: Member,
    db: Db,
    now: Now,
    area: Area | None = None,
    topic: Annotated[str | None, Query(max_length=16, pattern="^[a-z]+$")] = None,
    skip: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
) -> PlayQuestion:
    return _one(db, practice.next_question(db, user, now, area, topic, skip))


@router.get("/questions/{question_id}")
def practice_question(question_id: Id, user: Member, db: Db, now: Now) -> PlayQuestion:
    return _one(db, practice.question(db, user, question_id, now))


@router.post("/questions/{question_id}/answer")
def answer_practice(question_id: Id, body: AnswerIn, user: Member, db: Db, now: Now) -> Feedback:
    return feedback(practice.answer(db, user, question_id, body.options, body.value, now, body.unsure))


@router.post("/questions/{question_id}/hint")
def practice_hint(question_id: Id, user: Member, db: Db, now: Now) -> HintOut:
    return HintOut.model_validate(hints.practice(db, user, question_id, now))
