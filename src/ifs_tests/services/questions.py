"""Questions as players see them, and checking an answer. Shared by practice, daily and mock modes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

from sqlalchemy import and_, exists, or_, select, union
from sqlalchemy.orm import Session as DB

from ..db.models import (
    DAILY,
    PENDING,
    AnswerKey,
    AnswerOption,
    Attempt,
    DailyQuestion,
    Document,
    Event,
    LivePlayer,
    LiveQuestion,
    LiveSession,
    MockSession,
    Question,
    Quiz,
    QuizQuestion,
    Solution,
    quiz_documents,
    quiz_events,
)
from ..domain import shuffle
from ..domain.daily import GRACE, madrid_day
from ..domain.grading import grade, unreadable
from ..domain.keys import decimal_comma
from .errors import UserError

if TYPE_CHECKING:
    from .xp import Grant

MAX_QUIZ_LABELS = 4
OrderVerdict = Literal["shuffled", "auto", "pinned"]
WITHHELD = "This question is someone's daily question today: practise it later."
YOURS_TONIGHT = "Your daily answer to this question shows at midnight (Madrid time)."


@dataclass
class Doc:
    title: str
    type: str
    year: int
    path: str


@dataclass
class Documents:
    """What the quizzes a question came from were based on, and newer versions of those documents."""

    year: int | None
    used: list[Doc]
    newer: list[Doc]


@dataclass
class Shown:
    question: Question
    options: list[AnswerOption]
    quizzes: list[str]
    values: int | None
    documents: Documents


@dataclass
class Checked:
    correct: bool | None
    official: str | None
    correct_options: list[int]
    solutions: list[tuple[str | None, list[str]]]
    score: Grant | None = None  # set by the mode that scored the answer
    passed: bool = False


def _quiz_labels(db: DB, ids: list[int]) -> dict[int, list[str]]:
    rows = db.execute(
        select(QuizQuestion.question_id, Event.short_name, Quiz.year, Quiz.vehicle_class)
        .join(Quiz, Quiz.id == QuizQuestion.quiz_id)
        .join(quiz_events, quiz_events.c.quiz_id == Quiz.id)
        .join(Event, Event.id == quiz_events.c.event_id)
        .where(QuizQuestion.question_id.in_(ids))
        .order_by(Quiz.year.desc(), Quiz.held_on.desc().nulls_last(), Event.short_name, Quiz.id)
    )
    labels: dict[int, list[str]] = defaultdict(list)
    for qid, event, year, vehicle in rows:
        label = f"{event} {year} {vehicle.upper()}"
        if label not in labels[qid] and len(labels[qid]) < MAX_QUIZ_LABELS:
            labels[qid].append(label)
    return labels


ORDER = {"Rulebook": 0, "Additional Rules": 1, "Handbook": 2}
SUPERSEDED = ("Rulebook", "Handbook")  # kinds where a later year replaces an earlier one


def _successor(d: Document, o: Document) -> bool:
    """`o` is a later edition of `d`: same kind, later year, and the same events (or both for every event)."""
    same_scope = bool(set(o.event_ids) & set(d.event_ids)) if d.event_ids else not o.event_ids
    return o.type == d.type and o.year > d.year and same_scope


def _doc(d: Document) -> Doc:
    """Titled from the file name, which says more than the type: "FSG23 Competition Handbook v1.0". A few
    documents are a web page rather than a file; those are titled by kind, year and site."""
    if "://" in d.path:
        return Doc(f"{d.type} {d.year} ({urlsplit(d.path).hostname})", d.type, d.year, d.path)
    name = d.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return Doc(" ".join(name.replace("_", " ").replace("-", " ").split()), d.type, d.year, d.path)


def _documents(db: DB, ids: list[int]) -> dict[int, Documents]:
    rows = db.execute(
        select(QuizQuestion.question_id, Document)
        .join(quiz_documents, quiz_documents.c.quiz_id == QuizQuestion.quiz_id)
        .join(Document, Document.id == quiz_documents.c.document_id)
        .where(QuizQuestion.question_id.in_(ids))
    ).all()
    if not rows:
        return {i: Documents(None, [], []) for i in ids}
    everything = db.scalars(select(Document)).all()
    used: dict[int, dict[int, Document]] = defaultdict(dict)
    for qid, d in rows:
        used[qid][d.id] = d
    out = {}
    for qid in ids:
        docs = sorted(used[qid].values(), key=lambda d: (-d.year, ORDER.get(d.type, 9), d.path))
        newer: dict[int, Document] = {}
        for d in docs:
            later = [o for o in everything if _successor(d, o)] if d.type in SUPERSEDED else []
            if later:
                latest = max(later, key=lambda o: (o.year, o.version or ""))
                if latest.id not in used[qid]:
                    newer[latest.id] = latest
        year = docs[0].year if docs else None
        newest = sorted(newer.values(), key=lambda d: (ORDER.get(d.type, 9), d.path))
        out[qid] = Documents(year, [_doc(d) for d in docs], [_doc(d) for d in newest])
    return out


def _value_count(key: dict[str, Any] | None) -> int | None:
    """How many values a "numbers" answer needs, when every accepted answer agrees."""
    if not key or key["kind"] != "numbers":
        return None
    counts = {len(a["values"]) for a in key["accept"]}
    return counts.pop() if len(counts) == 1 else None


def _solutions(db: DB, ids: list[int]) -> dict[int, list[str]]:
    found: dict[int, list[str]] = defaultdict(list)
    for qid, text in db.execute(
        select(Solution.question_id, Solution.text).where(Solution.question_id.in_(ids)).order_by(Solution.id)
    ):
        if text:
            found[qid].append(text)
    return found


def show(
    db: DB, questions: list[Question], picked: Iterable[int] = (), *, order_key: bytes | None = None
) -> list[Shown]:
    """`picked`: option IDs a player already chose, shown even if FS-Quiz has since removed them. `order_key`:
    the daily's per-attempt shuffle; every other caller keeps bank order."""
    ids = [q.id for q in questions]
    picked_ids = set(picked)
    options: dict[int, list[AnswerOption]] = defaultdict(list)
    stmt = select(AnswerOption).where(AnswerOption.question_id.in_(ids))
    if order_key is None:
        stmt = stmt.where(AnswerOption.retired.is_(False) | AnswerOption.id.in_(list(picked_ids)))
    for o in db.scalars(stmt.order_by(AnswerOption.position, AnswerOption.id)):
        options[o.question_id].append(o)
    if order_key is not None:
        solutions = _solutions(db, ids)
        for q in questions:
            opts = options[q.id]
            if not q.keep_order:
                choices = [shuffle.Choice(o.id, o.text, o.retired) for o in opts]
                by_id = {o.id: o for o in opts}
                opts = [
                    by_id[i]
                    for i in shuffle.order(
                        choices, order_key, q.answer_kind, q.text, solutions[q.id], has_images=bool(q.images)
                    )
                ]
            options[q.id] = [o for o in opts if not o.retired or o.id in picked_ids]
    found = db.scalars(select(AnswerKey).where(AnswerKey.question_id.in_(ids)))
    keys = {k.question_id: k.effective for k in found}
    labels = _quiz_labels(db, ids)
    docs = _documents(db, ids)
    return [
        Shown(q, options[q.id], labels[q.id], _value_count(keys.get(q.id)), docs[q.id]) for q in questions
    ]


