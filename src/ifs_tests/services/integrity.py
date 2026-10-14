"""The integrity report (docs/guides/integrity-report.md): read-only forensics over ranked play, printed with
pseudonyms. `fetch` reads everything in one read-only transaction with plain SELECTs; every check then runs on
that snapshot with no connection open. Nothing is stored and nothing is decided: a person reads the report."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, case, func, or_, select
from sqlalchemy.orm import Session as DB

from ..db.models import (
    DAILY,
    AnswerKey,
    AnswerOption,
    Attempt,
    AuditLog,
    DailyQuestion,
    Invite,
    MockSession,
    Question,
    User,
)
from ..domain import grading
from ..domain import integrity as rules
from ..domain.daily import madrid_day
from ..domain.leaderboard import first_day, madrid_midnight
from ..domain.mock import season
from ..settings import IntegritySettings
from . import integrity_canary

ELEC_GROUP = ("Electronics", "Tractive System", "Driverless")
TOP_K = 10


@dataclass(frozen=True)
class Window:
    since: date  # inclusive Madrid day (a daily's day, a mock run's start)
    until: date  # exclusive: plays submitted before its Madrid midnight


def thresholds(
    s: IntegritySettings, *, fixed_rank: float | None = None, split: date | None = None
) -> rules.Thresholds:
    return rules.Thresholds(
        z=s.z,
        min_group=s.min_group,
        permutation_rounds=s.permutation_rounds,
        bootstrap_rounds=s.bootstrap_rounds,
        seed=s.seed,
        fixed_rank=s.fixed_rank if fixed_rank is None else fixed_rank,
        shrink_m=s.shrink_m,
        min_n=s.min_n,
        follow_within=timedelta(minutes=s.follow_within_min),
        follow_min=s.follow_min,
        follow_z=s.follow_z,
        follow_relay_z=s.follow_relay_z,
        reading_floor_s=s.reading_floor_s,
        reading_cps=s.reading_cps,
        below_floor_share=s.below_floor_share,
        narrow_sd_log=s.narrow_sd_log,
        flat_corr=s.flat_corr,
        hard_residual_z=s.hard_residual_z,
        away_z=s.away_z,
        upstream_min=s.upstream_min,
        upstream_z=s.upstream_z,
        split=split,
        canary_alpha=s.canary_alpha,
        canary_beta=s.canary_beta,
        canary_follow=s.canary_follow,
        canary_control_alpha=s.canary_control_alpha,
        canary_nudge=s.canary_nudge,
        canary_m=s.canary_m,
        away_undeclared_s=s.away_undeclared_s,
    )


@dataclass(frozen=True)
class UserInfo:
    vertical: str | None
    invite_vertical: str | None
    position: str
    rank_points: float
    rank_season: int
    active: bool


@dataclass(frozen=True)
class Correction:
    key: dict[str, Any]
    override: dict[str, Any]
    corrected_at: datetime | None  # the latest 'question.answer' in the audit log


@dataclass
class Snapshot:
    """Everything the report needs, fetched in one read-only transaction."""

    window: Window
    season_start: datetime
    users: dict[int, UserInfo]
    questions: dict[int, rules.QuestionInfo]
    question_labels: dict[int, tuple[bool, str | None]]  # labels_reviewed, topic
    history: dict[int, list[rules.Row]]  # per user, every attempt (any mode, any season), in grading order
    drawn_at: dict[tuple[date, str], datetime]
    per_player: rules.PerPlayer | None  # from the switch: when each question's first daily started that day
    keys: dict[int, Correction]
    answers: dict[int, dict[str, Any]]  # attempt id -> answer, daily and mock answers in the window
    repositioned: frozenset[int] = (
        frozenset()
    )  # users whose position an admin changed this season (audit log)
    rules_from: date | None = None  # IFS_RULES_1B_FROM: signals exist from its Madrid midnight
    signals: integrity_canary.Signals | None = None
    cache: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def end(self) -> datetime:
        return madrid_midnight(self.window.until)

    @property
    def season(self) -> int:
        return season(self.window.until - timedelta(days=1))


def _window_clause(window: Window) -> ColumnElement[bool]:
    """Daily and mock attempts from `since` (a daily's day, a mock run's start); needs MockSession joined."""
    return or_(
        and_(Attempt.mode == "daily", Attempt.day >= window.since),
        and_(Attempt.mode == "mock", MockSession.started_at >= madrid_midnight(window.since)),
    )


def fetch(db: DB, window: Window, checks: frozenset[str], rules_from: date | None = None) -> Snapshot:
    """Runs inside the caller's read-only transaction; every statement is a SELECT. The cohort: everyone with a
    ranked play this season before `until`. Their whole history comes along (for repeats and pre-seen questions);
    stored answers, corrected keys and signal totals only when a check needs them."""
    season_start = madrid_midnight(first_day("season", window.until - timedelta(days=1)))
    end = madrid_midnight(window.until)
    players = (
        select(Attempt.user_id)
        .outerjoin(MockSession, MockSession.id == Attempt.session_id)
        .where(
            Attempt.mode.in_(("daily", "mock")),
            Attempt.submitted_at.is_not(None),
            Attempt.submitted_at < end,
            func.coalesce(MockSession.started_at, Attempt.created_at) >= season_start,
        )
        .distinct()
        .cte("players")
    )
    in_cohort = select(players.c.user_id)

    invited = (
        select(Invite.used_by, func.min(Invite.vertical).label("vertical"))
        .where(Invite.used_by.is_not(None))
        .group_by(Invite.used_by)
        .cte("invited")
    )
    users = {
        uid: UserInfo(vertical, invite_vertical, position, float(points), rank_season, status == "active")
        for uid, vertical, position, points, rank_season, status, invite_vertical in db.execute(
            select(
                User.id,
                User.vertical,
                User.position,
                User.rank_points,
                User.rank_season,
                User.status,
                invited.c.vertical,
            )
            .outerjoin(invited, invited.c.used_by == User.id)
            .where(User.id.in_(in_cohort))
        )
    }

    live = (
        select(
            AnswerOption.question_id,
            func.count().label("n"),
            func.coalesce(func.sum(func.length(AnswerOption.text)), 0).label("chars"),
        )
        .where(AnswerOption.retired.is_(False))
        .group_by(AnswerOption.question_id)
        .cte("live_options")
    )
    effective = case(
        (func.jsonb_typeof(AnswerKey.override) == "object", AnswerKey.override), else_=AnswerKey.key
    )
    right_options = case(
        (
            func.jsonb_extract_path_text(effective, "kind") == "choice",
            func.jsonb_array_length(func.jsonb_extract_path(effective, "options")),
        ),
        else_=0,
    )
    questions: dict[int, rules.QuestionInfo] = {}
    labels: dict[int, tuple[bool, str | None]] = {}
    for (
        qid,
        area,
        kind,
        difficulty,
        graded,
        images,
        chars,
        options,
        option_chars,
        right,
        reviewed,
        topic,
    ) in db.execute(
        select(
            Question.id,
            Question.area,
            Question.answer_kind,
            Question.difficulty,
            Question.graded,
            func.cardinality(Question.images) > 0,
            func.length(Question.text),
            func.coalesce(live.c.n, 0),
            func.coalesce(live.c.chars, 0),
            func.coalesce(right_options, 0),
            Question.labels_reviewed,
            Question.topic,
        )
        .outerjoin(live, live.c.question_id == Question.id)
        .outerjoin(AnswerKey, AnswerKey.question_id == Question.id)
    ):
        choice = kind in ("choice-one", "choice-many")
        questions[qid] = rules.QuestionInfo(
            area=area,
            answer_kind=kind,
            difficulty=difficulty,
            options=options if choice else 0,
            right_options=right if choice else 0,
            text_len=(chars or 0) + (option_chars or 0),
            graded=graded,
            has_images=bool(images),
        )
        labels[qid] = (reviewed, topic)

    history: dict[int, list[rules.Row]] = defaultdict(list)
    for r in db.execute(
        select(
            Attempt.id,
            Attempt.user_id,
            Attempt.question_id,
            Attempt.mode,
            Attempt.created_at,
            Attempt.submitted_at,
            Attempt.correct,
            (Attempt.answer != {}).label("answered"),
            Attempt.day,
            Attempt.area,
            MockSession.started_at,
            MockSession.counted,
            Attempt.late,
            Attempt.passed,
            Attempt.hint_used,
            Attempt.lp,
            Attempt.released_at,
            Attempt.settled_at,
            Attempt.deadline_at,
        )
        .outerjoin(MockSession, MockSession.id == Attempt.session_id)
        .where(Attempt.user_id.in_(in_cohort))
    ):
        history[r.user_id].append(
            rules.Row(
                id=r.id,
                question_id=r.question_id,
                mode=r.mode,
                created_at=r.created_at,
                submitted_at=r.submitted_at,
                correct=r.correct,
                answered=bool(r.answered),
                day=r.day,
                area=r.area,
                run_started_at=r.started_at,
                counted=r.counted is not False,
                late=bool(r.late),
                passed=r.passed,
                hint_used=r.hint_used,
                lp=float(r.lp),
                released_at=r.released_at,
                settled_at=r.settled_at,
                deadline_at=r.deadline_at,
            )
        )
    for rows in history.values():
        rows.sort(key=rules.grading_order)

    drawn_at = {
        (day, area): at
        for day, area, at in db.execute(
            select(DailyQuestion.day, DailyQuestion.area, DailyQuestion.drawn_at).where(
                DailyQuestion.drawn_at.is_not(None)
            )
        )
    }

    per_player = None
    if rules_from is not None:
        per_player = rules.PerPlayer(
            rules_from,
            {
                (day, qid): at
                for day, qid, at in db.execute(
                    select(Attempt.day, Attempt.question_id, func.min(Attempt.created_at))
                    .where(DAILY, Attempt.day >= rules_from)
                    .group_by(Attempt.day, Attempt.question_id)
                )
            },
        )

    answers: dict[int, dict[str, Any]] = {}
    if checks & {"follow", "upstream-key", "canary", "people", "split"}:
        answers = {
            aid: answer
            for aid, answer in db.execute(
                select(Attempt.id, Attempt.answer)
                .outerjoin(MockSession, MockSession.id == Attempt.session_id)
                .where(
                    Attempt.user_id.in_(in_cohort),
                    Attempt.answer != {},
                    Attempt.submitted_at < end,
                    _window_clause(window),
                )
            )
        }

    signals = None
    if rules_from is not None and checks & {"canary", "people", "split"}:
        signals = integrity_canary.fetch_signals(
            db, in_cohort, _window_clause(window), rules_from, end, effective
        )

    repositioned: frozenset[int] = frozenset()
    if checks & {"elo", "fidelity"}:
        repositioned = frozenset(
            int(target.removeprefix("user:"))
            for (target,) in db.execute(
                select(AuditLog.target)
                .where(
                    AuditLog.action == "user.update",
                    AuditLog.details.has_key("position"),
                    AuditLog.at >= season_start,
                    AuditLog.at < end,
                    AuditLog.target.like("user:%"),
                )
                .distinct()
            )
        )

    corrections: dict[int, Correction] = {}
    if checks & {"upstream-key", "people"}:
        corrected = (
            select(AuditLog.target, func.max(AuditLog.at).label("at"))
            .where(AuditLog.action == "question.answer")
            .group_by(AuditLog.target)
            .cte("corrected")
        )
        for qid, key, override, at in db.execute(
            select(AnswerKey.question_id, AnswerKey.key, AnswerKey.override, corrected.c.at)
            .outerjoin(corrected, corrected.c.target == func.concat("question:", AnswerKey.question_id))
            .where(
                func.jsonb_typeof(AnswerKey.override) == "object",
                func.jsonb_typeof(AnswerKey.key) == "object",
                AnswerKey.key != AnswerKey.override,
            )
        ):
            corrections[qid] = Correction(key, override, at)

    return Snapshot(
        window=window,
        season_start=season_start,
        users=users,
        questions=questions,
        question_labels=labels,
        history=dict(history),
        drawn_at=drawn_at,
        per_player=per_player,
        keys=corrections,
        answers=answers,
        repositioned=repositioned,
        rules_from=rules_from,
        signals=signals,
    )


# --- shared derivations (cached on the snapshot) ---------------------------------------------------------------


def _cached(s: Snapshot, name: str, make: Callable[[], Any]) -> Any:
    if name not in s.cache:
        s.cache[name] = make()
    return s.cache[name]


def _by_question(s: Snapshot, uid: int) -> dict[int, list[rules.Row]]:
    def make() -> dict[int, list[rules.Row]]:
        out: dict[int, list[rules.Row]] = defaultdict(list)
        for r in s.history.get(uid, []):
            out[r.question_id].append(r)
        return out

    return _cached(s, f"byq:{uid}", make)  # type: ignore[no-any-return]


def _right(r: rules.Row) -> bool:
    return bool(r.correct) and not r.late and not r.passed


def _in_window(s: Snapshot, r: rules.Row) -> bool:
    if r.submitted_at is None or r.submitted_at >= s.end:
        return False
    if r.mode == "daily":
        return (r.day or madrid_day(r.created_at)) >= s.window.since
    if r.mode == "mock":
        return r.run_started_at is not None and madrid_day(r.run_started_at) >= s.window.since
    return False


def ranked_plays(s: Snapshot) -> dict[int, list[tuple[rules.Row, rules.Play]]]:
    """Each player's daily and mock plays this season in grading order, as grant priced them (uncounted runs
    included: they move nothing but are part of the walk)."""

    def make() -> dict[int, list[tuple[rules.Row, rules.Play]]]:
        out = {}
        for uid, rows in s.history.items():
            byq = _by_question(s, uid)
            plays = sorted(
                (
                    r
                    for r in rows
                    if r.mode in ("daily", "mock")
                    and r.submitted_at is not None
                    and not rules.pending(r)  # not granted yet: nothing to replay
                    and rules.season_anchor(r) >= s.season_start
                    and r.question_id in s.questions
                ),
                key=rules.grading_order,
            )
            out[uid] = [
                (
                    r,
                    rules.to_play(
                        r, byq[r.question_id], s.drawn_at, s.questions[r.question_id], s.per_player
                    ),
                )
                for r in plays
            ]
        return out

    return _cached(s, "ranked", make)  # type: ignore[no-any-return]


def miss0(s: Snapshot, uid: int) -> int:
    """The bad run the player brought into this season: grant never resets it at the September rollover."""

    def make() -> int:
        byq = _by_question(s, uid)
        return rules.miss_after(
            rules.to_play(r, byq[r.question_id], s.drawn_at, s.questions[r.question_id], s.per_player)
            for r in s.history.get(uid, [])
            if r.mode in ("daily", "mock")
            and r.submitted_at is not None
            and rules.season_anchor(r) < s.season_start
            and r.question_id in s.questions
        )

    return _cached(s, f"miss0:{uid}", make)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class Item:
    """A counted ranked play in the window."""

    row: rules.Row
    play: rules.Play
    lp_fixed: float
    pre_seen: bool


def _items(s: Snapshot, t: rules.Thresholds) -> dict[int, list[Item]]:
    def make() -> dict[int, list[Item]]:
        out: dict[int, list[Item]] = {}
        for uid, plays in ranked_plays(s).items():
            fixed = rules.replay_lp([p for _, p in plays], 0.0, fixed=t.fixed_rank, miss0=miss0(s, uid))
            byq = _by_question(s, uid)
            items = [
                Item(r, p, lp, rules.pre_seen(r, byq[r.question_id], s.drawn_at, s.per_player))
                for (r, p), lp in zip(plays, fixed, strict=True)
                if p.ranked and _in_window(s, r)
            ]
            if items:
                out[uid] = items
        return out

    return _cached(s, f"items:{hash(t)}", make)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class Baseline:
    per_question: dict[int, tuple[int, int]]  # right, n over each person's first answer
    first: dict[tuple[int, int], bool]  # (user, question) -> right on the first answer
    by_difficulty: dict[int, float]


def _baseline(s: Snapshot) -> Baseline:
    """Each person's first graded answer to each question (live answers are a table's: left out), before the
    window ends."""

    def make() -> Baseline:
        first: dict[tuple[int, int], bool] = {}
        for uid, rows in s.history.items():
            for r in sorted(rows, key=lambda r: (r.created_at, r.id)):
                if (
                    (uid, r.question_id) in first
                    or r.correct is None
                    or r.mode == "live"
                    or not r.answered
                    or rules.graded_at(r) >= s.end
                ):
                    continue
                first[(uid, r.question_id)] = _right(r)
        per_q: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        for (_, qid), y in first.items():
            per_q[qid][0] += y
            per_q[qid][1] += 1
        by_difficulty = rules.difficulty_baseline(
            (s.questions[qid].difficulty, y) for (_, qid), y in first.items() if qid in s.questions
        )
        return Baseline({q: (r, n) for q, (r, n) in per_q.items()}, first, by_difficulty)

    return _cached(s, "baseline", make)  # type: ignore[no-any-return]


def _peer(s: Snapshot, t: rules.Thresholds, uid: int, qid: int) -> float:
    b = _baseline(s)
    right, n = b.per_question.get(qid, (0, 0))
    p_d = b.by_difficulty.get(s.questions[qid].difficulty, 0.5)
    y = b.first.get((uid, qid))
    if y is None:  # not among the first answers: nothing of theirs to leave out
        return rules.peer_rate(right, n + 1, False, p_d, t.shrink_m)
    return rules.peer_rate(right, n, y, p_d, t.shrink_m)


def _first_seen(items: Iterable[Item]) -> list[Item]:
    return [i for i in items if not i.pre_seen and i.row.answered]


# --- fidelity --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fidelity:
    plays: int
    reproduced: int
    players: int
    mismatched: frozenset[int]
    unknown_start: int  # players whose rank belongs to another season by now
    repositioned: int  # of the mismatched, those whose position an admin changed this season

    @property
    def share(self) -> float | None:
        return self.reproduced / self.plays if self.plays else None


def fidelity(s: Snapshot) -> Fidelity:
    """Replay every player's season from where their stored LP says they started, and compare per play."""

    def make() -> Fidelity:
        plays = reproduced = players = unknown = 0
        mismatched = set()
        for uid, pairs in ranked_plays(s).items():
            info = s.users.get(uid)
            if not pairs or info is None:
                continue
            if info.rank_season != s.season:
                unknown += 1
                continue
            spent = sum(
                r.lp
                for r in s.history[uid]
                if rules.graded_at(r) != rules.NEVER and rules.season_anchor(r) >= s.season_start
            )
            start = round(info.rank_points - spent, 2)
            replayed = rules.replay_lp([p for _, p in pairs], start, miss0=miss0(s, uid))
            ok = sum(abs(a - p.lp) < 0.005 for a, (_, p) in zip(replayed, pairs, strict=True))
            players += 1
            plays += len(pairs)
            reproduced += ok
            if ok < len(pairs):
                mismatched.add(uid)
        return Fidelity(
            plays, reproduced, players, frozenset(mismatched), unknown, len(mismatched & s.repositioned)
        )

    return _cached(s, "fidelity", make)  # type: ignore[no-any-return]


