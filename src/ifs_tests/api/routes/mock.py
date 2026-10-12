from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path

from ...domain import signals as rules
from ...domain.mock import bar_to_beat
from ...services import hints, mock, questions, signals
from ..deps import AppSettings, Db, Member, Now
from ..present import decoy_shown, feedback, play_question, sent, signals_sent
from ..schemas import HintOut, MockAnswerIn, MockItem, MockQuiz, MockState, MockSummary, TimedQuestion

router = APIRouter(prefix="/api/mock", tags=["mock"])
Id = Annotated[int, Path(ge=1, le=2**31 - 1)]


def _state(db: Db, s: mock.State, now: Now, policy: rules.Policy) -> MockState:
    current = None
    if s.current:
        q, a = s.current
        assert a.deadline_at is not None  # noqa: S101 - every mock attempt gets a deadline
        on_screen = questions.show(db, [q])[0]
        current = TimedQuestion(
            attempt_id=a.id,
            question=play_question(on_screen),
            deadline_at=a.deadline_at,
            server_now=now,
            decoy_option_id=decoy_shown(a, on_screen, policy),
        )
    summary = None
    if s.summary:
        picked = [o for i in s.summary.items for o in i.answer.get("options") or []]
        shown = questions.show(db, [i.question for i in s.summary.items], picked)
        summary = MockSummary(
            correct=s.summary.correct,
            graded=s.summary.graded,
            unreached=s.summary.unreached,
            xp=s.summary.xp,
            lp=s.summary.lp,
            counted=s.summary.counted,
            bar_to_beat=s.summary.bar_to_beat,
            items=[
                MockItem(
                    question=play_question(sh),
                    feedback=feedback(i.checked),
                    answer=sent(i.answer),
                    late=i.late,
                )
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
def start_mock(quiz_id: Id, user: Member, db: Db, now: Now, settings: AppSettings) -> MockState:
    policy = signals.policy(settings, now)
    session = mock.start(db, user, quiz_id, now)
    return _state(db, mock.state(db, user, session.id, now, policy), now, policy)


@router.get("/sessions/{session_id}")
def mock_state(session_id: Id, user: Member, db: Db, now: Now, settings: AppSettings) -> MockState:
    policy = signals.policy(settings, now)
    return _state(db, mock.state(db, user, session_id, now, policy, resumed=True), now, policy)


@router.post("/sessions/{session_id}/answer")
def answer_mock(
    session_id: Id, body: MockAnswerIn, user: Member, db: Db, now: Now, settings: AppSettings
) -> MockState:
    policy = signals.policy(settings, now)
    s = mock.answer(
        db,
        user,
        session_id,
        body.attempt_id,
        body.options,
        body.value,
        now,
        body.unsure,
        signals_sent(body),
        policy,
    )
    return _state(db, s, now, policy)


@router.post("/sessions/{session_id}/end")
def end_mock(session_id: Id, user: Member, db: Db, now: Now) -> MockState:
    """End the run early: the question on screen counts as out of time; the ones not reached aren't scored."""
    return _state(db, mock.end(db, user, session_id, now), now, rules.OFF)


@router.post("/sessions/{session_id}/attempts/{attempt_id}/hint")
def mock_hint(
    session_id: Id, attempt_id: Annotated[int, Path(ge=1, le=2**63 - 1)], user: Member, db: Db, now: Now
) -> HintOut:
    return HintOut.model_validate(hints.timed(db, user, attempt_id, now, session_id))