def order_verdict(db: DB, q: Question) -> tuple[OrderVerdict, str | None]:
    """How the daily shows this question's options: ('pinned' | 'auto' | 'shuffled', the reason it would be kept
    in bank order, if any). Reviewers see it so the pin isn't blind."""
    opts = db.scalars(
        select(AnswerOption)
        .where(AnswerOption.question_id == q.id)
        .order_by(AnswerOption.position, AnswerOption.id)
    ).all()
    reason = shuffle.keep_reason(
        [shuffle.Choice(o.id, o.text, o.retired) for o in opts],
        q.answer_kind,
        q.text,
        _solutions(db, [q.id])[q.id],
        has_images=bool(q.images),
    )
    return ("pinned" if q.keep_order else "auto" if reason else "shuffled"), reason


def playable(db: DB, question_id: int) -> Question:
    q = db.get(Question, question_id)
    if q is None or not q.playable:
        raise UserError("That question doesn't exist.", 404)
    return q


def explain(db: DB, q: Question, correct: bool | None, passed: bool = False) -> Checked:
    """The official answer and solutions around a result. Past results come from the stored attempt and go
    straight here: they are never graded again, so a later bank reload or correction can't change them."""
    key = db.get(AnswerKey, q.id)
    k = key.effective if key else None
    solutions = db.scalars(select(Solution).where(Solution.question_id == q.id).order_by(Solution.id)).all()
    return Checked(
        correct=correct,
        official=key.shown if key else None,
        correct_options=list(k["options"]) if k and k["kind"] == "choice" else [],
        solutions=[(s.text, list(s.images)) for s in solutions],
        passed=passed,
    )


def check(db: DB, q: Question, options: list[int] | None, value: str | None, unsure: bool = False) -> Checked:
    """Grade a new answer and return everything needed to explain it. Never call before the player answered.
    `unsure` is "I'm not sure": no answer, marked not right, the official answer shown. An option FS-Quiz
    removed is refused like any unknown one, even if it was on screen; answers that picked it earlier still
    show it (`show`). A typed answer the grader can't read (units, a thousands comma) is refused before anything
    is recorded, so the player can fix it while the clock runs."""
    choices = db.scalars(
        select(AnswerOption.id).where(AnswerOption.question_id == q.id, AnswerOption.retired.is_(False))
    ).all()
    if options and not set(options) <= set(choices):
        raise UserError("Pick one of the listed answers.")
    key = db.get(AnswerKey, q.id)
    k = key.effective if key else None
    passed = unsure and q.graded
    if q.graded and not passed and (problem := unreadable(k, value, decimal_comma(q.text))):
        raise UserError(problem, fields={"value": problem})
    correct = (False if passed else grade(k, options=options, value=value)) if q.graded else None
    return explain(db, q, correct, passed)


