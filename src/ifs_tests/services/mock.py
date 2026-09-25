"""Mock quiz: replay a past quiz one question at a time, each on its real clock, results at the end.
A question's clock starts when it is shown; one left to run out while away is closed as late. A run can be
ended early: the question on screen is charged as out of time, the ones not reached aren't scored."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DB

from ..db.models import Attempt, Event, MockSession, Question, Quiz, QuizQuestion, User, quiz_events
from ..domain import daily as timing
from ..domain import mock as rules
from . import xp
from .errors import UserError
from .questions import Checked, check, explain, running


def labels(db: DB, quizzes: list[Quiz]) -> dict[int, str]:
    """ "FSG/FSA 2025 CV" for each quiz, in one query."""
    events: dict[int, list[str]] = {q.id: [] for q in quizzes}
    for quiz_id, name in db.execute(
        select(quiz_events.c.quiz_id, Event.short_name)
        .join(Event, Event.id == quiz_events.c.event_id)
        .where(quiz_events.c.quiz_id.in_(list(events)))
        .order_by(Event.short_name)
    ):
        events[quiz_id].append(name)
    return {q.id: f"{'/'.join(events[q.id]) or 'Quiz'} {q.year} {q.vehicle_class.upper()}" for q in quizzes}


def label(db: DB, quiz: Quiz) -> str:
    return labels(db, [quiz])[quiz.id]


def _questions(db: DB, quiz_id: int) -> list[Question]:
    return list(
        db.scalars(
            select(Question)
            .join(QuizQuestion, QuizQuestion.question_id == Question.id)
            .where(QuizQuestion.quiz_id == quiz_id, Question.playable)
            .order_by(QuizQuestion.position)
        )
    )


@dataclass
class QuizInfo:
    quiz: Quiz
    label: str
    questions: int
    graded: int
    total_time_s: int | None
    best: int | None
    open_session: int | None


def quizzes(db: DB, user: User) -> list[QuizInfo]:
    stats: dict[int, tuple[int, int, int]] = {}
    for quiz_id, graded, time_s, kind in db.execute(
        select(QuizQuestion.quiz_id, Question.graded, Question.time_s, Question.answer_kind)
        .join(Question, Question.id == QuizQuestion.question_id)
        .where(Question.playable)
    ):
        n, g, total = stats.get(quiz_id, (0, 0, 0))
        stats[quiz_id] = (n + 1, g + graded, total + rules.budget(time_s, kind))
    right = (
        select(Attempt.session_id, func.count().label("n"))
        .where(Attempt.correct.is_(True), Attempt.late.is_not(True), Attempt.session_id.is_not(None))
        .group_by(Attempt.session_id)
        .subquery()
    )
    finished = db.execute(
        select(MockSession.quiz_id, func.max(func.coalesce(right.c.n, 0)))
        .outerjoin(right, right.c.session_id == MockSession.id)
        .where(MockSession.user_id == user.id, MockSession.finished_at.is_not(None))
        .group_by(MockSession.quiz_id)
    )
    best: dict[int, int] = {qid: n for qid, n in finished}
    running = db.execute(
        select(MockSession.quiz_id, MockSession.id).where(
            MockSession.user_id == user.id, MockSession.finished_at.is_(None)
        )
    )
    open_: dict[int, int] = {qid: sid for qid, sid in running}
    rows = db.scalars(
        select(Quiz)
        .where(Quiz.retired.is_(False))
        .order_by(Quiz.held_on.desc().nulls_last(), Quiz.year.desc(), Quiz.id)
    ).all()
    names = labels(db, [q for q in rows if q.id in stats])
    out = []
    for quiz in rows:
        if quiz.id not in stats:
            continue
        n, graded, total = stats[quiz.id]
        out.append(
            QuizInfo(
                quiz=quiz,
                label=names[quiz.id],
                questions=n,
                graded=graded,
                total_time_s=total,
                best=best.get(quiz.id),
                open_session=open_.get(quiz.id),
            )
        )
    return out


def start(db: DB, user: User, quiz_id: int, now: datetime) -> MockSession:
    """Start a run, or return the one already open for this quiz."""
    quiz = db.get(Quiz, quiz_id)
    if quiz is None or quiz.retired or not _questions(db, quiz_id):
        raise UserError("That quiz isn't available.", 404)
    season = rules.season(timing.madrid_day(now))
    played = db.scalar(
        select(func.count()).where(
            MockSession.user_id == user.id, MockSession.quiz_id == quiz_id, MockSession.season == season
        )
    )
    db.execute(
        insert(MockSession)
        .values(user_id=user.id, quiz_id=quiz_id, season=season, counted=not played, started_at=now)
        .on_conflict_do_nothing(
            index_elements=["user_id", "quiz_id"], index_where=MockSession.finished_at.is_(None)
        )
    )
    db.commit()
    return db.scalars(
        select(MockSession).where(
            MockSession.user_id == user.id, MockSession.quiz_id == quiz_id, MockSession.finished_at.is_(None)
        )
    ).one()


def _session(db: DB, user: User, session_id: int) -> MockSession:
    xp.lock(db, user.id)  # the player, then the run: the order deleting an account takes
    s = db.scalar(
        select(MockSession)
        .where(MockSession.id == session_id, MockSession.user_id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if s is None:
        raise UserError("That quiz run doesn't exist.", 404)
    return s


@dataclass
class Item:
    question: Question
    checked: Checked
    late: bool
    answer: dict[str, Any]


@dataclass
class Summary:
    correct: int
    graded: int  # the questions not reached count, as in the real quiz
    unreached: int
    xp: int
    lp: float
    counted: bool
    bar_to_beat: str | None
    items: list[Item]


@dataclass
class State:
    session: MockSession
    label: str
    total: int
    current: tuple[Question, Attempt] | None
    summary: Summary | None


def _attempts(db: DB, s: MockSession) -> dict[int, Attempt]:
    rows = db.scalars(
        select(Attempt).where(Attempt.session_id == s.id).execution_options(populate_existing=True)
    )
    return {a.question_id: a for a in rows}


def _run(db: DB, s: MockSession, attempts: dict[int, Attempt]) -> list[Question]:
    """The run's questions in quiz order: every question it has already shown, plus the still-playable ones
    (only while running). Tracking by question, not by position, keeps a run intact when a question is
    hidden or its images arrive mid-run."""
    everything = db.scalars(
        select(Question)
        .join(QuizQuestion, QuizQuestion.question_id == Question.id)
        .where(QuizQuestion.quiz_id == s.quiz_id)
        .order_by(QuizQuestion.position)
    )
    return [q for q in everything if q.id in attempts or (q.playable and s.finished_at is None)]


def _advance(db: DB, s: MockSession, now: datetime) -> tuple[Question, Attempt] | None:
    """The question to show now: start its clock, or close it if its time ran out while away."""
    attempts = _attempts(db, s)
    current = None
    for q in _run(db, s, attempts):
        a = attempts.get(q.id)
        if a is None:
            a = Attempt(
                user_id=s.user_id,
                question_id=q.id,
                mode="mock",
                answer={},
                created_at=now,
                session_id=s.id,
                area=q.area,
                deadline_at=now + timedelta(seconds=rules.budget(q.time_s, q.answer_kind)),
            )
            db.add(a)
            db.flush()
            current = q, a
            break
        if a.submitted_at is None and a.deadline_at and not timing.is_late(now, a.deadline_at):
            current = q, a
            break
        if a.submitted_at is None:
            _time_out(db, s, q, a, now)
    s.position = sum(1 for a in attempts.values() if a.submitted_at)
    if current is None:
        s.finished_at = s.finished_at or now
    return current


def _time_out(db: DB, s: MockSession, q: Question, a: Attempt, now: datetime) -> None:
    """A question left to run out: closed as late and wrong, like an answer sent after the time."""
    a.submitted_at, a.late, a.correct = now, True, False if q.graded else None
    repeat = xp.last_seen(db, s.user_id, q.id, s.started_at, other_than=a.id) is not None
    timed_out = xp.grant(
        db,
        s.user_id,
        q,
        "mock",
        a.correct,
        now,
        answered=False,
        repeat=repeat,
        late=True,
        again_today=xp.answered_today(db, s.user_id, q.id, now, other_than=a.id),
        ranked=s.counted,
        season_at=s.started_at,
    )
    a.xp, a.lp = timed_out.xp, timed_out.lp


def close_expired(db: DB, now: datetime) -> int:
    """Nightly: charge questions left to run out in runs nobody came back to. The run itself stays open; the
    next question starts its clock when its player returns."""
    rows = db.execute(
        select(Attempt.id, Attempt.session_id, Attempt.user_id)
        .where(
            Attempt.mode == "mock",
            Attempt.submitted_at.is_(None),
            Attempt.deadline_at < now - timing.GRACE,
        )
        .order_by(Attempt.user_id, Attempt.id)
    ).all()
    closed = 0
    for attempt_id, session_id, owner in rows:
        xp.lock(db, owner)
        s = db.get_one(MockSession, session_id, with_for_update=True)
        a = db.get_one(Attempt, attempt_id, populate_existing=True)
        if a.submitted_at is None:
            _time_out(db, s, db.get_one(Question, a.question_id), a, now)
            s.position += 1
            closed += 1
        db.commit()  # one question per transaction: player, then run, the order answering takes
    return closed


def _end(db: DB, s: MockSession, now: datetime) -> None:
    attempts = _attempts(db, s)
    for a in attempts.values():
        if a.submitted_at is None:
            _time_out(db, s, db.get_one(Question, a.question_id), a, now)
    s.position = len(attempts)
    s.finished_at = now


def end(db: DB, user: User, session_id: int, now: datetime) -> State:
    """End a run early. Ending it again changes nothing."""
    s = _session(db, user, session_id)
    if s.finished_at is None:
        _end(db, s, now)
        db.commit()
    return state(db, user, session_id, now)


def end_stale(db: DB, now: datetime) -> int:
    """Nightly: end runs nobody has touched for a while, so a forgotten run stops holding back its questions
    (from the daily question and practice)."""
    # Answering shows the next question, so the last one shown is the last time its player was there.
    touched = func.coalesce(func.max(Attempt.created_at), MockSession.started_at)
    rows = db.execute(
        select(MockSession.id, MockSession.user_id)
        .outerjoin(Attempt, Attempt.session_id == MockSession.id)
        .where(MockSession.finished_at.is_(None))
        .group_by(MockSession.id)
        .having(touched < now - rules.STALE_AFTER)
        .order_by(MockSession.user_id, MockSession.id)
    ).all()
    db.commit()
    ended = 0
    for session_id, owner in rows:
        xp.lock(db, owner)
        s = db.get_one(MockSession, session_id, with_for_update=True, populate_existing=True)
        if s.finished_at is None:
            _end(db, s, now)
            ended += 1
        db.commit()  # one run per transaction: player, then run, the order answering takes
    return ended


def _summary(db: DB, s: MockSession, now: datetime) -> Summary:
    attempts = _attempts(db, s)
    questions = _run(db, s, attempts)
    busy = running(db, s.user_id, now)  # e.g. today's daily question, not answered yet: its answer waits
    items = []
    for q in questions:
        a = attempts.get(q.id)
        answer = a.answer if a else {}
        checked = explain(db, q, a.correct if a else (False if q.graded else None), bool(a and a.passed))
        if q.id in busy:
            checked.official, checked.correct_options, checked.solutions = None, [], []
        # level 0: a summary item carries its own XP and LP, not where the player stands now
        checked.score = xp.Grant(xp=a.xp if a else 0, lp=a.lp if a else 0.0, level=0)
        items.append(Item(q, checked, bool(a and a.late), answer))
    correct = sum(1 for i in items if i.checked.correct and not i.late)  # right but late scores as wrong
    unreached = [q for q in _questions(db, s.quiz_id) if q.id not in attempts]
    quiz = db.get_one(Quiz, s.quiz_id)
    return Summary(
        correct=correct,
        graded=sum(1 for q in questions + unreached if q.graded),
        unreached=len(unreached),
        xp=sum(a.xp for a in attempts.values()),
        lp=round(sum(a.lp for a in attempts.values()), 2),
        counted=s.counted,
        bar_to_beat=rules.bar_to_beat(quiz.last_qualifier),
        items=items,
    )


def state(db: DB, user: User, session_id: int, now: datetime) -> State:
    s = _session(db, user, session_id)
    current = None if s.finished_at else _advance(db, s, now)
    db.commit()
    return State(
        session=s,
        label=label(db, db.get_one(Quiz, s.quiz_id)),
        total=len(_run(db, s, _attempts(db, s))),
        current=current,
        summary=_summary(db, s, now) if s.finished_at else None,
    )


def answer(
    db: DB,
    user: User,
    session_id: int,
    attempt_id: int,
    options: list[int] | None,
    value: str | None,
    now: datetime,
    unsure: bool = False,
) -> State:
    """Answer the question on screen and move on. Answering it again changes nothing."""
    s = _session(db, user, session_id)
    a = db.scalar(select(Attempt).where(Attempt.id == attempt_id, Attempt.session_id == s.id))
    if a is None or a.deadline_at is None:
        raise UserError("That question isn't part of this run.", 404)
    if a.submitted_at is None:
        q = db.get_one(Question, a.question_id)
        checked = check(db, q, options, value, unsure)
        late = timing.is_late(now, a.deadline_at)
        recorded = db.execute(
            update(Attempt)
            .where(Attempt.id == a.id, Attempt.submitted_at.is_(None))
            .values(
                answer={"options": options, "value": value, "unsure": checked.passed},
                correct=checked.correct,
                submitted_at=now,
                late=late,
                passed=checked.passed,
            )
            .returning(Attempt.id)
        ).first()
        if (
            recorded
        ):  # a replay of a quiz already run this season earns XP only; questions seen before, a quarter
            repeat = xp.last_seen(db, user.id, q.id, s.started_at, other_than=a.id) is not None
            granted = xp.grant(
                db,
                user.id,
                q,
                "mock",
                checked.correct,
                now,
                repeat=repeat,
                late=late,
                passed=checked.passed,
                hint=a.hint_used,
                again_today=xp.answered_today(db, user.id, q.id, now, other_than=a.id),
                ranked=s.counted,
                season_at=s.started_at,
                played_on=timing.madrid_day(a.created_at),
            )
            db.execute(update(Attempt).where(Attempt.id == a.id).values(xp=granted.xp, lp=granted.lp))
        db.commit()
    return state(db, user, session_id, now)
