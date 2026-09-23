"""Turn service results into response bodies (shared by the practice, daily and mock routes)."""

from __future__ import annotations

from ..services.questions import Checked, Shown
from .schemas import Feedback, Option, PlayQuestion, SolutionOut, media_url


def play_question(shown: Shown) -> PlayQuestion:
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


def feedback(checked: Checked) -> Feedback:
    return Feedback(
        xp=checked.xp,
        level=checked.level,
        correct=checked.correct,
        official=checked.official,
        correct_options=checked.correct_options,
        solutions=[SolutionOut(text=t, images=[media_url(i) for i in imgs]) for t, imgs in checked.solutions],
    )