# --- 0a Elo artefact -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupRow:
    by: str  # "vertical" or "position"
    group: str
    people: int
    plays: int
    lp_stored: float | None  # per play
    lp_fixed: float | None
    mean_accuracy: float | None
    mean_interval: tuple[float, float] | None
    right: int
    n: int
    wilson: tuple[float, float]
    pre_seen: int
    mismatched: int  # players whose replay doesn't reproduce their stored LP


@dataclass(frozen=True)
class ElecStats:
    stored: float
    fixed: float
    right: int
    n: int
    pre_seen: int


def _elec(s: Snapshot, t: rules.Thresholds) -> dict[int, ElecStats]:
    out = {}
    for uid, items in _items(s, t).items():
        elec = [i for i in items if i.play.area == "elec" and i.row.answered]
        if elec:
            out[uid] = ElecStats(
                stored=sum(i.row.lp for i in elec),
                fixed=sum(i.lp_fixed for i in elec),
                right=sum(_right(i.row) for i in elec),
                n=len(elec),
                pre_seen=sum(i.pre_seen for i in elec),
            )
    return out


def _group_of(s: Snapshot, by: str, uid: int) -> str:
    u = s.users[uid]
    return (u.vertical or "none") if by == "vertical" else u.position


def elo_groups(s: Snapshot, t: rules.Thresholds) -> tuple[dict[str, dict[str, list[int]]], bool]:
    """The groups of each table, by vertical and by position (never crossed), small ones merged so every group
    has min_group people. When the two tables together would still single out fewer people (a position nested in
    a vertical, say), the position table is withheld: (groups per table, withheld)."""
    stats = _elec(s, t)
    out = {}
    for by in ("vertical", "position"):
        raw: dict[str, list[int]] = defaultdict(list)
        for uid in sorted(stats):
            raw[_group_of(s, by, uid)].append(uid)
        out[by] = rules.merge_groups(raw, t.min_group)
    withheld = rules.discloses([out["vertical"], out["position"]], t.min_group)
    if withheld:
        out["position"] = {}
    return out, withheld


