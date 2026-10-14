"""The AI canary and the signal context in the integrity report (ADR 0010 D, docs/guides/integrity-report.md).
Read-only like services/integrity, which calls it with explicit inputs: plain SELECTs with no identity
column, then counts. Nothing printed here names an option, a key or a person; the caller passes pseudonyms."""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session as DB

from ..db.models import REVEALED, AnswerKey, AnswerOption, Attempt, AuditLog, MockSession, Question
from ..domain import integrity as rules
from ..domain.leaderboard import madrid_midnight

NA = "n/a"
NOT_COLLECTED = "not collected"
CONTEXT_HEADERS = (
    "undeclared away any/over/n, median",
    "declared away any/n, median",
    "pasted/text n",
    "long copies attempts/n",
    "resumes attempts/n",
    "decoy attempts without totals/n",
)
CAUTION = (
    "Caution: the signal columns can come from allowed behaviour (the rulebook in another tab, a translator,"
    " notifications, reading in a second language), and the page reports them, so they can be forged. They are"
    " context for a conversation, never evidence on their own and never a family."
)
SHARES = (
    "any undeclared away",
    "undeclared away over the threshold",
    "any declared away",
    "pasted (text answers)",
    "long copy",
    "resumed",
    "decoy attempts without totals",
)
P90_MIN = 10  # contributors before a p90 is shown: display privacy, not a decision threshold


@dataclass(frozen=True)
class SignalRow:
    away_declared_s: int | None
    away_undeclared_s: int | None
    pasted: bool | None
    long_copies: int | None  # None: the page sent no totals
    resumes: int
    decoy: int | None
    created_at: datetime


@dataclass(frozen=True)
class Signals:
    rows: dict[int, SignalRow]  # attempt id -> totals, ranked attempts created from the rule date on
    live: dict[int, frozenset[int]]  # question id -> live option ids, for the questions with a decoy
    right: dict[int, frozenset[int]]  # question id -> the effective key's options, for choice keys
    # question id -> when it last changed upstream (flagged, or acknowledged since), for the questions with a decoy
    changed_after: dict[int, datetime | None]


def fetch_signals(
    db: DB,
    cohort: Select[Any],
    window: ColumnElement[bool],
    rules_from: date,
    end: datetime,
    effective: ColumnElement[Any],
) -> Signals:
    """Attempts that carry signals (purged and pre-date rows have none), created from the rule date's Madrid
    midnight: an attempt started the evening before is left out even when it was submitted after."""
    rows: dict[int, SignalRow] = {}
    decoy_questions: set[int] = set()
    for r in db.execute(
        select(
            Attempt.id,
            Attempt.question_id,
            Attempt.away_declared_s,
            Attempt.away_undeclared_s,
            Attempt.pasted,
            Attempt.long_copies,
            Attempt.resumes,
            Attempt.decoy_option_id,
            Attempt.created_at,
        )
        .outerjoin(MockSession, MockSession.id == Attempt.session_id)
        .where(
            Attempt.user_id.in_(cohort),
            Attempt.mode.in_(("daily", "mock")),
            Attempt.resumes.is_not(None),
            Attempt.created_at >= madrid_midnight(rules_from),
            Attempt.submitted_at < end,
            REVEALED,  # a daily whose result is not out yet joins the cohort at its grant
            window,
        )
    ):
        rows[r.id] = SignalRow(
            r.away_declared_s,
            r.away_undeclared_s,
            r.pasted,
            r.long_copies,
            r.resumes,
            r.decoy_option_id,
            r.created_at,
        )
        if r.decoy_option_id is not None:
            decoy_questions.add(r.question_id)
    live: dict[int, set[int]] = {q: set() for q in decoy_questions}
    right: dict[int, frozenset[int]] = {}
    changed: dict[int, datetime | None] = dict.fromkeys(decoy_questions)
    if decoy_questions:
        for qid, oid in db.execute(
            select(AnswerOption.question_id, AnswerOption.id).where(
                AnswerOption.question_id.in_(decoy_questions), AnswerOption.retired.is_(False)
            )
        ):
            live[qid].add(oid)
        for qid, key in db.execute(
            select(AnswerKey.question_id, effective).where(AnswerKey.question_id.in_(decoy_questions))
        ):
            if isinstance(key, dict) and key.get("kind") == "choice":
                right[qid] = frozenset(int(o) for o in key.get("options") or ())
        for qid, at in db.execute(
            select(Question.id, Question.key_changed_at).where(
                Question.id.in_(decoy_questions), Question.key_changed_at.is_not(None)
            )
        ):
            changed[qid] = at
        # a reviewer's acknowledgement clears key_changed_at; its audit row keeps when the change was seen
        for target, at in db.execute(
            select(AuditLog.target, func.max(AuditLog.at))
            .where(
                AuditLog.action == "question.update",
                AuditLog.target.in_([f"question:{q}" for q in decoy_questions]),
                AuditLog.details.has_key("upstream_change"),
            )
            .group_by(AuditLog.target)
        ):
            qid = int(target.removeprefix("question:"))
            changed[qid] = max(at, changed[qid] or at)
    return Signals(rows, {q: frozenset(v) for q, v in live.items()}, right, changed)


