"""Live quiz sessions (ADR 0005): a Technical Director or admin runs a quiz for the room; tables answer through
their captains, and every member at a table shares its result."""

from __future__ import annotations

import csv
import io
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DB

from ..db.models import (
    AnswerOption,
    Attempt,
    LiveAnswer,
    LivePlayer,
    LiveProposal,
    LiveQuestion,
    LiveSession,
    LiveTable,
    Question,
    Quiz,
    QuizQuestion,
    User,
)
from ..domain import daily as timing
from ..domain import live as rules
from ..domain import mock as mock_rules
from . import xp
from .errors import UserError
from .questions import Checked, Shown, check, show


def can_host(user: User) -> bool:
    """By position on the team, never by XP level: a DT on the ladder is not a Technical Director."""
    return user.role == "admin" or user.position == "technical_director"


def create(db: DB, host: User, config: dict[str, Any], now: datetime) -> LiveSession:
    if not can_host(host):
        raise UserError("Only Technical Directors and admins host live quizzes.", 403)
    _check_config(db, config)
    rng = random.SystemRandom()
    for _ in range(10):
        s = LiveSession(code=rules.new_code(rng), host_id=host.id, config=config, created_at=now)
        db.add(s)
        try:
            db.commit()
            return s
        except IntegrityError:
            db.rollback()
    raise UserError("Couldn't find a free code. Try again.", 503)


def _check_config(db: DB, config: dict[str, Any]) -> None:
    if config["questions"] == "quiz" and db.get(Quiz, config.get("quiz_id") or 0) is None:
        raise UserError("That quiz doesn't exist.", 404)


def _session(db: DB, code: str, lock: bool = False) -> LiveSession:
    stmt = select(LiveSession).where(LiveSession.code == code.upper())
    # populate_existing: a locked read must see what another request committed, not this session's cache.
    s = db.scalar(stmt.with_for_update().execution_options(populate_existing=True) if lock else stmt)
    if s is None:
        raise UserError("No live quiz with that code.", 404)
    return s


def _runs(user: User, s: LiveSession) -> bool:
    return s.host_id == user.id or user.role == "admin"


def _not_finished(s: LiveSession) -> None:
    if s.state == "finished":
        raise UserError("This live quiz has finished.", 409)


def _hosted(db: DB, user: User, code: str) -> LiveSession:
    s = _session(db, code, lock=True)
    if not _runs(user, s):
        raise UserError("Only the host runs the session.", 403)
    _not_finished(s)
    return s


def _touch(s: LiveSession) -> None:
    s.version += 1


def _finish(db: DB, s: LiveSession, now: datetime) -> None:
    s.state, s.finished_at = "finished", now
    _touch(s)
    for a in db.scalars(select(LiveAnswer).where(LiveAnswer.session_id == s.id, ~LiveAnswer.granted)):
        _share(db, s, a, now)  # a rehearsal's XP, held back so it couldn't give answers away


