"""Scoring answers (LP for the rank, XP for the account level) and keeping question difficulty in line with how
people do."""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Row, Select, and_, case, exists, func, or_, select, update
from sqlalchemy.orm import Session as DB

from ..db.models import (
    AS_OF,
    DAILY,
    PENDING,
    REVEALED,
    AnswerKey,
    AnswerOption,
    Attempt,
    MockSession,
    Question,
    User,
)
from ..domain import daily as daily_rules
from ..domain import leaderboard as board_rules
from ..domain import rank as rank_rules
from ..domain import xp as rules
from . import hints, streaks
from .errors import UserError

COUNTER_CAP = 99  # combo and bad-run counters are SMALLINT; nothing past a handful changes the score
log = logging.getLogger(__name__)


def streak_days(db: DB, user_id: int, now: datetime) -> int:
    """Consecutive Madrid days with an on-time daily answer (or a freeze), ending today (or yesterday)."""
    return streaks.days(db, user_id, now)


def rested(
    db: DB, bank: int, topped_up: date | None, user_id: int, now: datetime, day: date | None = None
) -> int:
    """Rested XP as it stands on `day` (today by default): the bank, plus what the full days away since the last
    scored answer added to it. (A daily started and abandoned, or a mock question shown, isn't playing.)"""
    today = day or daily_rules.madrid_day(now)
    if topped_up is not None and topped_up >= today:
        return bank
    if topped_up is not None:
        return rules.rested_bank(bank, (today - topped_up).days - 1)
    last = db.scalar(
        select(func.max(func.date(func.timezone("Europe/Madrid", Attempt.created_at)))).where(
            Attempt.user_id == user_id, Attempt.created_at < board_rules.madrid_midnight(today)
        )
    )
    return rules.rested_bank(bank, (today - last).days - 1) if last else bank


def lock(db: DB, user_id: int) -> Row[Any]:
    """Take the player's row lock until commit, so their answers are scored one at a time. NO KEY UPDATE
    still lets rows that reference the user (attempts, sessions) be inserted meanwhile."""
    row = db.execute(
        select(
            User.xp,
            User.position,
            User.rank_points,
            User.rank_season,
            User.rank_best,
            User.combo,
            User.miss_streak,
            User.rested_xp,
            User.rested_on,
        )
        .where(User.id == user_id)
        .with_for_update(key_share=True)
    ).one_or_none()
    if row is None:  # deleted while this request waited for it
        raise UserError("This account no longer exists.", 401)
    return row


def _hidden_mock(since: datetime) -> Any:
    """A mock question closed without an answer (left to run out, or on screen when the run was ended) since
    `since`, while the question was running for the player as a daily one: the run's summary kept its answer
    hidden, so the player neither answered it nor saw its answer."""
    return (Attempt.mode == "mock") & (Attempt.answer == {}) & (Attempt.submitted_at >= since)


def _season_start(now: datetime) -> datetime:
    return board_rules.madrid_midnight(board_rules.first_day("season", daily_rules.madrid_day(now)))


def seen_this_season(user_id: int, now: datetime, before: datetime) -> Select[tuple[int, datetime]]:
    """The questions the player had graded this season (`last_seen`'s rule) before `before`, with when last."""
    return (
        select(Attempt.question_id, func.max(Attempt.created_at).label("at"))
        .outerjoin(MockSession, MockSession.id == Attempt.session_id)
        .where(
            Attempt.user_id == user_id,
            Attempt.correct.is_not(None),
            func.coalesce(MockSession.started_at, Attempt.created_at) >= _season_start(now),
            Attempt.created_at < before,
        )
        .group_by(Attempt.question_id)
    )


def last_seen(
    db: DB,
    user_id: int,
    question_id: int,
    now: datetime,
    other_than: int | None = None,
    hidden_since: datetime | None = None,
    before: datetime | None = None,
) -> datetime | None:
    """When the player last had this question graded this season, in any mode: from then on they have seen
    its answer. A new season starts everyone afresh; a mock answer belongs to the season its run started in,
    as on the leaderboard. `hidden_since`: for a daily answer, when its question started running for the
    player (see `_hidden_mock`). `before`: what the call saw at that moment, for a result granted later (a daily
    at day close)."""
    season_start = _season_start(now)
    stmt = (
        select(func.max(Attempt.created_at))
        .outerjoin(MockSession, MockSession.id == Attempt.session_id)
        .where(
            Attempt.user_id == user_id,
            Attempt.question_id == question_id,
            Attempt.correct.is_not(None),
            func.coalesce(MockSession.started_at, Attempt.created_at) >= season_start,
        )
    )
    if other_than is not None:
        stmt = stmt.where(Attempt.id != other_than)
    if hidden_since is not None:
        stmt = stmt.where(~_hidden_mock(hidden_since))
    if before is not None:
        stmt = stmt.where(_answered_before(before))
    return db.scalar(stmt)