@dataclass(frozen=True)
class CanarySummary:
    decoys: int
    voided: Counter[str]
    arms: Counter[str]  # valid trials per arm: copy, placebo, unreported, neither (a reload, no long copy)
    draw: rules.Tail
    draw_status: str  # ok | off | too small
    placebo: rules.Tail  # pooled over everyone, verdict after leave-one-out
    placebo_people: int
    placebo_status: str  # ok | off | too small
    # active people pushing an off placebo most: (user id, placebo trials, hits - expected)
    contributors: list[tuple[int, int, float]]
    excluded: int  # people whose own placebo is off
    over_m: bool
    people: dict[int, rules.Canary]  # everyone with copy-arm trials, alumni included
    listed: dict[int, rules.Canary]  # active people whose picks without a reported copy cross the boundary
    unreported_share: dict[int, float]  # of the listed walk's trials
    reloaded_share: dict[int, float]  # of the listed walk's trials: no long copy, but a reload
    # active people whose copy walk crossed while their own placebo is off: their decision is ignored, so they
    # are shown here with both arms (copy walk, own placebo tail) instead of vanishing
    own_off_crossed: dict[int, tuple[rules.Canary, rules.Tail]]
    nudged: bool
    exploratory: bool
    flagged: list[int]  # active people with an active canary reject

    @property
    def reliable(self) -> bool:
        return self.draw_status == "ok" and self.placebo_status == "ok" and not self.over_m


def _excess(trials: Sequence[tuple[float, bool]]) -> float:
    return sum(h for _, h in trials) - sum(p for p, _ in trials)