def elo_artefact(s: Snapshot, t: rules.Thresholds) -> list[GroupRow]:
    stats = _elec(s, t)
    mismatched = fidelity(s).mismatched
    groups, _ = elo_groups(s, t)
    return [
        _group_row(by, name, members, stats, mismatched, t)
        for by in ("vertical", "position")
        for name, members in sorted(groups[by].items())
    ]


def _group_row(
    by: str,
    name: str,
    members: list[int],
    stats: dict[int, ElecStats],
    mismatched: frozenset[int],
    t: rules.Thresholds,
) -> GroupRow:
    st = [stats[u] for u in members]
    plays = sum(x.n for x in st)
    right = sum(x.right for x in st)
    accuracies = [x.right / x.n for x in st]
    return GroupRow(
        by=by,
        group=name,
        people=len(members),
        plays=plays,
        lp_stored=sum(x.stored for x in st) / plays if plays else None,
        lp_fixed=sum(x.fixed for x in st) / plays if plays else None,
        mean_accuracy=statistics.fmean(accuracies) if accuracies else None,
        mean_interval=rules.bootstrap_mean(accuracies, rounds=t.bootstrap_rounds, seed=t.seed, z=t.z),
        right=right,
        n=plays,
        wilson=rules.wilson(right, plays, t.z),
        pre_seen=sum(x.pre_seen for x in st),
        mismatched=sum(u in mismatched for u in members),
    )


def top_compositions(s: Snapshot, t: rules.Thresholds) -> list[tuple[str, dict[str, int]]]:
    """Who makes the elec top 10, by the vertical groups of the table (so no column is a group under min_group),
    ordered three ways."""
    stats = _elec(s, t)
    groups, _ = elo_groups(s, t)
    vertical = {u: name for name, members in groups["vertical"].items() for u in members}
    shown = [u for u in stats if u in vertical]
    orderings = {
        "stored elec LP": sorted(shown, key=lambda u: -stats[u].stored),
        f"elec LP replayed at {t.fixed_rank:g}": sorted(shown, key=lambda u: -stats[u].fixed),
        "elec accuracy, Wilson low (n >= min_n)": sorted(
            (u for u in shown if stats[u].n >= t.min_n),
            key=lambda u: -rules.wilson(stats[u].right, stats[u].n, t.z)[0],
        ),
    }
    return [(name, rules.top_composition(order, vertical, TOP_K)) for name, order in orderings.items()]