def _answered_before(before: datetime) -> Any:
    return func.coalesce(Attempt.submitted_at, Attempt.created_at) < before


def _options(db: DB, question: Question) -> tuple[int, int]:
    """A choice question's live options, and how many are right (what a hint on a multiple choice says)."""
    if question.answer_kind not in ("choice-one", "choice-many"):
        return 0, 0
    offered = AnswerOption.question_id == question.id, AnswerOption.retired.is_(False)
    key = db.get(AnswerKey, question.id)
    k = key.effective if key else None
    right = len(k["options"]) if k and k["kind"] == "choice" else 0
    return db.scalar(select(func.count()).where(*offered)) or 0, right


def priced(db: DB, question: Question) -> dict[str, Any]:
    """What a grant prices a question with: kept with a daily answered on a per-player day, so the grant at day
    close is what an instant one would have been, whatever the nightly recalibration or a retired option changes
    in between."""
    options, right_options = _options(db, question)
    return {"difficulty": question.difficulty, "options": options, "right_options": right_options}


def answered_today(
    db: DB,
    user_id: int,
    question_id: int,
    now: datetime,
    other_than: int | None = None,
    hidden_since: datetime | None = None,
    before: datetime | None = None,
) -> bool:
    """Whether the player already answered this question today (Madrid), graded or not: once a day pays.
    `hidden_since` and `before` as for `last_seen`."""
    start = board_rules.madrid_midnight(daily_rules.madrid_day(now))
    stmt = select(func.count()).where(
        Attempt.user_id == user_id,
        Attempt.question_id == question_id,
        Attempt.submitted_at.is_not(None) | (Attempt.mode == "practice"),
        Attempt.created_at
        >= start,  # when it was shown: a night job closing yesterday's isn't answering today
    )
    if other_than is not None:
        stmt = stmt.where(Attempt.id != other_than)
    if hidden_since is not None:
        stmt = stmt.where(~_hidden_mock(hidden_since))
    if before is not None:
        stmt = stmt.where(_answered_before(before))
    return bool(db.scalar(stmt))


def first_wins(db: DB, user_id: int, now: datetime) -> int:
    """Right answers already paid on `now`'s day (Madrid), outside live quizzes, in the order they were granted: a
    daily waiting for day close holds no slot. The answer being scored has no XP yet."""
    day = daily_rules.madrid_day(now)
    start, end = board_rules.madrid_midnight(day), board_rules.madrid_midnight(day + timedelta(days=1))
    return (
        db.scalar(
            select(func.count()).where(
                Attempt.user_id == user_id,
                Attempt.mode != "live",
                Attempt.correct.is_(True),
                Attempt.late.is_not(True),  # right but late earned a wrong answer's XP, no first win
                Attempt.xp > 0,
                func.coalesce(Attempt.submitted_at, Attempt.created_at) >= start,
                func.coalesce(Attempt.submitted_at, Attempt.created_at) < end,  # a day settled late
            )
        )
        or 0
    )


def _crit(db: DB, user_id: int, question_id: int, now: datetime) -> bool:
    """A rare double, fixed per player, question and day on the server: answering again can't reroll it."""
    salt = hints.salt(db)
    message = f"crit:{user_id}:{question_id}:{daily_rules.madrid_day(now)}".encode()
    roll = int.from_bytes(hmac.new(salt, message, hashlib.sha256).digest()[:8], "big") / 2**64
    return roll < rules.CRIT_CHANCE


