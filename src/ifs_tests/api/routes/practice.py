from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from ...db.models import Question
from ...services import practice, questions
from ..deps import Db, Member, Now
from ..schemas import AnswerIn, AreaProgress, Feedback, Option, PlayQuestion, SolutionOut, media_url

router = APIRouter(prefix="/api/practice", tags=["practice"])
Id = Annotated[int, Path(ge=1, le=2**31 - 1)]
Area = Literal["mech", "elec", "rules", "unclassified"]


def play_question(shown: questions.Shown) -> PlayQuestion:
    q = shown.question
    return PlayQuestion(
        id=q.id,
        text=q.text,
        answer_kind=q.answer_kind,
        graded=q.graded,
        values=shown.values,
        time_s=q.time_s,
        area=q.area,
        topic=q.topic,
        images=[media_url(i) for i in q.images],
        options=[Option.model_validate(o) for o in shown.options],
        quizzes=shown.quizzes,
    )


def feedback(checked: questions.Checked) -> Feedback:
    return Feedback(
        correct=checked.correct,
        official=checked.official,
        correct_options=checked.correct_options,
        solutions=[SolutionOut(text=t, images=[media_url(i) for i in imgs]) for t, imgs in checked.solutions],
    )


def _one(db: Db, q: Question) -> PlayQuestion:
    return play_question(questions.show(db, [q])[0])


@router.get("/areas")
def practice_areas(user: Member, db: Db) -> list[AreaProgress]:
    return [AreaProgress.model_validate(a, from_attributes=True) for a in practice.areas(db, user)]


@router.get("/next")
def next_question(
    user: Member,
    db: Db,
    area: Area | None = None,
    topic: Annotated[str | None, Query(max_length=16, pattern="^[a-z]+$")] = None,
    skip: Annotated[int | None, Query(ge=1, le=2**31 - 1)] = None,
) -> PlayQuestion:
    return _one(db, practice.next_question(db, user, area, topic, skip))


@router.get("/questions/{question_id}")
def practice_question(question_id: Id, _: Member, db: Db) -> PlayQuestion:
    return _one(db, questions.playable(db, question_id))


@router.post("/questions/{question_id}/answer")
def answer_practice(question_id: Id, body: AnswerIn, user: Member, db: Db, now: Now) -> Feedback:
    return feedback(practice.answer(db, user, question_id, body.options, body.value, now))