def summarise(
    plays_by_person: Mapping[int, Sequence[rules.DecoyPlay]],
    active: Collection[int],
    walk_from: date,
    since: date,
    t: rules.Thresholds,
) -> CanarySummary:
    """The trials of each person in grading order, the controls and the decisions. The controls run at
    canary_control_alpha; a control that is off or too small to see a follower ignores every decision."""
    assert (  # noqa: S101 - canary_summary checks them
        t.canary_alpha is not None
        and t.canary_beta is not None
        and t.canary_follow is not None
        and t.canary_control_alpha is not None
        and t.canary_nudge is not None
        and t.canary_m is not None
    )
    alpha, beta, follow, ca = t.canary_alpha, t.canary_beta, t.canary_follow, t.canary_control_alpha
    nudge, m = t.canary_nudge, t.canary_m
    voided: Counter[str] = Counter()
    arms: Counter[str] = Counter()
    copy: dict[int, list[tuple[float, bool]]] = {}
    placebo: dict[int, list[tuple[float, bool]]] = {}
    # no reported copy (placebo, unreported, reloaded), in grading order
    quiet: dict[int, list[tuple[float, bool]]] = {}
    unreported: Counter[int] = Counter()
    reloaded: Counter[int] = Counter()
    draws = []
    for uid, plays in plays_by_person.items():
        for d in plays:
            if (hit := rules.draw_hit(d)) is not None:
                draws.append(hit)
            trial = rules.canary_trial(d)
            if isinstance(trial, str):
                voided[trial] += 1
                continue
            arm = rules.canary_arm(d) or "neither"
            arms[arm] += 1
            if arm == "copy":
                copy.setdefault(uid, []).append(trial)
                continue
            quiet.setdefault(uid, []).append(trial)
            if arm == "placebo":
                placebo.setdefault(uid, []).append(trial)
            elif arm == "unreported":
                unreported[uid] += 1
            else:
                reloaded[uid] += 1  # a reload may hide a copy: walked in the listing, kept out of the placebo

    exploratory = since > walk_from
    draw = rules.draw_tail(draws, ca)
    rs = [r for r, _ in draws]
    draw_power = rules.power(rs, [r + follow * (1 - r) for r in rs], ca / 2)
    draw_status = "off" if draw.verdict == "off" else "too small" if draw_power < 1 - beta else "ok"

    pooled = [x for v in placebo.values() for x in v]
    p0s = [p for p, _ in pooled]
    tail = rules.placebo_tail(pooled, ca)
    sides = {"high": tail.p_high, "low": tail.p_low}
    off = {side for side, p in sides.items() if p < ca / 2 and rules.loo_off(placebo, ca, side)}
    tail = replace(tail, verdict="off" if off else "near chance")
    if len(placebo) < t.min_group:
        placebo_status = "too small"
    elif off:
        placebo_status = "off"
    elif rules.power(p0s, [p + follow * (1 - p) for p in p0s], ca / 2) < 1 - beta:
        placebo_status = "too small"
    else:
        placebo_status = "ok"
    contributors: list[tuple[int, int, float]] = []
    if placebo_status == "off":
        sign = 1 if "high" in off else -1
        contributors = sorted(
            ((u, len(v), _excess(v)) for u, v in placebo.items() if u in active), key=lambda c: -sign * c[2]
        )[:5]

    over_m = len(copy) > m
    own_tails = {u: rules.placebo_tail(v, ca) for u, v in placebo.items()}
    own_off = {u for u, x in own_tails.items() if x.p_high < ca}
    reason: str | None = None
    if draw_status != "ok":
        reason = "draw check off" if draw_status == "off" else "controls too small"
    elif placebo_status != "ok":
        reason = "placebo off" if placebo_status == "off" else "controls too small"
    elif over_m:
        reason = "more players than IFS_INTEGRITY_CANARY_M"
    raw = rules.canary_evidence(copy, alpha=alpha, beta=beta, follow=follow, nudge=nudge, m=m)
    people = {}
    for uid, c in raw.items():
        if exploratory:
            people[uid] = replace(c, decision="exploratory", decided_at=None, earlier_stretch=False)
        elif reason is not None or uid in own_off:
            people[uid] = replace(
                c,
                decision="ignored",
                decided_at=None,
                earlier_stretch=False,
                note=reason or "own placebo off",
            )
        else:
            people[uid] = c

    listed: dict[int, rules.Canary] = {}
    if not exploratory and draw_status == "ok":
        found = rules.listing(quiet, alpha=alpha, follow=follow, nudge=nudge, m=m)
        listed = {u: c for u, c in found.items() if u in active}
    own_off_crossed = {}
    if not exploratory and draw_status == "ok":
        own_off_crossed = {
            u: (raw[u], own_tails[u])
            for u in sorted(own_off)
            if u in active and u in raw and raw[u].decision == "reject"
        }
    nudged = rules.nudge_check(
        [x for u, v in copy.items() if raw[u].decision != "reject" for x in v], alpha=ca, nudge=nudge
    )
    return CanarySummary(
        decoys=sum(len(v) for v in plays_by_person.values()),
        voided=voided,
        arms=arms,
        draw=draw,
        draw_status=draw_status,
        placebo=tail,
        placebo_people=len(placebo),
        placebo_status=placebo_status,
        contributors=contributors,
        excluded=len(own_off),
        over_m=over_m,
        people=people,
        listed=listed,
        unreported_share={u: unreported[u] / len(quiet[u]) for u in listed},
        reloaded_share={u: reloaded[u] / len(quiet[u]) for u in listed},
        own_off_crossed=own_off_crossed,
        nudged=nudged,
        exploratory=exploratory,
        flagged=sorted(u for u, c in people.items() if c.decision == "reject" and u in active),
    )