# --- 0b labels -------------------------------------------------------------------------------------------------


def label_quality(s: Snapshot) -> list[tuple[str, bool, str | None, int, int]]:
    """Questions by area, labels_reviewed and topic: how many, and how many ranked plays they had in the
    window."""
    plays: dict[int, int] = defaultdict(int)
    for rows in s.history.values():
        for r in rows:
            if r.mode in ("daily", "mock") and r.counted and _in_window(s, r):
                plays[r.question_id] += 1
    groups: dict[tuple[str, bool, str | None], list[int]] = defaultdict(lambda: [0, 0])
    for qid, q in s.questions.items():
        reviewed, topic = s.question_labels.get(qid, (False, None))
        g = groups[(q.area, reviewed, topic)]
        g[0] += 1
        g[1] += plays[qid]
    return [
        (a, r, tp, n, p)
        for (a, r, tp), (n, p) in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or ""))
    ]


# --- 0c permutation --------------------------------------------------------------------------------------------


def _residuals(s: Snapshot, t: rules.Thresholds, area: str) -> dict[int, list[float]]:
    out = {}
    for uid, items in _items(s, t).items():
        res = [
            _right(i.row) - _peer(s, t, uid, i.row.question_id)
            for i in _first_seen(items)
            if i.play.area == area
        ]
        if res:
            out[uid] = res
    return out


def permutation(s: Snapshot, t: rules.Thresholds) -> tuple[float | None, int, int]:
    """Members' mean elec residual on first-seen plays, Mechanical vs the electrical verticals: how often does
    shuffling the labels give the mechanics an advantage at least this large?"""
    res = _residuals(s, t, "elec")
    mech = [statistics.fmean(v) for u, v in res.items() if s.users[u].vertical == "Mechanical"]
    elec = [statistics.fmean(v) for u, v in res.items() if s.users[u].vertical in ELEC_GROUP]
    if min(len(mech), len(elec)) < t.min_group:  # a side of one or two would be about those people
        return None, len(mech), len(elec)
    return rules.permutation_p(mech, elec, rounds=t.permutation_rounds, seed=t.seed), len(mech), len(elec)


# --- 2b suspect keys -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SuspectKey:
    question_id: int
    options: int
    right: int
    n: int
    wilson: tuple[float, float]


def suspect_keys(s: Snapshot, t: rules.Thresholds) -> list[SuspectKey]:
    """Single-choice questions the cohort gets right below chance on its first answers: the key may be wrong."""
    first: dict[tuple[int, int], bool] = {}
    for uid, rows in s.history.items():
        for r in sorted(rows, key=lambda r: (r.created_at, r.id)):
            if (uid, r.question_id) in first or r.correct is None or r.mode == "live":
                continue
            if not r.answered or r.late or r.passed or rules.graded_at(r) >= s.end:
                continue
            first[(uid, r.question_id)] = bool(r.correct)
    per_q: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for (_, qid), y in first.items():
        per_q[qid][0] += y
        per_q[qid][1] += 1
    out = []
    for qid, (right, n) in sorted(per_q.items()):
        q = s.questions.get(qid)
        if q is None or q.answer_kind != "choice-one" or not q.graded or q.options < 2 or n < t.min_n:
            continue
        lo, hi = rules.wilson(right, n, t.z)
        if hi < 1 / q.options:
            out.append(SuspectKey(qid, q.options, right, n, (lo, hi)))
    return out


# --- 1 follow-the-leader ---------------------------------------------------------------------------------------


def follow(s: Snapshot, t: rules.Thresholds) -> rules.Follow:
    """Every cohort member's daily answers in the window take part (alumni and disabled accounts too: they are part
    of who answered when); only active members are ever printed."""

    def make() -> rules.Follow:
        answers = []
        for uid, rows in s.history.items():
            byq = _by_question(s, uid)
            for r in rows:
                if r.mode != "daily" or not r.answered or not _in_window(s, r) or r.id not in s.answers:
                    continue
                q = s.questions.get(r.question_id)
                canonical = rules.canonical_answer(s.answers[r.id], q.answer_kind if q else "")
                if canonical is None or r.submitted_at is None:
                    continue
                seen = rules.pre_seen(r, byq[r.question_id], s.drawn_at, s.per_player)
                answers.append(
                    rules.DailyAnswer(
                        uid, r.question_id, r.created_at, r.submitted_at, canonical, _right(r), r.passed, seen
                    )
                )
        copies, relays = rules.follow_pairs(answers, t.follow_within, t.follow_min, t.shrink_m)
        return rules.follow_flags(copies, relays, t)

    return _cached(s, f"follow:{hash(t)}", make)  # type: ignore[no-any-return]


# --- 2 upstream-key canary -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UpstreamEvidence:
    n: int
    matches: int
    expected: float
    p: float  # exact upper tail of the matches
    typed: int  # matches on typed answers

    def z(self) -> float | None:
        return rules.z_of(self.p) if self.n else None


def upstream_key(s: Snapshot, t: rules.Thresholds) -> dict[int, UpstreamEvidence]:
    """On questions a reviewer corrected: first exposures after the correction that match FS-Quiz's key and not
    the correction, against how often the rest of the cohort does that (leave-one-out, shrunk)."""

    def make() -> dict[int, UpstreamEvidence]:
        exposures: list[tuple[int, int, bool, bool]] = []  # user, question, match, typed
        for qid, c in s.keys.items():
            if c.corrected_at is None or qid not in s.questions:
                continue
            typed = not s.questions[qid].answer_kind.startswith("choice")
            for uid in s.history:
                graded = [r for r in _by_question(s, uid).get(qid, []) if r.correct is not None]
                if not graded:
                    continue
                r = graded[0]
                if (
                    r.mode not in ("daily", "mock")
                    or not r.counted
                    or not r.answered
                    or r.passed
                    or not _in_window(s, r)
                    or rules.graded_at(r) <= c.corrected_at
                    or r.id not in s.answers
                ):
                    continue
                a = s.answers[r.id]
                options, value = a.get("options"), a.get("value")
                match = (
                    grading.grade(c.key, options, value) is True
                    and grading.grade(c.override, options, value) is False
                )
                exposures.append((uid, qid, match, typed))
        per_q: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        per_u: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        for uid, qid, match, _ in exposures:
            per_q[qid][0] += match
            per_q[qid][1] += 1
            per_u[uid][0] += match
            per_u[uid][1] += 1
        total_m = sum(m for m, _ in per_q.values())
        total_n = sum(n for _, n in per_q.values())
        ps: dict[int, list[float]] = defaultdict(list)
        out: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        for uid, qid, match, typed in exposures:
            own_m, own_n = per_u[uid]
            base = (total_m - own_m + 1) / (total_n - own_n + 2)
            m_q, n_q = per_q[qid]
            p = (
                (m_q - match + t.shrink_m * base) / (n_q - 1 + t.shrink_m)
                if n_q - 1 + t.shrink_m > 0
                else base
            )
            ps[uid].append(p)
            out[uid][0] += match
            out[uid][1] += match and typed
        return {
            u: UpstreamEvidence(len(ps[u]), m, sum(ps[u]), rules.poisson_binomial_sf(ps[u], m), typed)
            for u, (m, typed) in out.items()
        }

    return _cached(s, f"upstream:{hash(t)}", make)  # type: ignore[no-any-return]


def corrections_without_time(s: Snapshot) -> int:
    return sum(c.corrected_at is None for c in s.keys.values())


# --- 3 profile -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Profile:
    latency: rules.Latency
    hard: rules.Anomaly  # difficulty 4-5 against the person's own easier first-seen plays
    gradient: float | None
    easy_n: int


def _seconds(r: rules.Row) -> float:
    assert r.submitted_at is not None  # noqa: S101 - only submitted plays get here
    return (r.submitted_at - r.created_at).total_seconds()