@dataclass
class Grant:
    xp: int
    lp: float
    bonuses: dict[str, int] = field(default_factory=dict)
    combo: int = 0  # right answers in a row, this one included
    comeback: bool = False
    cushioned: bool = False
    points: float = 0.0
    promoted: bool = False  # into a division not reached before this season
    rose: bool = False  # back up into a division reached before
    demoted: bool = False
    level: int = 0  # account level; 0 when not looked up (a mock summary item): no standing shown
    level_up: bool = False
    left: bool = False  # granted after the player left its season: the new season's rank stayed put


def grant(
    db: DB,
    user_id: int,
    question: Question,
    mode: str,
    correct: bool | None,
    now: datetime,
    *,
    answered: bool = True,
    hint: bool = False,
    repeat: bool = False,
    late: bool = False,
    again_today: bool = False,
    passed: bool = False,
    ranked: bool = True,
    season_at: datetime | None = None,
    played_on: date | None = None,
    as_of: datetime | None = None,
    price: dict[str, Any] | None = None,
) -> Grant:
    """Score one answer in both currencies: LP for the rank, XP for the account level. The caller stores
    `xp` and `lp` on the attempt and commits. Live answers are a table's: XP only, and they leave the
    player's combo and bad run alone. `ranked=False` (a mock replay) moves no LP either. Only first-time
    daily and mock answers count towards a bad run, so it can't be staged with cheap practice misses. Practice
    earns XP only (rank.K). `season_at` is when the play started (a daily's start, a mock run's): an answer
    belongs to that season's rank, as on the leaderboard, unless the player has already moved on to the next.
    `played_on` is the day the question was shown: a daily started at 23:59 and answered after midnight played
    its own day, for rested XP. `as_of`: when a result granted later (a daily at day close) was answered: its
    day's first wins, the streak, the crit roll and the rested bank are as of then; combo, bad run and first-win
    slots follow the grant order. Every grant first settles the player's due daily results (`settle_due`), so
    they are granted before anything played after them; a result whose season the player has already left moves
    XP and is priced for that season's board, but leaves the new season's rank alone. `price`: `priced` as it
    stood at the answer, for a grant made later."""
    state = lock(db, user_id)
    if not _settling.get() and _has_due(db, user_id, now):
        settle_due(db, user_id, now)
        state = lock(db, user_id)
    when = as_of or now
    season = rank_rules.season_of(season_at or now)
    left = as_of is not None and season < state.rank_season
    if season < state.rank_season:
        season = rank_rules.season_of(now)
    at = now if season == rank_rules.season_of(now) else season_at or now
    points = rank_rules.current_points(state.rank_points, state.rank_season, state.position, at)
    best = state.rank_best if state.rank_season == season else rank_rules.division_of(points)
    ranked = ranked and not left
    live = mode == "live"
    right = bool(correct) and not late and not passed
    run = mode in ("daily", "mock") and ranked and not repeat and not again_today
    price = price or priced(db, question)
    options, right_options, difficulty = price["options"], price["right_options"], price["difficulty"]
    lp = rank_rules.lp_award(
        correct,
        points,
        difficulty,
        mode,
        area=question.area,
        answer_kind=question.answer_kind,
        options=options,
        right_options=right_options,
        hint=hint,
        repeat=repeat,
        late=late,
        passed=passed,
        again_today=again_today,
        miss_streak=state.miss_streak if run else 0,
    )
    if not ranked and not left:
        lp = rank_rules.Lp(0.0)
    day = played_on or daily_rules.madrid_day(when)
    bank = rested(db, state.rested_xp, state.rested_on, user_id, when, day)
    earned = rules.xp_award(
        correct,
        difficulty,
        mode,
        answered=answered,
        hint=hint,
        repeat=repeat,
        late=late,
        passed=passed,
        again_today=again_today,
        first_win=right and not live and first_wins(db, user_id, when) < rules.FIRST_WINS,
        combo=0 if live else state.combo,
        streak_days=streak_days(db, user_id, when),
        crit=right and not again_today and _crit(db, user_id, question.id, when),
        rested=bank,
    )
    combo, miss = state.combo, state.miss_streak
    if not live and correct is not None and not again_today:
        combo = min(combo + 1, COUNTER_CAP) if right else 0  # only up to 5 and 3 matter
    if run:
        miss = min(rank_rules.next_miss_streak(miss, correct, passed, late), COUNTER_CAP)
    if left:  # for the season's board only: the rank it was played for has already been reset
        after, division = points, rank_rules.division_of(points)
    else:
        after = max(0.0, round(points + lp.amount, 2))
        division = rank_rules.division_of(after)
    values: dict[str, Any] = {
        "xp": User.xp + earned.amount,
        "rank_points": after,
        "rank_season": season,
        "rank_best": max(best, division),
        "combo": combo,
        "miss_streak": miss,
    }
    if answered:  # a question left to run out (closed by the nightly job) isn't playing: the rested days stay
        values |= {
            "rested_xp": bank - earned.bonuses.get("rested", 0),
            "rested_on": max(day, state.rested_on or day),
        }
    xp_after = db.execute(
        update(User).where(User.id == user_id).values(values).returning(User.xp)
    ).scalar_one()
    level = rules.account_level(xp_after)[0]
    return Grant(
        xp=earned.amount,
        lp=round(lp.amount, 2) if left else round(after - points, 2),
        bonuses=earned.bonuses,
        combo=combo if right else 0,
        comeback=lp.comeback,
        cushioned=lp.cushioned,
        points=after,
        promoted=division > best,
        rose=rank_rules.division_of(points) < division <= best,
        demoted=division < rank_rules.division_of(points),
        level=level,
        level_up=level > rules.account_level(state.xp)[0],
        left=left,
    )


