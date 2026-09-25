"""Scoring answers (LP for the rank, XP for the account level) and keeping question difficulty in line with how
people do."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import Row, case, func, select, update
from sqlalchemy.orm import Session as DB

from ..db.models import AnswerOption, Attempt, MockSession, Question, User
from ..domain import daily as daily_rules
from ..domain import leaderboard as board_rules
from ..domain import rank as rank_rules
from ..domain import xp as rules
from . import hints, streaks
from .errors import UserError

COUNTER_CAP = 99  # combo and bad-run counters are SMALLINT; nothing past a handful changes the score


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


def last_seen(
    db: DB, user_id: int, question_id: int, now: datetime, other_than: int | None = None
) -> datetime | None:
    """When the player last had this question graded this season, in any mode: from then on they have seen
    its answer. A new season starts everyone afresh; a mock answer belongs to the season its run started in,
    as on the leaderboard."""
    season_start = board_rules.madrid_midnight(board_rules.first_day("season", daily_rules.madrid_day(now)))
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
    return db.scalar(stmt)


def _options(db: DB, question: Question) -> int:
    if question.answer_kind != "choice-one":
        return 0
    offered = AnswerOption.question_id == question.id, AnswerOption.retired.is_(False)
    return db.scalar(select(func.count()).where(*offered)) or 0


def answered_today(
    db: DB, user_id: int, question_id: int, now: datetime, other_than: int | None = None
) -> bool:
    """Whether the player already answered this question today (Madrid), graded or not: once a day pays."""
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
    return bool(db.scalar(stmt))


def first_wins(db: DB, user_id: int, now: datetime) -> int:
    """Right answers already paid today (Madrid), outside live quizzes. The answer being scored has no XP yet."""
    start = board_rules.madrid_midnight(daily_rules.madrid_day(now))
    return (
        db.scalar(
            select(func.count()).where(
                Attempt.user_id == user_id,
                Attempt.mode != "live",
                Attempt.correct.is_(True),
                Attempt.late.is_not(True),  # right but late earned a wrong answer's XP, no first win
                Attempt.xp > 0,
                func.coalesce(Attempt.submitted_at, Attempt.created_at) >= start,
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
) -> Grant:
    """Score one answer in both currencies: LP for the rank, XP for the account level. The caller stores
    `xp` and `lp` on the attempt and commits. Live answers are a table's: XP only, and they leave the
    player's combo and bad run alone. `ranked=False` (a mock replay) moves no LP either. Only first-time
    daily and mock answers count towards a bad run, so it can't be staged with cheap practice misses. Practice
    earns XP only (rank.K). `season_at` is when the play started (a daily's start, a mock run's): an answer
    belongs to that season's rank, as on the leaderboard, unless the player has already moved on to the next.
    `played_on` is the day the question was shown: a daily started at 23:59 and answered after midnight played
    its own day, for rested XP."""
    state = lock(db, user_id)
    season = rank_rules.season_of(season_at or now)
    if season < state.rank_season:
        season = rank_rules.season_of(now)
    at = now if season == rank_rules.season_of(now) else season_at or now
    points = rank_rules.current_points(state.rank_points, state.rank_season, state.position, at)
    best = state.rank_best if state.rank_season == season else rank_rules.division_of(points)
    live = mode == "live"
    right = bool(correct) and not late and not passed
    run = mode in ("daily", "mock") and ranked and not repeat and not again_today
    options = _options(db, question)
    lp = rank_rules.lp_award(
        correct,
        points,
        question.difficulty,
        mode,
        area=question.area,
        answer_kind=question.answer_kind,
        options=options,
        hint=hint,
        repeat=repeat,
        late=late,
        passed=passed,
        again_today=again_today,
        miss_streak=state.miss_streak if run else 0,
    )
    if not ranked:
        lp = rank_rules.Lp(0.0)
    day = played_on or daily_rules.madrid_day(now)
    bank = rested(db, state.rested_xp, state.rested_on, user_id, now, day)
    earned = rules.xp_award(
        correct,
        question.difficulty,
        mode,
        answered=answered,
        hint=hint,
        repeat=repeat,
        late=late,
        passed=passed,
        again_today=again_today,
        first_win=right and not live and first_wins(db, user_id, now) < rules.FIRST_WINS,
        combo=0 if live else state.combo,
        streak_days=streak_days(db, user_id, now),
        crit=right and not again_today and _crit(db, user_id, question.id, now),
        rested=bank,
    )
    combo, miss = state.combo, state.miss_streak
    if not live and correct is not None and not again_today:
        combo = min(combo + 1, COUNTER_CAP) if right else 0  # only up to 5 and 3 matter
    if run:
        miss = min(rank_rules.next_miss_streak(miss, correct, passed, late), COUNTER_CAP)
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
        lp=round(after - points, 2),
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
        .where(Attempt.correct.is_not(None), Attempt.late.is_not(True), Attempt.mode != "live")
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