def profile(s: Snapshot, t: rules.Thresholds) -> dict[int, Profile]:
    """Latency on first-seen, answered, in-time, first-time plays; hard items against the person's own record on
    easier ones (each against its peer rate); the difficulty gradient as context."""

    def make() -> dict[int, Profile]:
        out = {}
        for uid, items in _items(s, t).items():
            first = _first_seen(items)
            timed = [i for i in first if not i.row.passed and not i.row.late and not i.play.repeat]
            qs = [s.questions[i.row.question_id] for i in timed]
            latency = rules.latency_profile(
                [(_seconds(i.row), q.text_len) for i, q in zip(timed, qs, strict=True)],
                t,
                images=[q.has_images for q in qs],
            )
            rated = [
                (i.play.difficulty >= rules.HARD, (_right(i.row), _peer(s, t, uid, i.row.question_id)))
                for i in first
            ]
            by_d: dict[int, list[int]] = defaultdict(lambda: [0, 0])
            for i in first:
                by_d[i.play.difficulty][0] += _right(i.row)
                by_d[i.play.difficulty][1] += 1
            out[uid] = Profile(
                latency=latency,
                hard=rules.anomaly([x for h, x in rated if not h], [x for h, x in rated if h]),
                gradient=rules.gradient({d: (r, n) for d, (r, n) in by_d.items()}, t.min_n),
                easy_n=sum(n for d, (_, n) in by_d.items() if d <= 2),
            )
        return out

    return _cached(s, f"profile:{hash(t)}", make)  # type: ignore[no-any-return]


# --- 4 home vs away --------------------------------------------------------------------------------------------


def _mean_residual(pairs: Sequence[tuple[bool, float]]) -> float:
    return sum(y - p for y, p in pairs) / len(pairs)


def home_away(s: Snapshot, t: rules.Thresholds) -> dict[int, tuple[float | None, int, int]]:
    """Residual on away-area questions above the residual at home, one-sided, with the vertical as it is now."""

    def make() -> dict[int, tuple[float | None, int, int]]:
        out = {}
        for uid, items in _items(s, t).items():
            home = rules.HOME.get(s.users[uid].vertical or "")
            if not home:
                continue
            sides: dict[str, list[tuple[bool, float]]] = {"home": [], "away": []}
            for i in _first_seen(items):
                area = i.play.area
                if area not in ("mech", "elec"):
                    continue
                sides["home" if area in home else "away"].append(
                    (_right(i.row), _peer(s, t, uid, i.row.question_id))
                )
            h, a = sides["home"], sides["away"]
            z = None
            if h and a:
                var = (
                    sum(p * (1 - p) for _, p in a) / len(a) ** 2
                    + sum(p * (1 - p) for _, p in h) / len(h) ** 2
                )
                if var > 0:
                    z = (_mean_residual(a) - _mean_residual(h)) / math.sqrt(var)
            out[uid] = (z, len(a), len(h))
        return out

    return _cached(s, f"home_away:{hash(t)}", make)  # type: ignore[no-any-return]


# --- canary and signal context ----------------------------------------------------------------------------------


def _decoy_plays(s: Snapshot) -> dict[int, list[rules.DecoyPlay]]:
    """Each cohort member's counted ranked plays in the window that carried a decoy, in grading order."""

    def make() -> dict[int, list[rules.DecoyPlay]]:
        out: dict[int, list[rules.DecoyPlay]] = {}
        if s.signals is None:
            return out
        for uid, plays in ranked_plays(s).items():
            mine = []
            for r, p in plays:
                sig = s.signals.rows.get(r.id)
                if sig is None or sig.decoy is None or not p.ranked or not _in_window(s, r):
                    continue
                options = s.answers.get(r.id, {}).get("options") or ()
                ca = s.signals.changed_after.get(r.question_id)
                mine.append(
                    rules.DecoyPlay(
                        decoy=sig.decoy,
                        chosen=tuple(int(o) for o in options),
                        answer_kind=s.questions[r.question_id].answer_kind,
                        passed=r.passed,
                        hint=r.hint_used,
                        long_copies=sig.long_copies,
                        resumes=sig.resumes,
                        live=s.signals.live.get(r.question_id, frozenset()),
                        right=s.signals.right.get(r.question_id, frozenset()),
                        changed=ca is not None and ca > sig.created_at,
                    )
                )
            if mine:
                out[uid] = mine
        return out

    return _cached(s, "decoys", make)  # type: ignore[no-any-return]


def walk_from(s: Snapshot) -> date | None:
    return None if s.rules_from is None else rules.walk_from(s.rules_from, s.window.until)


def canary_summary(s: Snapshot, t: rules.Thresholds) -> integrity_canary.CanarySummary | None:
    """None when nothing is collected (no rule date) or a canary setting is unset."""

    def make() -> integrity_canary.CanarySummary | None:
        start = walk_from(s)
        if s.signals is None or start is None:
            return None
        settings = (
            t.canary_alpha,
            t.canary_beta,
            t.canary_follow,
            t.canary_control_alpha,
            t.canary_nudge,
            t.canary_m,
        )
        if any(v is None for v in settings):
            return None
        active = {u for u, info in s.users.items() if info.active}
        return integrity_canary.summarise(_decoy_plays(s), active, start, s.window.since, t)

    return _cached(s, f"canary:{hash(t)}", make)  # type: ignore[no-any-return]


def signal_context(s: Snapshot, t: rules.Thresholds, items: Sequence[Item]) -> rules.Context | None:
    if s.signals is None or t.away_undeclared_s is None:
        return None
    recorded = [
        rules.Recorded(
            sig.away_undeclared_s,
            sig.away_declared_s,
            sig.pasted,
            sig.long_copies,
            sig.resumes,
            sig.decoy is not None,
        )
        for i in items
        if (sig := s.signals.rows.get(i.row.id)) is not None
    ]
    return rules.context(recorded, t.away_undeclared_s)


def collected(s: Snapshot, t: rules.Thresholds) -> int:
    """Counted ranked plays in the window that carry signals."""
    if s.signals is None:
        return 0
    rows = s.signals.rows
    return sum(i.row.id in rows for items in _items(s, t).values() for i in items)


# --- people ----------------------------------------------------------------------------------------------------


def persons(s: Snapshot, t: rules.Thresholds) -> list[rules.Person]:
    """Every active member with a counted ranked play in the window, with the evidence of each family."""

    def make() -> list[rules.Person]:
        fl = follow(s, t)
        upstream = upstream_key(s, t)
        prof = profile(s, t)
        away = home_away(s, t)
        summary = canary_summary(s, t)
        out = []
        for uid, items in sorted(_items(s, t).items()):
            if not s.users[uid].active:
                continue
            share, n_pre = rules.pre_seen_lp_share((i.row.lp, i.pre_seen) for i in items)
            p = prof[uid]
            z, n_away, n_home = away.get(uid, (None, 0, 0))
            up = upstream.get(uid, UpstreamEvidence(0, 0, 0.0, 1.0, 0))
            out.append(
                rules.Person(
                    key=uid,
                    n=len(items),
                    right=sum(_right(i.row) for i in items if i.row.answered),
                    timeouts=sum(not i.row.answered for i in items),
                    late=sum(i.row.late and i.row.answered for i in items),
                    n_first=len(_first_seen(items)),
                    n_preseen=n_pre,
                    pre_seen_lp_share=share,
                    hard_z=p.hard.z(),
                    hard_n=p.hard.n,
                    hard_base_n=p.hard.base_n,
                    gradient=p.gradient,
                    away_z=z,
                    away_n=n_away,
                    home_n=n_home,
                    latency=p.latency,
                    following=uid in fl.flagged,
                    upstream_matches=up.matches,
                    upstream_expected=up.expected,
                    upstream_p=up.p,
                    upstream_n=up.n,
                    upstream_typed=up.typed,
                    follow_tested=uid in fl.tested,
                    canary=summary.people.get(uid) if summary else None,
                    signals=signal_context(s, t, items),
                )
            )
        return out

    return _cached(s, f"persons:{hash(t)}", make)  # type: ignore[no-any-return]