_settling: ContextVar[bool] = ContextVar("settling", default=False)


@contextmanager
def settling() -> Iterator[None]:
    """Grants made inside don't settle first: they are the settle's own (or a run-out closed with it)."""
    token = _settling.set(True)
    try:
        yield
    finally:
        _settling.reset(token)


def reward(g: Grant) -> dict[str, Any]:
    """What a grant paid on top, kept on a result granted at day close for the card that reveals it."""
    return {
        "bonuses": g.bonuses,
        "promoted": g.promoted,
        "rose": g.rose,
        "demoted": g.demoted,
        "level_up": g.level if g.level_up else None,
    }


def due(now: datetime) -> tuple[Any, Any]:
    """What `settle_due` has to do: daily results whose Madrid day has closed, and dailies left to run out that
    are still open."""
    return (
        and_(PENDING, Attempt.released_at <= now),
        and_(DAILY, Attempt.submitted_at.is_(None), Attempt.deadline_at < now - daily_rules.GRACE),
    )


def _has_due(db: DB, user_id: int, now: datetime) -> bool:
    released, ran_out = due(now)
    return bool(
        db.scalar(
            select(
                or_(
                    exists().where(released, Attempt.user_id == user_id),
                    exists().where(ran_out, Attempt.user_id == user_id),
                )
            )
        )
    )


_REPORTED: set[int] = set()


def _report(attempt_id: int) -> None:
    """A row that keeps failing is tried on every request that probes for due results: its traceback is logged
    once per process, the repeats in a line (`ifs-tests settle` lists the stuck ones, runbook 5.1)."""
    if attempt_id in _REPORTED:
        log.warning("settle: attempt %s fails again", attempt_id)
        return
    if len(_REPORTED) > 1000:
        _REPORTED.clear()
    _REPORTED.add(attempt_id)
    log.exception("settle: attempt %s", attempt_id)


@dataclass
class Settled:
    closed: int = 0  # dailies left to run out, closed now
    settled: int = 0  # results granted
    failed: int = 0  # rows that raised: rolled back to be tried again