def running(db: DB, user_id: int, now: datetime, *, daily: bool = True, on_screen: bool = False) -> set[int]:
    """The questions `user_id` still has to answer in a scored mode: today's daily questions (and one they
    started before midnight and haven't answered, and one they answered whose result shows at midnight), the
    questions of their open mock runs, and the open question (every question, in a rehearsal) of a live quiz they
    play in. Their answers must not reach them another way first. A per-player day has no `daily_questions` row,
    so its daily part is the player's own started attempts and those still to be revealed.
    `daily=False` leaves the daily part out; `on_screen=True` narrows a mock run to the question it has shown
    and is waiting for (the rest of the run is skipped once it is someone's daily: `mock._run`)."""
    day = madrid_day(now)

    def answered(question_id: Any, *where: Any) -> Any:
        return exists().where(
            Attempt.user_id == user_id,
            Attempt.question_id == question_id,
            Attempt.submitted_at.is_not(None),
            *where,
        )

    today = select(DailyQuestion.question_id).where(
        DailyQuestion.day == day,
        ~answered(DailyQuestion.question_id, Attempt.mode == "daily", Attempt.day == day),
    )
    started = select(Attempt.question_id).where(
        Attempt.user_id == user_id, Attempt.mode == "daily", Attempt.submitted_at.is_(None)
    )
    pending = _yours_tonight(user_id, now)
    in_run = (
        select(QuizQuestion.question_id)
        .join(MockSession, QuizQuestion.quiz_id == MockSession.quiz_id)
        .where(
            MockSession.user_id == user_id,
            MockSession.finished_at.is_(None),
            ~answered(QuizQuestion.question_id, Attempt.session_id == MockSession.id),
        )
    )
    if on_screen:
        in_run = select(Attempt.question_id).where(
            Attempt.user_id == user_id,
            Attempt.mode == "mock",
            Attempt.submitted_at.is_(None),
            Attempt.deadline_at >= now - GRACE,
        )
    in_live = (
        select(LiveQuestion.question_id)
        .join(LiveSession, LiveQuestion.session_id == LiveSession.id)
        .join(LivePlayer, LivePlayer.session_id == LiveSession.id)
        .where(
            LivePlayer.user_id == user_id,
            ~LivePlayer.removed,
            LiveSession.state != "finished",
            or_(
                and_(LiveQuestion.position == LiveSession.position, LiveSession.state == "open"),
                LiveSession.config["feedback"].astext == "end",
            ),
        )
    )
    return set(
        db.scalars(union(today, started, pending, in_run, in_live) if daily else union(in_run, in_live))
    )


def _yours_tonight(user_id: int, now: datetime) -> Any:
    """The player's answered per-player dailies whose result is still to come at midnight."""
    return select(Attempt.question_id).where(Attempt.user_id == user_id, PENDING, Attempt.released_at > now)


def withheld(db: DB, now: datetime) -> set[int]:
    """The questions still running for whoever drew them as their per-player daily: today's, answered or not (the
    result is revealed at midnight, so the key is out for nobody before then), and yesterday's still unanswered
    inside its clock. Kept from every second surface (practice, the mock run and summary, the reviewer view, live
    picks, reveals and the CSV): one of them answering it would pass the answer on. Keyed on `released_at`,
    written when the attempt was started, so it never changes for an attempt already started; empty on shared
    days, which don't write it."""
    return set(
        db.scalars(
            select(Attempt.question_id).where(
                DAILY,
                Attempt.day
                >= madrid_day(now) - timedelta(days=1),  # implied below; lets ix_attempts_daily_day serve
                or_(
                    Attempt.released_at > now,
                    and_(
                        Attempt.released_at.is_not(None),
                        Attempt.submitted_at.is_(None),
                        Attempt.deadline_at >= now - GRACE,
                    ),
                ),
            )
        )
    )


def running_for(db: DB, user_id: int, question_id: int, now: datetime) -> bool:
    return question_id in running(db, user_id, now) or question_id in withheld(db, now)


def not_running(db: DB, user_id: int, question_id: int, now: datetime) -> None:
    """Practice can't answer or hint at a question still to be answered elsewhere: that would give it away."""
    if question_id in set(db.scalars(_yours_tonight(user_id, now))):
        raise UserError(YOURS_TONIGHT, 409)
    if question_id in running(db, user_id, now):
        raise UserError(
            "This question is running in your daily question, mock or live quiz: answer it there first.", 409
        )
    if question_id in withheld(db, now):
        raise UserError(WITHHELD, 409)
