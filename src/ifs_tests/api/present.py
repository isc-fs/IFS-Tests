"""Turn service results into response bodies (shared by the practice, daily and mock routes)."""

from __future__ import annotations

from typing import Any

from ..bank.client import DOC_URL
from ..services.questions import Checked, Doc, Shown
from .schemas import DocLink, Feedback, KeyIn, Option, PlayQuestion, QuestionDocs, SolutionOut, media_url


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
        documents=QuestionDocs(
            year=shown.documents.year,
            used=[_link(d) for d in shown.documents.used],
            newer=[_link(d) for d in shown.documents.newer],
        ),
    )


def _link(d: Doc) -> DocLink:
    url = d.path if "://" in d.path else f"{DOC_URL}/{d.path}"
    return DocLink(title=d.title, type=d.type, year=d.year, url=url)


def sent(answer: dict[str, Any] | None) -> KeyIn | None:
    """The player's own answer as they sent it; none for a question left to run out or passed."""
    if not answer or (answer.get("options") is None and answer.get("value") is None):
        return None
    return KeyIn(options=answer.get("options"), value=answer.get("value"))


def feedback(checked: Checked) -> Feedback:
    s = checked.score
    return Feedback(
        xp=s.xp if s else 0,
        lp=s.lp if s else 0,
        bonuses=s.bonuses if s else {},
        combo=s.combo if s else 0,
        comeback=bool(s and s.comeback),
        cushioned=bool(s and s.cushioned),
        promoted=bool(s and s.promoted),
        rose=bool(s and s.rose),
        demoted=bool(s and s.demoted),
        rank_points=s.points if s and s.level else None,
        level=s.level if s and s.level else None,
        level_up=bool(s and s.level_up),
        passed=checked.passed,
        correct=checked.correct,
        official=checked.official,
        correct_options=checked.correct_options,
        solutions=[SolutionOut(text=t, images=[media_url(i) for i in imgs]) for t, imgs in checked.solutions],
    )