def lock_hosted(db: DB, host_id: int) -> list[LiveSession]:
    """The sessions someone still hosts, locked before their account is: the order answering takes (the
    session, then the players' rows), so deleting a host can't deadlock with a captain's answer."""
    stmt = (
        select(LiveSession)
        .where(LiveSession.host_id == host_id, LiveSession.state != "finished")
        .order_by(LiveSession.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(db.scalars(stmt))


def finish(db: DB, sessions: list[LiveSession], now: datetime) -> None:
    for s in sessions:
        _finish(db, s, now)


def _expired(s: LiveSession, now: datetime) -> bool:
    return s.state == "open" and s.deadline_at is not None and timing.is_late(now, s.deadline_at)


def refresh(db: DB, code: str, now: datetime) -> int:
    """Close a question whose time ran out; the version tells screens whether to fetch the state again.
    One conditional update, so it can never close a question the host opened a moment earlier."""
    closed = db.execute(
        update(LiveSession)
        .where(
            LiveSession.code == code.upper(),
            LiveSession.state == "open",
            LiveSession.deadline_at < now - timing.GRACE,
        )
        .values(state="closed", version=LiveSession.version + 1)
        .returning(LiveSession.version)
    ).scalar()
    version = closed if closed is not None else _session(db, code).version
    db.commit()
    return version


def join(db: DB, user: User, code: str, now: datetime) -> LiveSession:
    s = _session(db, code, lock=True)
    _not_finished(s)
    if db.scalar(
        select(LivePlayer.removed).where(LivePlayer.session_id == s.id, LivePlayer.user_id == user.id)
    ):
        raise UserError("The host removed you from this live quiz.", 403)
    if user.id != s.host_id:
        added = db.execute(
            insert(LivePlayer)
            .values(session_id=s.id, user_id=user.id, joined_at=now)
            .on_conflict_do_nothing()
            .returning(LivePlayer.user_id)
        ).first()
        if added:
            _touch(s)
    db.commit()
    return s


def configure(db: DB, host: User, code: str, config: dict[str, Any]) -> None:
    s = _hosted(db, host, code)
    if s.state != "lobby":
        raise UserError("The quiz has started: its settings are fixed.", 409)
    _check_config(db, config)
    s.config = config
    _touch(s)
    db.commit()


def _players(db: DB, s: LiveSession) -> dict[int, LivePlayer]:
    rows = db.scalars(select(LivePlayer).where(LivePlayer.session_id == s.id, ~LivePlayer.removed))
    return {p.user_id: p for p in rows}


def seat(db: DB, host: User, code: str, tables: list[dict[str, Any]]) -> None:
    """Replace the tables in the lobby: [{name, captain_id, member_ids, topics, catch_all}]."""
    s = _hosted(db, host, code)
    if s.state != "lobby":
        raise UserError("Tables are set before the quiz starts; move people one by one now.", 409)
    players = _players(db, s)
    seen: set[int] = set()
    if sum(bool(t.get("catch_all")) for t in tables) > 1:
        raise UserError("Only one table takes the questions nobody owns.")
    for t in tables:
        members = set(t["member_ids"])
        if not members <= players.keys() or members & seen:
            raise UserError("Each table takes players from this session, each at one table.")
        if t.get("captain_id") is not None and t["captain_id"] not in members:
            raise UserError("A captain sits at their own table.")
        seen |= members
    db.execute(update(LivePlayer).where(LivePlayer.session_id == s.id).values(table_id=None))
    db.execute(delete(LiveTable).where(LiveTable.session_id == s.id))
    levels = dict(db.execute(select(User.id, User.rank_points).where(User.id.in_(seen))).tuples().all())
    for t in tables:
        # A table built by hand gets its best-ranked member as captain until the host picks another.
        captain = t.get("captain_id") or max(
            t["member_ids"], key=lambda uid: (levels[uid], -uid), default=None
        )
        table = LiveTable(
            session_id=s.id,
            name=t["name"],
            captain_id=captain,
            topics=t.get("topics") or [],
            catch_all=bool(t.get("catch_all")),
        )
        db.add(table)
        db.flush()
        for uid in t["member_ids"]:
            players[uid].table_id = table.id
    _touch(s)
    db.commit()


def seat_by_subdepartment(db: DB, host: User, code: str) -> None:
    s = _hosted(db, host, code)
    rows = db.execute(
        select(User.id, User.subdepartments, User.rank_points)
        .join(LivePlayer, LivePlayer.user_id == User.id)
        .where(LivePlayer.session_id == s.id, ~LivePlayer.removed)
    )
    players = [rules.Player(uid, tuple(subs or ()), points) for uid, subs, points in rows]
    tables = [asdict(t) for t in rules.seat_by_subdepartment(players)]
    for t in tables:  # the table of people without a sub-department takes the questions nobody owns
        t["catch_all"] = t["name"] == rules.EVERYONE_ELSE
    seat(db, host, code, tables)


def move(db: DB, host: User, code: str, user_id: int, table_id: int | None) -> None:
    """Seat, move or unseat one player at any point before the end (latecomers, a swap between questions)."""
    s = _hosted(db, host, code)
    player = _players(db, s).get(user_id)
    table = db.get(LiveTable, table_id) if table_id is not None else None
    if player is None or (table_id is not None and (table is None or table.session_id != s.id)):
        raise UserError("No such player or table in this session.", 404)
    for t in db.scalars(
        select(LiveTable).where(LiveTable.session_id == s.id, LiveTable.captain_id == user_id)
    ):
        if t.id != table_id:
            t.captain_id = None
    player.table_id = table_id
    _touch(s)
    db.commit()


def edit_table(
    db: DB, host: User, code: str, table_id: int, name: str | None, captain_id: int | None
) -> None:
    s = _hosted(db, host, code)
    table = db.get(LiveTable, table_id)
    if table is None or table.session_id != s.id:
        raise UserError("No such table in this session.", 404)
    if captain_id is not None:
        player = _players(db, s).get(captain_id)
        if player is None or player.table_id != table.id:
            raise UserError("A captain sits at their own table.")
        table.captain_id = captain_id
    if name:
        table.name = name
    _touch(s)
    db.commit()


def remove(db: DB, host: User, code: str, user_id: int) -> None:
    s = _hosted(db, host, code)
    db.execute(
        update(LiveTable)
        .where(LiveTable.session_id == s.id, LiveTable.captain_id == user_id)
        .values(captain_id=None)
    )
    db.execute(
        update(LivePlayer)
        .where(LivePlayer.session_id == s.id, LivePlayer.user_id == user_id)
        .values(removed=True, table_id=None)
    )
    _touch(s)
    db.commit()


def _pick(db: DB, config: dict[str, Any]) -> list[Question]:
    base = select(Question).where(Question.playable, Question.graded)
    if config["questions"] == "quiz":
        stmt = (
            base.join(QuizQuestion, QuizQuestion.question_id == Question.id)
            .where(QuizQuestion.quiz_id == config["quiz_id"])
            .order_by(QuizQuestion.position)
        )
        return list(db.scalars(stmt))
    areas, topics = config.get("areas") or [], config.get("topics") or []
    if areas or topics:
        base = base.where(or_(Question.area.in_(areas), Question.topic.in_(topics)))
    return list(db.scalars(base.order_by(func.random()).limit(config["count"])))


def _budget(config: dict[str, Any], q: Question) -> int | None:
    if config["timing"] == "real":
        return timing.budget(q.time_s, q.answer_kind)
    return int(config["seconds"]) if config["timing"] == "fixed" else None


def _open(s: LiveSession, position: int, budget: int | None, now: datetime) -> None:
    s.state, s.position, s.opened_at = "open", position, now
    s.deadline_at = now + timedelta(seconds=budget) if budget else None
    _touch(s)


def _tables(db: DB, s: LiveSession) -> list[LiveTable]:
    return list(db.scalars(select(LiveTable).where(LiveTable.session_id == s.id).order_by(LiveTable.id)))


def advance(db: DB, host: User, code: str, now: datetime, seen: tuple[str, int] | None = None) -> None:
    """The host's one button: start, close the question, open the next one, finish after the last. `seen` is
    the state the host's screen showed: a double tap, or a second device, mustn't skip a step."""
    s = _hosted(db, host, code)
    if seen is not None and seen != (s.state, s.position):
        raise UserError("The quiz has already moved on.", 409)
    if _expired(s, now):  # time ran out and nothing noticed yet: close it first, so its reveal shows
        s.state = "closed"
        _touch(s)
        db.commit()
        return
    if s.state == "lobby":
        _start(db, s, now)
    elif s.state == "open":
        s.state = "closed"
        _touch(s)
    else:
        nxt = db.get(LiveQuestion, (s.id, s.position + 1))
        if nxt is None:
            _finish(db, s, now)
        else:
            _open(s, nxt.position, nxt.budget_s, now)
    db.commit()


def _start(db: DB, s: LiveSession, now: datetime) -> None:
    tables = [t for t in _tables(db, s) if t.captain_id is not None]
    if not tables:
        raise UserError("Seat people at a table with a captain first.", 409)
    questions = _pick(db, s.config)
    if not questions:
        raise UserError("No questions match these settings.", 409)
    owners = [(t.id, list(t.topics)) for t in tables]
    # Questions no table owns go to the chosen table, else the biggest: it has the widest mix of people.
    sizes = {t.id: len([p for p in _players(db, s).values() if p.table_id == t.id]) for t in tables}
    catch_all = next((t.id for t in tables if t.catch_all), max(tables, key=lambda t: sizes[t.id]).id)
    specialists = s.config["routing"] == "owners"
    for i, q in enumerate(questions):
        db.add(
            LiveQuestion(
                session_id=s.id,
                position=i,
                question_id=q.id,
                table_id=rules.owner(q.topic, owners, catch_all) if specialists else None,
                budget_s=_budget(s.config, q),
            )
        )
    db.flush()
    _open(s, 0, db.get_one(LiveQuestion, (s.id, 0)).budget_s, now)


def end(db: DB, host: User, code: str, now: datetime) -> None:
    _finish(db, _hosted(db, host, code), now)
    db.commit()


def _running(db: DB, code: str, now: datetime) -> tuple[LiveSession, LiveQuestion]:
    s = _session(db, code, lock=True)
    if _expired(s, now):
        s.state = "closed"
        _touch(s)
        db.commit()
        raise UserError("Time is up for this question.", 409)
    if s.state != "open":
        raise UserError("There's no question open right now.", 409)
    return s, db.get_one(LiveQuestion, (s.id, s.position))


def propose(db: DB, user: User, code: str, answer: dict[str, Any], now: datetime) -> None:
    """Suggest an answer to the captain of the table answering the question (your own, in all-tables mode)."""
    s, lq = _running(db, code, now)
    player = _players(db, s).get(user.id)
    if player is None or player.table_id is None:
        raise UserError("Sit at a table first.", 409)
    target = lq.table_id or player.table_id
    row = {"table_id": target, "answer": answer, "updated_at": now}
    db.execute(
        insert(LiveProposal)
        .values(session_id=s.id, position=s.position, user_id=user.id, **row)
        .on_conflict_do_update(index_elements=["session_id", "position", "user_id"], set_=row)
    )
    _touch(s)
    db.commit()


def answer(
    db: DB, user: User, code: str, options: list[int] | None, value: str | None, unsure: bool, now: datetime
) -> None:
    """The captain sends the table's one answer. Every member seated at the table shares the XP."""
    s, lq = _running(db, code, now)
    table = db.scalar(select(LiveTable).where(LiveTable.session_id == s.id, LiveTable.captain_id == user.id))
    if table is None:
        raise UserError("Only a table's captain sends its answer.", 403)
    if lq.table_id not in (None, table.id):
        raise UserError("This question is for another table.", 403)
    q = db.get_one(Question, lq.question_id)
    checked = check(db, q, options, value, unsure)
    elapsed = (now - s.opened_at).total_seconds() if s.opened_at else 0
    points = rules.speed_points(checked.correct, elapsed, lq.budget_s) if s.config.get("speed_points") else 0
    body = {"options": options, "value": value, "unsure": checked.passed}
    sent = db.execute(
        insert(LiveAnswer)
        .values(
            session_id=s.id,
            position=s.position,
            table_id=table.id,
            answer=body,
            correct=checked.correct,
            passed=checked.passed,
            points=points,
            by_user_id=user.id,
            submitted_at=now,
        )
        .on_conflict_do_nothing()
        .returning(LiveAnswer.table_id)
    ).first()
    if sent is None:
        raise UserError("Your table has already answered.", 409)
    a = db.get_one(LiveAnswer, (s.id, s.position, table.id))
    a.member_ids = list(
        db.scalars(
            select(LivePlayer.user_id)
            .where(LivePlayer.session_id == s.id, LivePlayer.table_id == table.id, ~LivePlayer.removed)
            .order_by(LivePlayer.user_id)
        )
    )
    if s.config["feedback"] == "each":
        _share(db, s, a, now)
    expected = {lq.table_id} if lq.table_id else {t.id for t in _tables(db, s) if t.captain_id is not None}
    answered = set(
        db.scalars(
            select(LiveAnswer.table_id).where(
                LiveAnswer.session_id == s.id, LiveAnswer.position == s.position
            )
        )
    )
    if expected <= answered:
        s.state = "closed"
    _touch(s)
    db.commit()


def _share(db: DB, s: LiveSession, a: LiveAnswer, now: datetime) -> None:
    """Every member seated when the table answered shares its XP. A table's answer isn't one person's
    performance, so it never moves anyone's rank."""
    q = db.get_one(Question, db.get_one(LiveQuestion, (s.id, a.position)).question_id)
    scored = set(
        db.scalars(
            select(Attempt.user_id).where(Attempt.live_session_id == s.id, Attempt.question_id == q.id)
        )
    )
    for uid in a.member_ids:  # in id order, so tables answering at once lock players in the same order
        if uid in scored:  # moved to another table mid-question: their first table's answer counted
            continue
        if db.scalar(select(User.id).where(User.id == uid).with_for_update(key_share=True)) is None:
            continue  # deleted their account after sitting down
        xp.lock(db, uid)  # before checking what they've seen, so a first answer can't count twice
        repeat = xp.last_seen(db, uid, q.id, now) is not None
        granted = xp.grant(db, uid, q, "live", a.correct, now, repeat=repeat, passed=a.passed)
        db.add(
            Attempt(
                user_id=uid,
                question_id=q.id,
                mode="live",
                answer=a.answer,
                correct=a.correct,
                passed=a.passed,
                created_at=now,
                submitted_at=now,
                late=False,
                area=q.area,
                xp=granted.xp,
                live_session_id=s.id,
            )
        )
    a.granted = True


# What each screen sees


@dataclass
class TableView:
    id: int
    name: str
    captain_id: int | None
    topics: list[str]
    catch_all: bool
    member_ids: list[int]
    answered: bool
    right: int = 0
    points: int = 0


@dataclass
class Reveal:
    position: int
    shown: Shown
    table_id: int | None
    checked: Checked
    answers: dict[int, LiveAnswer]


@dataclass
class View:
    session: LiveSession
    host_name: str
    role: Literal["host", "player"]
    my_table_id: int | None
    captain: bool
    players: list[tuple[int, str, int | None]]
    tables: list[TableView]
    total: int
    current: Shown | None = None
    current_table_id: int | None = None
    budget_s: int | None = None
    my_answer: dict[str, Any] | None = None
    proposals: list[tuple[int, str, dict[str, Any]]] = field(default_factory=list)
    reveals: list[Reveal] = field(default_factory=list)
    room_right: int | None = None
    room_asked: int = 0
    bar_to_beat: str | None = None


def _revealed(s: LiveSession) -> bool:
    """Right and wrong show after each question, or only at the end in a rehearsal."""
    return s.state == "finished" or (s.state == "closed" and s.config["feedback"] == "each")


def view(db: DB, user: User, code: str, now: datetime) -> View:
    refresh(db, code, now)
    s = _session(db, code)
    players = _players(db, s)
    if user.id != s.host_id and user.id not in players:  # admins too: they join like anyone else
        raise UserError("Join the live quiz first.", 403)
    names = dict(
        db.execute(select(User.id, User.display_name).where(User.id.in_([*players, s.host_id or 0])))
        .tuples()
        .all()
    )
    me = players.get(user.id)
    tables = _tables(db, s)
    questions = {
        lq.position: lq for lq in db.scalars(select(LiveQuestion).where(LiveQuestion.session_id == s.id))
    }
    answers: dict[int, dict[int, LiveAnswer]] = {}
    for a in db.scalars(select(LiveAnswer).where(LiveAnswer.session_id == s.id)):
        answers.setdefault(a.position, {})[a.table_id] = a
    lq = questions.get(s.position)
    table_views = [
        TableView(
            t.id,
            t.name,
            t.captain_id,
            list(t.topics),
            t.catch_all,
            [p.user_id for p in players.values() if p.table_id == t.id],
            t.id in answers.get(s.position, {}),
        )
        for t in tables
    ]
    out = View(
        session=s,
        host_name=names.get(s.host_id or 0, "a former member"),
        role="host" if user.id == s.host_id else "player",
        my_table_id=me.table_id if me else None,
        captain=any(t.captain_id == user.id for t in tables),
        players=[(p.user_id, names.get(p.user_id, ""), p.table_id) for p in players.values()],
        tables=table_views,
        total=len(questions),
    )
    if s.config["questions"] == "quiz":
        quiz = db.get(Quiz, s.config["quiz_id"])
        out.bar_to_beat = mock_rules.bar_to_beat(quiz.last_qualifier) if quiz else None
    if lq is not None and s.state in ("open", "closed"):
        q = db.get_one(Question, lq.question_id)
        out.current, out.current_table_id, out.budget_s = show(db, [q])[0], lq.table_id, lq.budget_s
        target = lq.table_id or out.my_table_id
        mine = answers.get(s.position, {}).get(target) if target else None
        out.my_answer = mine.answer if mine else None
        if me is not None and target is not None:
            rows = db.execute(
                select(LiveProposal.user_id, LiveProposal.table_id, LiveProposal.answer).where(
                    LiveProposal.session_id == s.id, LiveProposal.position == s.position
                )
            )
            out.proposals = [
                (uid, names.get(uid, ""), ans)
                for uid, tid, ans in rows
                if tid == target and (me.table_id == target or uid == user.id)
            ]
    closed = [p for p in sorted(questions) if p < s.position or (p == s.position and s.state != "open")]
    if _revealed(s):
        _score(db, s, questions, answers, closed, out)
    db.commit()  # read-only by now: give the connection back before the route serialises
    return out


def _score(
    db: DB,
    s: LiveSession,
    questions: dict[int, LiveQuestion],
    answers: dict[int, dict[int, LiveAnswer]],
    closed: list[int],
    out: View,
) -> None:
    """Right answers per table and for the room: the owning table's answer, or the best table's tally."""
    by_id = {t.id: t for t in out.tables}
    right = 0
    for p in closed:
        lq = questions[p]
        for tid, a in answers.get(p, {}).items():
            if tid in by_id:
                by_id[tid].right += bool(a.correct)
                by_id[tid].points += a.points
        owner = answers.get(p, {}).get(lq.table_id) if lq.table_id else None
        right += bool(owner and owner.correct)
    specialists = s.config["routing"] == "owners"
    out.room_asked = len(closed)
    out.room_right = right if specialists else max((t.right for t in out.tables), default=0)
    positions = closed if s.state == "finished" else [s.position]
    ids = [questions[p].question_id for p in positions]
    found = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(ids)))}
    qs = [found[i] for i in ids]
    for p, q, shown in zip(positions, qs, show(db, qs), strict=True):
        out.reveals.append(
            Reveal(p, shown, questions[p].table_id, check(db, q, None, None), answers.get(p, {}))
        )