def settle_due(db: DB, user_id: int, now: datetime) -> Settled:
    """Grant the player's daily results whose Madrid day has closed (ADR 0010), as of their answers and in that
    order, inside the caller's transaction: the caller holds the player's lock, then this takes the attempts,
    the order answering and deleting an account take. Run-outs still open are closed first; those of a shared
    day are charged last, as the nightly job would have charged them after the results it had granted. Each row
    has its own savepoint: one that raises is logged, rolled back and left for the next call, and never fails
    the caller."""
    from . import daily  # daily scores through this module

    out = Settled()
    with settling():
        open_runs = daily.run_outs(db, user_id, now)
        for a in open_runs:
            if a.released_at is not None:
                daily.close_run_out(db, a, now)
                out.closed += 1
        db.flush()
        rows = db.scalars(
            select(Attempt)
            .where(PENDING, Attempt.user_id == user_id, Attempt.released_at <= now)
            .order_by(AS_OF, Attempt.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        for a in rows:
            if a.xp or a.lp:  # started under this release, granted by the previous one after a rollback
                a.settled_at, a.reward = a.submitted_at, None
                db.flush()
                log.warning("settle: attempt %s granted by the previous release", a.id)
                continue
            try:
                with db.begin_nested():
                    g = _settle(db, a, now, daily)
                    a.xp, a.lp, a.settled_at, a.reward = g.xp, g.lp, now, reward(g)
                    db.flush()
            except Exception:
                _report(a.id)
                out.failed += 1
                continue
            if g.left:
                season = rank_rules.season_of(a.created_at)
                log.warning("grant: attempt %s settled into season %s the player has left", a.id, season)
            out.settled += 1
        for a in open_runs:
            if a.released_at is not None:
                continue
            try:
                with db.begin_nested():
                    daily.close_run_out(db, a, now)
                    daily.charge_run_out(db, a, now)
            except Exception:
                log.exception("settle: run-out %s", a.id)
                out.failed += 1
                continue
            out.closed += 1
    return out


def _settle(db: DB, a: Attempt, now: datetime, daily: Any) -> Grant:
    """One pending daily's grant: what `daily.answer` (or `daily.charge_run_out` for a run-out) would have granted
    at the answer, with combo, bad run and first-win slots as they stand now."""
    assert a.day is not None and a.submitted_at is not None and a.deadline_at is not None  # noqa: S101 - PENDING
    q = db.get_one(Question, a.question_id)
    answered = a.answer != {}
    as_of = a.submitted_at if answered else a.deadline_at
    hidden = daily.running_since(db, a.day, a.area, q.id)
    price = (a.reward or {}).get("priced")
    seen = last_seen(db, a.user_id, q.id, as_of, other_than=a.id, hidden_since=hidden, before=as_of)
    if not answered:
        return grant(
            db,
            a.user_id,
            q,
            "daily",
            a.correct,
            now,
            answered=False,
            late=True,
            repeat=seen is not None,
            season_at=a.created_at,
            as_of=as_of,
            price=price,
        )
    return grant(
        db,
        a.user_id,
        q,
        "daily",
        a.correct,
        now,
        late=bool(a.late),
        repeat=seen is not None,
        passed=a.passed,
        hint=a.hint_used,
        again_today=answered_today(
            db, a.user_id, q.id, as_of, other_than=a.id, hidden_since=hidden, before=as_of
        ),
        season_at=a.created_at,
        played_on=a.day,
        as_of=as_of,
        price=price,
    )


def stored(db: DB, user_id: int, a: Attempt) -> Grant:
    """An attempt scored earlier, as a reload shows it: its XP and LP, and where the player stands now."""
    row = db.execute(select(User.xp, User.rank_points).where(User.id == user_id)).one_or_none()
    if row is None:  # deleted since this request's answer was saved
        raise UserError("This account no longer exists.", 401)
    xp, points = row
    return Grant(xp=a.xp, lp=a.lp, points=points, level=rules.account_level(xp)[0])


def recalibrate(db: DB) -> int:
    """Nightly: move each graded question's difficulty towards how people actually answer it. Only each
    person's first answer in time counts, so nobody can drag a question's difficulty by answering it again."""
    first = (
        select(Attempt.question_id, Attempt.correct)
        # A live answer is a table's, shared by everyone at it: it says little about how one person does.
        .where(Attempt.correct.is_not(None), Attempt.late.is_not(True), Attempt.mode != "live", REVEALED)
        .distinct(Attempt.user_id, Attempt.question_id)
        .order_by(Attempt.user_id, Attempt.question_id, Attempt.created_at, Attempt.id)
        .subquery()
    )
    stats = db.execute(
        select(
            Question.id,
            Question.answer_kind,
            Question.time_s,
            Question.difficulty,
            func.count(),
            func.count(case((first.c.correct.is_(True), 1))),
        )
        .join(first, first.c.question_id == Question.id)
        .where(Question.graded)
        .group_by(Question.id)
    )
    changed = 0
    for qid, kind, time_s, current, answered, right in stats:
        new = rules.difficulty(kind, time_s, answered, right)
        if new != current:
            db.execute(update(Question).where(Question.id == qid).values(difficulty=new))
            changed += 1
    return changed