def people(s: Snapshot, t: rules.Thresholds) -> list[rules.Person]:
    """Only the people with at least one positive family."""
    return [p for p in persons(s, t) if any(v is True for v in rules.families(p, t, p.following).values())]


# --- split -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SplitRow:
    key: int
    metric: str
    before: str
    before_n: int
    after: str
    after_n: int
    z: float | None


@dataclass(frozen=True)
class Half:
    seconds: list[float]  # answered in time, not passed
    below: int
    floor_n: int
    right: int
    answered: int
    plays: int


def _halves(s: Snapshot, t: rules.Thresholds, items: Sequence[Item]) -> tuple[Half, Half]:
    assert t.split is not None  # noqa: S101 - only with --split
    cut = madrid_midnight(t.split)
    out = []
    for before in (True, False):
        half = [i for i in items if ((i.row.submitted_at or cut) < cut) is before]
        answered = [i for i in half if i.row.answered]
        timed = [i for i in answered if not i.row.passed and not i.row.late]
        floor = [i for i in timed if not s.questions[i.row.question_id].has_images]
        below = sum(
            _seconds(i.row) < rules.reading_floor(s.questions[i.row.question_id].text_len, t) for i in floor
        )
        right = sum(_right(i.row) for i in answered)
        out.append(Half([_seconds(i.row) for i in timed], below, len(floor), right, len(answered), len(half)))
    return out[0], out[1]


def before_split(s: Snapshot, t: rules.Thresholds) -> Snapshot:
    """The snapshot cut at the split day, so the families can be read on the plays before it alone: behaviour that
    stopped later is not averaged away by the honest-looking rest of the window."""
    assert t.split is not None  # noqa: S101 - only with --split
    return replace(s, window=Window(s.window.since, t.split), cache={})


def split_flags(s: Snapshot, t: rules.Thresholds) -> dict[int, tuple[set[str], set[str], int]]:
    """Active people positive in a family before the split or over the whole window: (families before, families
    over the window, counted plays before)."""
    pre = before_split(s, t)
    whole = {p.key: p for p in people(s, t)}
    early = {p.key: p for p in people(pre, t)}
    plays = {p.key: p.n for p in persons(pre, t)}

    def positive(p: rules.Person | None) -> set[str]:
        if p is None:
            return set()
        return {f for f, v in rules.families(p, t, p.following).items() if v is True}

    return {
        uid: (positive(early.get(uid)), positive(whole.get(uid)), plays.get(uid, 0))
        for uid in sorted(whole.keys() | early.keys())
    }


def split(s: Snapshot, t: rules.Thresholds, flagged: Iterable[int]) -> list[SplitRow]:
    """These people's metrics before and after `t.split`. Context, never a family."""
    items = _items(s, t)
    out = []
    for uid in sorted(set(flagged) & items.keys()):
        b, a = _halves(s, t, items[uid])
        median = [_num(statistics.median(h.seconds) if h.seconds else None, 0) for h in (b, a)]
        out.append(
            SplitRow(uid, "median latency (s)", median[0], len(b.seconds), median[1], len(a.seconds), None)
        )
        for label, (br, bn), (ar, an) in (
            ("below floor", (b.below, b.floor_n), (a.below, a.floor_n)),
            ("accuracy", (b.right, b.answered), (a.right, a.answered)),
            ("timeout share", (b.plays - b.answered, b.plays), (a.plays - a.answered, a.plays)),
        ):
            out.append(
                SplitRow(
                    uid, label, _share(br, bn), bn, _share(ar, an), an, rules.two_proportion_z(ar, an, br, bn)
                )
            )
    return out


def shift(s: Snapshot, t: rules.Thresholds) -> dict[str, list[float]]:
    """Per active person with min_n timed plays on both sides: the change in median log answer time and in
    below-floor share across the split. A cohort distribution, printed without anyone's pseudonym."""
    out: dict[str, list[float]] = {"median log time": [], "below-floor share": []}
    for uid, items in sorted(_items(s, t).items()):
        if not s.users[uid].active:
            continue
        b, a = _halves(s, t, items)
        if min(len(b.seconds), len(a.seconds)) < t.min_n:
            continue
        logs = [statistics.median(math.log(max(x, 0.5)) for x in h.seconds) for h in (b, a)]
        out["median log time"].append(logs[1] - logs[0])
        if b.floor_n and a.floor_n:
            out["below-floor share"].append(a.below / a.floor_n - b.below / b.floor_n)
    return out


# --- the report ------------------------------------------------------------------------------------------------

NA = "n/a"


def _num(x: float | None, digits: int = 2) -> str:
    return NA if x is None else f"{x:.{digits}f}"


def _share(k: int, n: int) -> str:
    return f"{k}/{n} ({k / n:.0%})" if n else NA


