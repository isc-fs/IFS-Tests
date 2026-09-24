from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from ...domain.mock import bar_to_beat
from ...services import mock, questions
from ..deps import Db, Member, Now
from ..present import feedback, play_question
from ..schemas import MockAnswerIn, MockItem, MockQuiz, MockState, MockSummary, TimedQuestion

router = APIRouter(prefix="/api/mock", tags=["mock"])
Id = Annotated[int, Path(ge=1, le=2**31 - 1)]


def _state(db: Db, s: mock.State, now: Now) -> MockState:
    current = None
    if s.current:
        q, a = s.current
        assert a.deadline_at is not None  # noqa: S101 - every mock attempt gets a deadline
        current = TimedQuestion(
            attempt_id=a.id,
            question=play_question(questions.show(db, [q])[0]),
            deadline_at=a.deadline_at,
            server_now=now,
        )
    summary = None
    if s.summary:
        shown = questions.show(db, [i.question for i in s.summary.items])
        summary = MockSummary(
            correct=s.summary.correct,
            graded=s.summary.graded,
            xp=s.summary.xp,
            counted=s.summary.counted,
            bar_to_beat=s.summary.bar_to_beat,
            items=[
                MockItem(question=play_question(sh), feedback=feedback(i.checked), late=i.late)
                for sh, i in zip(shown, s.summary.items, strict=True)
            ],
        )
    return MockState(
        session_id=s.session.id,
        quiz_id=s.session.quiz_id,
        label=s.label,
        position=s.session.position,
        total=s.total,
        current=current,
        summary=summary,
    )


@router.get("/quizzes")
def mock_quizzes(user: Member, db: Db) -> list[MockQuiz]:
    return [
        MockQuiz(
            id=i.quiz.id,
            label=i.label,
            year=i.quiz.year,
            vehicle_class=i.quiz.vehicle_class,
            held_on=i.quiz.held_on,
            questions=i.questions,
            graded=i.graded,
            total_time_s=i.total_time_s,
            bar_to_beat=bar_to_beat(i.quiz.last_qualifier),
            best=i.best,
            open_session=i.open_session,
        )
        for i in mock.quizzes(db, user)
    ]


@router.post("/quizzes/{quiz_id}/start")
def start_mock(quiz_id: Id, user: Member, db: Db, now: Now) -> MockState:
    session = mock.start(db, user, quiz_id, now)
    return _state(db, mock.state(db, user, session.id, now), now)


@router.get("/sessions/{session_id}")
def mock_state(session_id: Id, user: Member, db: Db, now: Now) -> MockState:
    return _state(db, mock.state(db, user, session_id, now), now)


@router.post("/sessions/{session_id}/answer")
def answer_mock(session_id: Id, body: MockAnswerIn, user: Member, db: Db, now: Now) -> MockState:
    s = mock.answer(db, user, session_id, body.attempt_id, body.options, body.value, now, body.unsure)
    return _state(db, s, now)