def _five(x: float) -> float:
    return round(x * 20) / 20


def cohort_context(
    contexts: Sequence[rules.Context], min_group: int
) -> dict[str, tuple[int, float | None, float | None]] | None:
    """p50 and p90 of each share over the people with signals, rounded to 5 points; None under min_group people,
    no quantiles for a share fewer than min_group people have, and p90 only from P90_MIN of them."""
    if len(contexts) < min_group:
        return None
    pairs: dict[str, list[tuple[int, int]]] = {
        SHARES[0]: [(c.away_any, c.reported) for c in contexts],
        SHARES[1]: [(c.away_over, c.reported) for c in contexts],
        SHARES[2]: [(c.declared_any, c.reported_d) for c in contexts],
        SHARES[3]: [(c.pasted, c.text_n) for c in contexts],
        SHARES[4]: [(c.copied, c.copies_n) for c in contexts],
        SHARES[5]: [(c.resumed, c.n) for c in contexts],
        SHARES[6]: [(c.unreported, c.decoy_n) for c in contexts],
    }
    out: dict[str, tuple[int, float | None, float | None]] = {}
    for name, ks in pairs.items():
        values = [k / n for k, n in ks if n]
        if len(values) < min_group:
            out[name] = (len(values), None, None)
            continue
        p90 = statistics.quantiles(values, n=10, method="inclusive")[-1] if len(values) >= P90_MIN else None
        out[name] = (len(values), _five(statistics.median(values)), None if p90 is None else _five(p90))
    return out


# --- printing ----------------------------------------------------------------------------------------------------


def _seconds(x: float | None) -> str:
    return NA if x is None else f"{x:.0f} s"


def _pct(x: float | None) -> str:
    return NA if x is None else f"{x:.0%}"


def _decision(c: rules.Canary) -> str:
    if c.note:
        return f"{c.decision} ({c.note})"
    return f"{c.decision}, earlier stretch" if c.earlier_stretch else c.decision


def canary_cell(c: rules.Canary | None, collected: bool) -> str:
    if not collected:
        return NOT_COLLECTED
    if c is None:
        return "no trials"
    return f"{c.hits}/{c.trials}, expected {c.expected:.2f}, {_decision(c)}"


def context_cells(ctx: rules.Context | None) -> list[str]:
    """In the order of CONTEXT_HEADERS."""
    if ctx is None:
        return [NOT_COLLECTED] * len(CONTEXT_HEADERS)
    return [
        f"{ctx.away_any}/{ctx.away_over}/{ctx.reported}, {_seconds(ctx.away_median_s)}",
        f"{ctx.declared_any}/{ctx.reported_d}, {_seconds(ctx.declared_median_s)}",
        f"{ctx.pasted}/{ctx.text_n}",
        f"{ctx.copied}/{ctx.copies_n} ({ctx.long_copies} total)",
        f"{ctx.resumed}/{ctx.n} ({ctx.resumes} total)",
        f"{ctx.unreported}/{ctx.decoy_n}",
    ]


def cohort_lines(
    contexts: Sequence[rules.Context],
    min_group: int,
    table: Callable[[Sequence[str], Sequence[Sequence[object]]], str],
) -> list[str]:
    cc = cohort_context(contexts, min_group)
    if cc is None:
        return ["Signals across the cohort: fewer than min_group people with collected signals.", CAUTION]
    return [
        "Signals across the cohort: per person, the share of their ranked answers with collected signals; rounded"
        f" to 5 points, nobody named, `n/a` under min_group people (p90 under {P90_MIN}).",
        table(
            ["share", "people (n)", "p50", "p90"],
            [[name, n, _pct(p50), _pct(p90)] for name, (n, p50, p90) in cc.items()],
        ),
        CAUTION,
    ]