def _interval(iv: tuple[float, float] | None) -> str:
    return NA if iv is None else f"[{iv[0]:.2f}, {iv[1]:.2f}]"


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    if not rows:
        rows = [[NA] * len(headers)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _flag(name: str, v: bool | None) -> str:
    if name == "supervised":
        return "pending"
    return {True: "yes", False: "no", None: "insufficient"}[v]


def _quantiles(values: Sequence[float]) -> list[str]:
    if len(values) < 2:
        return [_num(values[0]) if values else NA] * 3
    q = statistics.quantiles(values, n=10, method="inclusive")
    return [_num(q[0]), _num(statistics.median(values)), _num(q[-1])]


def _elo_section(s: Snapshot, t: rules.Thresholds) -> list[str]:
    out = [
        "Elec plays (answered, first-seen and pre-seen both) in the window. Read the mean per-person accuracy for"
        " people and the pooled accuracy for plays; LP replayed at a fixed rank removes the placement head start."
        " Groups under min_group people are pooled as `other` (or join the largest group), so every group has"
        " min_group people and the groups of a table cover everyone.",
    ]
    headers = [
        "group",
        "people",
        "plays (n)",
        "LP/play stored",
        f"LP/play replayed@{t.fixed_rank:g}",
        "mean accuracy",
        "bootstrap interval",
        "pooled right/n",
        "Wilson",
        "pre-seen/n",
        "replay mismatch (people)",
    ]
    rows = elo_artefact(s, t)
    _, withheld = elo_groups(s, t)
    for by in ("vertical", "position"):
        cells = [
            [
                r.group,
                r.people,
                r.plays,
                _num(r.lp_stored),
                _num(r.lp_fixed),
                _num(r.mean_accuracy),
                _interval(r.mean_interval),
                _share(r.right, r.n),
                _interval(r.wilson),
                _share(r.pre_seen, r.n),
                r.mismatched,
            ]
            for r in rows
            if r.by == by
        ]
        out.append(f"### by {by}")
        if by == "position" and withheld:
            out.append(
                "Withheld: together with the vertical table it would single out fewer than min_group people (a"
                " position nested in a vertical). Read it with `--checks elo` on a later, larger cohort."
            )
            continue
        out.append(_table(headers, cells))
    comp = top_compositions(s, t)
    groups = sorted({g for _, c in comp for g in c})
    out += [
        f"### top {TOP_K} composition by vertical",
        _table(
            ["ordering", *groups],
            [[name, *(c.get(g, 0) for g in groups)] for name, c in comp] if groups else [],
        ),
    ]
    return out


def _people_header(s: Snapshot, t: rules.Thresholds) -> list[str]:
    everyone = persons(s, t)
    fams = [rules.families(p, t, p.following) for p in everyone]

    def counts(name: str) -> tuple[int, int]:
        return sum(f[name] is not None for f in fams), sum(f[name] is True for f in fams)

    hard_eligible = sum(
        p.n_first >= t.min_n and p.hard_z is not None and min(p.hard_n, p.hard_base_n) >= t.min_n
        for p in everyone
    )
    away_eligible = sum(
        p.n_first >= t.min_n and p.away_z is not None and min(p.away_n, p.home_n) >= t.min_n for p in everyone
    )
    up_eligible = sum(p.upstream_n >= t.upstream_min for p in everyone)
    fl = follow(s, t)
    chance = {
        "performance": _num(
            rules.expected_false_flags(hard_eligible, t.hard_residual_z)
            + rules.expected_false_flags(away_eligible, t.away_z)
        )
        + " (approximate: within-person tests)",
        "timing": f"{NA} (share thresholds)",
        "provenance": f"≤ {rules.expected_false_flags(up_eligible, t.upstream_z) + fl.expected_false(t):.2f}"
        f" (upstream; follow: copy pairs tested {len(fl.copies)}, relay pairs tested {len(fl.relays)}, Holm)",
        "supervised": NA,
    }
    if canary_summary(s, t) is not None:
        chance["provenance"] += (
            f"; canary: at most α per season (Bonferroni over IFS_INTEGRITY_CANARY_M), for the walk from"
            f" {walk_from(s)}"
        )
    rows = [[name, *counts(name), chance[name]] for name in rules.FAMILIES]
    out = [_table(["family", "eligible (n)", "flagged", "expected by chance"], rows)]
    if s.signals is not None:
        contexts = [p.signals for p in everyone if p.signals is not None]
        out += integrity_canary.cohort_lines(contexts, t.min_group, _table)
    return out


def _people_section(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    flagged = people(s, t)
    rows = []
    for p in flagged:
        f = rules.families(p, t, p.following)
        lat = p.latency
        floor_n = lat.floor_n or lat.n
        uz = p.upstream_z()
        rows.append(
            [
                rules.pseudonym(salt, p.key),
                *(_flag(name, f[name]) for name in rules.FAMILIES),
                ", ".join(name for name in rules.FAMILIES if f[name]) or "none",
                "yes" if rules.independent(f) else "no",
                "yes" if rules.conversation(f) else "no",
                p.n,
                p.n_first,
                p.n_preseen,
                _num(p.pre_seen_lp_share),
                _share(p.timeouts, p.n),
                _share(p.late, p.n),
                f"{_num(p.hard_z)} ({p.hard_n}, {p.hard_base_n})",
                f"{_num(p.away_z)} ({p.away_n}, {p.home_n})",
                _share(lat.below_floor, floor_n),
                _num(lat.sd_log),
                _num(lat.corr_length),
                "yes" if p.following else "no",
                f"{_num(uz)} ({p.upstream_n})",
                integrity_canary.canary_cell(p.canary, p.signals is not None),
                *integrity_canary.context_cells(p.signals),
            ]
        )
    headers = [
        "pseudonym",
        *rules.FAMILIES,
        "families",
        "independent",
        "conversation",
        "n",
        "n_first",
        "n_preseen",
        "pre-seen LP share",
        "timeouts/n",
        "late/n",
        "hard z (n hard, n base)",
        "away z (n_away, n_home)",
        "below floor/n",
        "sd log",
        "ρ length",
        "follow",
        "upstream z (n)",
        "canary hits/trials",
        *integrity_canary.CONTEXT_HEADERS,
    ]
    return [
        "Only people with at least one positive family. Worth a conversation only when two families agree;"
        " `independent` says whether provenance or supervised evidence is among them (performance and timing share"
        " a cause). No flag does not mean clean.",
        *_people_header(s, t),
        _table(headers, rows),
        *([integrity_canary.CAUTION] if s.signals is not None else []),
    ]


def report(s: Snapshot, salt: bytes, checks: frozenset[str], t: rules.Thresholds) -> str:
    items = _items(s, t)
    out = [
        "# Integrity report",
        "",
        f"- window: [{s.window.since}, {s.window.until}) (Madrid days; plays from {s.window.until} on are left out)",
        f"- season: {s.season}",
        f"- n_people: {len(items)} with counted ranked plays in the window ({len(s.users)} in the season's cohort)",
        f"- n_plays: {sum(len(v) for v in items.values())}",
        "- thresholds: from config",
        "- pseudonyms: HMAC-SHA256(salt)[:8]",
        f"- fixed rank: {t.fixed_rank:g}",
        "- home areas: "
        + "; ".join(f"{v}: {', '.join(sorted(a))}" for v, a in rules.HOME.items())
        + " (rules: neither)",
    ]
    if checks & {"canary", "people", "split"}:
        out += _signals_header(s, t)
    for name in rules.CHECKS:
        if name not in checks:
            continue
        out += ["", *SECTIONS[name](s, salt, t)]
    out += ["", "Delete this output after the review (docs/guides/integrity-report.md)."]
    return "\n".join(out) + "\n"


def _signals_header(s: Snapshot, t: rules.Thresholds) -> list[str]:
    if s.signals is None or s.rules_from is None:
        return ["- signals: not collected (IFS_RULES_1B_FROM unset)"]
    summary = canary_summary(s, t)
    decoys = summary.decoys if summary else 0
    return [
        f"- signals: collected from {s.rules_from} (IFS_RULES_1B_FROM): {collected(s, t)} ranked attempts in the"
        " window carry them",
        f"- canary decoys: {decoys} attempts" if decoys else "- canary decoys: none in the window",
    ]


def _s_elo(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    return ["## elo: 0a Elo artefact", *_elo_section(s, t)]


def _s_labels(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    rows = label_quality(s)
    return [
        "## labels: 0b label quality",
        _table(
            ["area", "labels reviewed", "topic", "questions (n)", "ranked plays in window"],
            [[a, "yes" if r else "no", tp or "none", n, p] for a, r, tp, n, p in rows],
        ),
    ]


def _s_permutation(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    p, n_mech, n_elec = permutation(s, t)
    return [
        "## permutation: 0c small-N permutation",
        "Mean per-person elec residual (first-seen plays, against the peer rate), one-sided Mechanical >= the"
        " electrical verticals; `n/a` when a side has fewer than min_group people.",
        _table(
            ["p", "n_mech", "n_elec", "rounds", "seed"],
            [[_num(p, 4), n_mech, n_elec, t.permutation_rounds, t.seed]],
        ),
    ]


def _s_keys(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    rows = suspect_keys(s, t)
    return [
        "## keys: 2b suspect keys",
        "Single-choice questions answered right below chance on first answers (n >= min_n): ask a reviewer to"
        " check the key.",
        _table(
            ["question", "options", "right/n", "n", "Wilson"],
            [[k.question_id, k.options, _share(k.right, k.n), k.n, _interval(k.wilson)] for k in rows],
        ),
    ]


def _s_fidelity(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    f = fidelity(s)
    line = (
        f"replay fidelity: {f.share:.1%} of {f.plays:,} plays reproduce the stored LP; {len(f.mismatched)} players"
        f" have a replay mismatch, {f.repositioned} of them with a position change this season in the audit log."
        " On prod the expected main cause is the nightly difficulty recalibration (the replay prices every play at"
        " the question's current difficulty); then a season rollover or a question changed since. Their plays stay"
        " in the sample"
        if f.share is not None
        else f"replay fidelity: {NA} (no plays)"
    )
    if f.unknown_start:
        line += f"; {f.unknown_start} players not replayed (their rank belongs to a later season)"
    return ["## fidelity: LP replay fidelity", line + "."]


def _shown(s: Snapshot, salt: bytes, uid: int) -> str:
    return rules.pseudonym(salt, uid) if s.users[uid].active else "not active"


def _s_follow(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    fl = follow(s, t)
    flagged = {u for u in fl.flagged if s.users[u].active}
    copies = [
        [
            _shown(s, salt, c.a),
            _shown(s, salt, c.b),
            c.items,
            c.both_wrong,
            c.shared_wrong,
            _num(c.expected),
            _num(c.z()),
            _share(c.a_submitted_first, c.items),
            _share(c.a_started_first, c.items),
            _num(c.median_dt_s, 0),
        ]
        for c in fl.copy_flagged
        if s.users[c.a].active or s.users[c.b].active
    ]
    relays = [
        [
            rules.pseudonym(salt, r.leader) if r.leader in flagged else "not flagged",
            rules.pseudonym(salt, r.follower),
            r.after,
            r.test.n,
            r.test.right,
            _num(r.test.expected),
            _num(r.test.z()),
            r.test.base_n,
            _num(r.median_dt_s, 0),
        ]
        for r in fl.relay_flagged
        if s.users[r.follower].active
    ]
    return [
        "## follow: 1 follow-the-leader on the daily",
        f"pairs tested: copy {len(fl.copies)}, relay {len(fl.relays)}; each test is corrected for the pairs it"
        " tested (Holm, at its configured level). Copy: the same wrong answer, by two people who answered within the"
        " configured window of each other, against how the other players' wrong answers spread; it names a pair,"
        " not who copied. Relay: right where an earlier player was wrong, at any delay that day, against the"
        " follower's own other answers. Known gap: relay inside concurrent mock runs isn't tested here.",
        "### copy pairs",
        _table(
            [
                "pair a",
                "pair b",
                "together (n)",
                "both wrong (n)",
                "same wrong answer",
                "expected",
                "z",
                "a submitted first/n",
                "a started first/n",
                "median |dt| (s)",
            ],
            copies,
        ),
        "### relays",
        _table(
            [
                "leader",
                "follower",
                "after leader (n)",
                "leader wrong (n)",
                "right",
                "expected",
                "z",
                "base (n)",
                "median dt (s)",
            ],
            relays,
        ),
    ]


def _s_upstream(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    evidence = upstream_key(s, t)
    rows = [
        [rules.pseudonym(salt, u), e.n, e.matches, _num(e.expected), _num(e.z()), e.typed]
        for u, e in sorted(evidence.items())
        if s.users[u].active and e.n >= t.upstream_min and (e.z() or 0.0) >= t.upstream_z
    ]
    usable = sum(c.corrected_at is not None for c in s.keys.values())
    return [
        "## upstream-key: 2 corrected-key canary",
        f"corrected questions: {usable}; skipped: no audit time: {corrections_without_time(s)}. Reviewers see"
        " corrections, so this check is blind to them; the set shrinks when an import drops a correction.",
        _table(["pseudonym", "n", "matches", "expected", "z", "typed matches"], rows),
    ]


def _s_profile(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    prof = profile(s, t)
    judged = [p for p in prof.values() if p.latency.n >= t.min_n]
    medians = [p.latency.median_s for p in judged if p.latency.median_s is not None]
    shares = [
        p.latency.below_floor / (p.latency.floor_n or p.latency.n)
        for p in judged
        if (p.latency.floor_n or p.latency.n)
    ]
    sds = [p.latency.sd_log for p in judged if p.latency.sd_log is not None]
    quantiles = _table(
        ["cohort (people with n >= min_n)", "n", "p10", "p50", "p90"],
        [
            ["median latency (s)", len(medians), *_quantiles(medians)],
            ["below-floor share", len(shares), *_quantiles(shares)],
            ["sd of log latency", len(sds), *_quantiles(sds)],
        ],
    )
    rows = []
    for uid, p in sorted(prof.items()):
        if not s.users[uid].active:
            continue
        timing = rules.timing_positive(p.latency, t)
        z = p.hard.z()
        hard = z is not None and min(p.hard.n, p.hard.base_n) >= t.min_n and z >= t.hard_residual_z
        if not timing and not hard:
            continue
        lat = p.latency
        rows.append(
            [
                rules.pseudonym(salt, uid),
                lat.n,
                _num(lat.median_s, 0),
                _share(lat.below_floor, lat.floor_n or lat.n),
                _num(lat.sd_log),
                _num(lat.corr_length),
                f"{_num(z)} ({p.hard.n}, {p.hard.base_n})",
                f"{p.hard.right}/{p.hard.n} ({_num(p.hard.expected, 1)})",
                f"{_num(p.gradient)} ({p.hard.n}, {p.easy_n})",
            ]
        )
    return [
        "## profile: 3 difficulty gradient and latency profile",
        "Read the cohort's spread first, to judge the configured thresholds; then the people they flag. Hard z"
        " compares a person's difficulty 4-5 answers with what their own easier first-seen answers predict.",
        quantiles,
        _table(
            [
                "pseudonym",
                "n",
                "median (s)",
                "below floor/n",
                "sd log",
                "ρ length",
                "hard z (n hard, n base)",
                "hard right/n (expected)",
                "gradient (n hard, n easy)",
            ],
            rows,
        ),
    ]


def _s_home_away(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    ha = home_away(s, t)
    changed = sum(
        1
        for u in _items(s, t)
        if s.users[u].invite_vertical and s.users[u].invite_vertical != s.users[u].vertical
    )
    rows = [
        [rules.pseudonym(salt, u), _num(z), n_away, n_home]
        for u, (z, n_away, n_home) in sorted(ha.items())
        if s.users[u].active and z is not None and min(n_away, n_home) >= t.min_n and z >= t.away_z
    ]
    return [
        "## home-away: 4 home vs away residual",
        f"Vertical as it is now; vertical changed since sign-up: {changed} people.",
        _table(["pseudonym", "away z", "n_away", "n_home"], rows),
    ]


def _s_canary(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    items = _items(s, t)
    return integrity_canary.section(
        canary_summary(s, t),
        name=lambda uid: rules.pseudonym(salt, uid),
        context_of=lambda uid: signal_context(s, t, items.get(uid, [])),
        rules_from=s.rules_from,
        walk_from=walk_from(s),
        min_group=t.min_group,
        table=_table,
    )


def _s_people(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    return ["## people: evidence families per person", *_people_section(s, salt, t)]


def _s_split(s: Snapshot, salt: bytes, t: rules.Thresholds) -> list[str]:
    if t.split is None:
        return ["## split: before and after", f"{NA}: no --split date."]
    flags = split_flags(s, t)
    families = [
        [
            rules.pseudonym(salt, uid),
            ", ".join(f for f in rules.FAMILIES if f in early) or "none",
            n_before,
            ", ".join(f for f in rules.FAMILIES if f in whole) or "none",
        ]
        for uid, (early, whole, n_before) in flags.items()
    ]
    rows = [
        [rules.pseudonym(salt, r.key), r.metric, r.before, r.before_n, r.after, r.after_n, _num(r.z)]
        for r in split(s, t, flags)
    ]
    moved = shift(s, t)
    return [
        f"## split: before and after {t.split}",
        "The families read on the plays before the split alone, for anyone positive there or over the whole window"
        " (a behaviour that stopped is not averaged away), then their metrics on each side. Context for a"
        " conversation, never a family of its own.",
        _table(["pseudonym", "families before", "n before", "families over the window"], families),
        _table(["pseudonym", "metric", "before", "n before", "after", "n after", "z (after - before)"], rows),
        "Cohort shift: per person with min_n timed plays on each side, after minus before. No one is named.",
        _table(
            ["change", "people (n)", "p10", "p50", "p90"],
            [[name, len(v), *_quantiles(v)] for name, v in moved.items()],
        ),
    ]


SECTIONS: dict[str, Callable[[Snapshot, bytes, rules.Thresholds], list[str]]] = {
    "elo": _s_elo,
    "labels": _s_labels,
    "permutation": _s_permutation,
    "keys": _s_keys,
    "fidelity": _s_fidelity,
    "follow": _s_follow,
    "upstream-key": _s_upstream,
    "profile": _s_profile,
    "home-away": _s_home_away,
    "canary": _s_canary,
    "people": _s_people,
    "split": _s_split,
}