def _cell(value: object) -> str:
    """Spreadsheets run a cell starting with = + - @ as a formula; names and answers come from players."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def results_csv(db: DB, user: User, code: str) -> str:
    """One row per table answer (or per question nobody answered), as the Excel sheet had them."""
    s = _session(db, code)
    if not _runs(user, s):
        raise UserError("Only the host downloads the results.", 403)
    tables = {t.id: t.name for t in _tables(db, s)}
    rows = db.execute(
        select(LiveQuestion.position, Question, LiveQuestion.table_id, LiveAnswer, User.display_name)
        .join(Question, Question.id == LiveQuestion.question_id)
        .outerjoin(
            LiveAnswer,
            (LiveAnswer.session_id == LiveQuestion.session_id)
            & (LiveAnswer.position == LiveQuestion.position),
        )
        .outerjoin(User, User.id == LiveAnswer.by_user_id)
        .where(LiveQuestion.session_id == s.id, LiveQuestion.position <= s.position)
        .order_by(LiveQuestion.position, LiveAnswer.table_id)
    ).all()
    ids = {row[1].id for row in rows}
    texts = dict(
        db.execute(select(AnswerOption.id, AnswerOption.text).where(AnswerOption.question_id.in_(ids)))
        .tuples()
        .all()
    )
    official = {q.id: check(db, q, None, None).official or "" for q in {row[1] for row in rows}}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "question",
            "text",
            "answered by",
            "table",
            "captain",
            "answer",
            "official answer",
            "right",
            "points",
        ]
    )
    for pos, q, owner, a, captain in rows:
        row = [q.text[:120], tables.get(owner, "every table"), "", "", ""]
        if a is not None:
            sent = a.answer.get("value") or ", ".join(
                texts.get(o, "?") for o in a.answer.get("options") or []
            )
            row[2:] = [tables.get(a.table_id, ""), captain or "", "not sure" if a.passed else sent]
        right = "" if a is None or a.correct is None else "yes" if a.correct else "no"
        w.writerow([pos + 1, *map(_cell, [*row, official[q.id]]), right, a.points if a else ""])
    return out.getvalue()