def _tail_cells(x: rules.Tail) -> list[object]:
    return [x.trials, x.hits, f"{x.expected:.2f}", f"{x.p_high:.4f}", f"{x.p_low:.4f}"]


def _p_cell(c: rules.Canary) -> str:
    z = c.z()
    return NA if z is None else f"{c.p:.4f} ({z:.2f})"


STATUS = {"ok": "near chance", "off": "off", "too small": "too small"}


def section(
    summary: CanarySummary | None,
    *,
    name: Callable[[int], str],
    context_of: Callable[[int], rules.Context | None],
    rules_from: date | None,
    walk_from: date | None,
    min_group: int,
    table: Callable[[Sequence[str], Sequence[Sequence[object]]], str],
) -> list[str]:
    """`name` pseudonymises a user id; `context_of` gives a person's signal context for the tables."""
    out = [
        "## canary: AI canary note followed",
        "A trial is a ranked single-choice answer with a decoy that is not a right option, at least 3 live options"
        " and 2 wrong ones, the question unchanged upstream since, no hint, and one wrong option chosen; a hit is"
        " that option being the decoy. The decoy is drawn uniformly over the options offered, independently of the"
        " key and the player, so for an honest wrong answer a hit has chance exactly 1/(options - right options)."
        " A hit means the note was followed, by an AI or a nudged person: not necessarily `used an AI`. Copy arm:"
        " a long copy (which carried the note) before the answer. Placebo arm: no long copy and no reload."
        " Unreported: the page sent no totals. Neither arm: no long copy but a reload, which resets the page's"
        " counters, so a copy may have been lost: it is in no control and no decision, only in the listing below.",
    ]
    if summary is None or rules_from is None or walk_from is None:
        return [*out, f"{NOT_COLLECTED}: IFS_RULES_1B_FROM is unset."]
    if not summary.decoys:
        return [*out, "none in the window."]
    if summary.exploratory:
        out.append(
            f"exploratory: the window starts after the walk start {walk_from}, so this is a new look at the data;"
            " the canary flags no one, lists no one and sets no family."
        )
    out.append(
        table(
            ["decoy attempts", "n"],
            [
                ["copy arm", summary.arms["copy"]],
                ["placebo arm", summary.arms["placebo"]],
                ["unreported (no totals)", summary.arms["unreported"]],
                ["neither arm (reloaded, no long copy)", summary.arms["neither"]],
                *([f"void: {v}", summary.voided.get(v, 0)] for v in rules.VOID),
            ],
        )
    )
    small = summary.placebo_people < min_group
    placebo = ["fewer than min_group people"] * 5 if small else _tail_cells(summary.placebo)
    out.append(
        table(
            ["control", "trials", "hits", "expected", "p high", "p low", "verdict"],
            [
                [
                    "draw check (decoy is a right option)",
                    *_tail_cells(summary.draw),
                    STATUS[summary.draw_status],
                ],
                [
                    f"placebo (no long copy, no reload; {summary.placebo_people} people, own placebo off:"
                    f" {summary.excluded})",
                    *placebo,
                    STATUS[summary.placebo_status],
                ],
            ],
        )
    )
    if summary.draw_status == "off":
        out.append(
            "The draw check is off: the decoy doesn't fall on a right option as often as chance says, so the"
            " draw may look at the key. The canary flags no one in this run and lists no one."
        )
    if summary.placebo_status == "off":
        out.append(
            "The placebo is off, even without its largest contributor: without the note the decoy is picked"
            " more (or less) often than chance, so it is observable some other way. The canary flags no one in"
            " this run and its evidence is unreliable. The people who push it most:"
        )
        out.append(
            table(
                ["pseudonym", "placebo trials", "hits - expected"],
                [[name(u), n, f"{x:+.2f}"] for u, n, x in summary.contributors],
            )
        )
    if "too small" in (summary.draw_status, summary.placebo_status) and summary.draw_status != "off":
        out.append(
            "The controls are too small to see a follower of the configured strength: the canary flags no one in"
            " this run. Wait for the next, longer window."
        )
    if summary.over_m:
        out.append(
            "More people have copy-arm trials than IFS_INTEGRITY_CANARY_M: the canary flags no one in this run."
        )
    if not summary.reliable:
        out.append(
            "A run is judged once: re-running the same window until the controls pass is not valid; the next"
            " scheduled, longer window is."
        )
    if summary.reliable and not summary.exploratory and not summary.flagged:
        out.append("No active person's copy-arm walk reached the boundary in this run.")
    if summary.flagged:
        out.append(
            table(
                [
                    "pseudonym",
                    "trials",
                    "hits",
                    "expected",
                    "fixed-window p (z), context",
                    "anytime p",
                    "decided at (trial)",
                    "note",
                    *CONTEXT_HEADERS,
                ],
                [
                    [
                        name(u),
                        c.trials,
                        c.hits,
                        f"{c.expected:.2f}",
                        _p_cell(c),
                        f"{c.p_any:.4f}",
                        c.decided_at,
                        "earlier stretch" if c.earlier_stretch else "",
                        *context_cells(context_of(u)),
                    ]
                    for u in summary.flagged
                    for c in [summary.people[u]]
                ],
            )
        )
    if summary.listed:
        out.append(
            "Decoy picked without a reported copy: the same walk and boundary over the answers with no long copy"
            " reported (placebo, unreported and neither-arm attempts). Either the person reads the decoy some other"
            " way or the page under-reported its copies (a reload loses them). A pointer for a reviewer, never a"
            " family."
        )
        out.append(
            table(
                [
                    "pseudonym",
                    "trials",
                    "hits",
                    "fixed-window p (z), context",
                    "anytime p",
                    "unreported share",
                    "reloaded share",
                    *CONTEXT_HEADERS,
                ],
                [
                    [
                        name(u),
                        c.trials,
                        c.hits,
                        _p_cell(c),
                        f"{c.p_any:.4f}",
                        _pct(summary.unreported_share[u]),
                        _pct(summary.reloaded_share[u]),
                        *context_cells(context_of(u)),
                    ]
                    for u, c in sorted(summary.listed.items(), key=lambda uc: name(uc[0]))
                ],
            )
        )
    if summary.own_off_crossed:
        out.append(
            "Copy walk crossed, own placebo off: these people's copy-arm walk reached the boundary, but they also"
            " pick the decoy without a copy more often than chance, so the note is not the only way they could"
            " know it and their decision is `ignored`. Shown rather than dropped, with both arms. A pointer for a"
            " reviewer, never a family."
        )
        out.append(
            table(
                [
                    "pseudonym",
                    "copy trials",
                    "copy hits",
                    "fixed-window p (z), context",
                    "anytime p",
                    "placebo trials",
                    "placebo hits",
                    "placebo expected",
                    "placebo p high",
                    *CONTEXT_HEADERS,
                ],
                [
                    [
                        name(u),
                        c.trials,
                        c.hits,
                        _p_cell(c),
                        f"{c.p_any:.4f}",
                        x.trials,
                        x.hits,
                        f"{x.expected:.2f}",
                        f"{x.p_high:.4f}",
                        *context_cells(context_of(u)),
                    ]
                    for u, (c, x) in sorted(summary.own_off_crossed.items(), key=lambda uc: name(uc[0]))
                ],
            )
        )
    if summary.nudged:
        out.append(
            "Warning: honest readers may be nudged beyond IFS_INTEGRITY_CANARY_NUDGE, or followers are undetected;"
            " read the canary with extra caution."
        )
    out.append(CAUTION)
    decisions = Counter(c.decision for c in summary.people.values())
    out.append(
        f"{len(summary.people)} people with copy-arm trials (alumni included): "
        + ", ".join(
            f"{d} {decisions.get(d, 0)}" for d in ("reject", "no sign", "continue", "ignored", "exploratory")
        )
        + f". Bonferroni over IFS_INTEGRITY_CANARY_M keeps the chance of any false reject at α per season, for the"
        f" walk from {walk_from}; a reject is final for the trials of this run: a later"
        " upstream change or key correction can remove or reprice earlier trials. `no sign` clears no one."
    )
    return out
