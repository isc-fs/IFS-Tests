"""Forensic statistics over ranked play, for the integrity report (docs/guides/integrity-report.md).

Pure: no I/O, no clock, no identities. Callers pass user ids as opaque keys and pseudonymise them only when
rendering. Nothing here decides anything: it measures, and a person reads the result.

`rank.expected` is never a baseline here: it is conditioned on rank points, so a player placed high looks weak
and one placed low looks strong at the same accuracy, which rebuilds the artefact the fixed-rank replay
removes. Baselines are raw accuracy with a Wilson interval, the cohort's accuracy per difficulty, and a
leave-one-out peer rate per question shrunk towards that.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import math
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Collection, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from statistics import NormalDist
from typing import Any

from . import keys
from . import rank as rank_rules
from .daily import madrid_day
from .leaderboard import first_day, madrid_midnight
from .signals import MIN_DECOY_OPTIONS

FAMILIES = ("performance", "timing", "provenance", "supervised")
COHORT_CHECKS = ("elo", "labels", "permutation", "keys", "fidelity")
PERSON_CHECKS = ("follow", "upstream-key", "profile", "home-away", "canary", "people", "split")
CHECKS = COHORT_CHECKS + PERSON_CHECKS
MIN_SALT = 32
# Rules questions are neither home nor away for anyone; the other verticals have no home area.
HOME = {"Mechanical": {"mech"}, "Electronics": {"elec"}, "Tractive System": {"elec"}, "Driverless": {"elec"}}
HARD = 4
NEVER = datetime.max.replace(tzinfo=UTC)
# Prior sd of a person's ability shift in logits: wide on purpose, it only keeps a perfect record finite.
ABILITY_SD = 2.0
OTHER = "other"


# --- primitives ------------------------------------------------------------------------------------------------


def pseudonym(salt: bytes, user_id: int) -> str:
    return hmac.new(salt, str(user_id).encode(), hashlib.sha256).hexdigest()[:8]


def wilson(right: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for right/n; (0, 1) when nothing was answered."""
    if n <= 0:
        return 0.0, 1.0
    p = right / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def two_proportion_z(a_right: int, a_n: int, b_right: int, b_n: int) -> float | None:
    if a_n <= 0 or b_n <= 0:
        return None
    pooled = (a_right + b_right) / (a_n + b_n)
    if pooled <= 0 or pooled >= 1:
        return None
    se = math.sqrt(pooled * (1 - pooled) * (1 / a_n + 1 / b_n))
    return (a_right / a_n - b_right / b_n) / se


def tail(z: float) -> float:
    """One-sided upper tail of the standard normal."""
    return 1 - NormalDist().cdf(z)


def z_of(p: float) -> float:
    """The one-sided z with upper tail p, never below 0 (no evidence): puts exact and predictive p-values on the
    scale of the thresholds."""
    return max(0.0, -NormalDist().inv_cdf(min(max(p, 1e-300), 0.5)))


_TINY = 1e-300  # mass dropped at the edges of a distribution: what the floats underflow to anyway


def _binomial(n: int, p: float) -> tuple[int, list[float]]:
    """(lowest count kept, the pmf from there), grown out from the mode."""
    if p <= 0 or p >= 1:
        return (0 if p <= 0 else n), [1.0]
    lp, lq, g = math.log(p), math.log1p(-p), math.lgamma(n + 1)

    def pmf(k: int) -> float:
        return math.exp(g - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * lp + (n - k) * lq)

    lo = hi = min(n, int((n + 1) * p))
    while lo > 0 and pmf(lo - 1) >= _TINY:
        lo -= 1
    while hi < n and pmf(hi + 1) >= _TINY:
        hi += 1
    return lo, [pmf(k) for k in range(lo, hi + 1)]


def _convolve(a: tuple[int, list[float]], b: tuple[int, list[float]]) -> tuple[int, list[float]]:
    (la, xa), (lb, xb) = a, b
    out = [0.0] * (len(xa) + len(xb) - 1)
    for i, x in enumerate(xa):
        for j, y in enumerate(xb):
            out[i + j] += x * y
    lo, hi = 0, len(out) - 1
    while lo < hi and out[lo] < _TINY:
        lo += 1
    while hi > lo and out[hi] < _TINY:
        hi -= 1
    return la + lb + lo, out[lo : hi + 1]


def _poisson_binomial(ps: Sequence[float]) -> tuple[int, list[float]]:
    """The distribution of a sum of independent Bernoulli(p_i) as (lowest count kept, pmf): one binomial per
    distinct p, convolved, so thousands of trials over a few chances stay fast."""
    dist: tuple[int, list[float]] = (0, [1.0])
    for p, n in sorted(Counter(ps).items(), key=lambda pn: pn[1]):
        dist = _convolve(dist, _binomial(n, p))
    return dist


def poisson_binomial_tails(ps: Sequence[float], k: int) -> tuple[float, float]:
    """(P(X <= k), P(X >= k)) from one distribution: exact, where a normal tail is far too thin."""
    lo, dist = _poisson_binomial(ps)
    i = k - lo
    low = 0.0 if k < 0 else 1.0 if k >= len(ps) else min(1.0, sum(dist[: max(0, i + 1)]))
    high = 1.0 if k <= 0 else 0.0 if k > len(ps) else min(1.0, sum(dist[max(0, i) :]))
    return low, high


def poisson_binomial_sf(ps: Sequence[float], k: int) -> float:
    """P(X >= k)."""
    if k <= 0:
        return 1.0
    if k > len(ps):
        return 0.0
    return poisson_binomial_tails(ps, k)[1]


def power(ps: Sequence[float], alt_ps: Sequence[float], alpha: float) -> float:
    """The chance the exact one-sided test at alpha (reject from the smallest count whose upper tail under `ps`
    is at most alpha) rejects when the chances are `alt_ps`."""
    if not ps:
        return 0.0
    lo, dist = _poisson_binomial(ps)
    c, upper = lo + len(dist), 0.0
    while c > lo and upper + dist[c - 1 - lo] <= alpha:
        c -= 1
        upper += dist[c - lo]
    return poisson_binomial_sf(alt_ps, c) if c <= len(ps) else 0.0


def holm(pvalues: Sequence[float], alpha: float) -> list[bool]:
    """Holm's step-down rejections, in the order given."""
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    out = [False] * len(pvalues)
    m = len(pvalues)
    for rank, i in enumerate(order):
        if pvalues[i] > alpha / (m - rank):
            break
        out[i] = True
    return out


def bootstrap_mean(
    values: Sequence[float], *, rounds: int, seed: int, z: float
) -> tuple[float, float] | None:
    """Percentile interval of the mean over resampled values, two-sided at `z`."""
    if len(values) < 2 or rounds < 1:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(rounds))
    a = tail(z)
    return means[int(a * (rounds - 1))], means[round((1 - a) * (rounds - 1))]


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    try:
        return statistics.correlation(xs, ys, method="ranked")
    except statistics.StatisticsError:  # one side constant
        return None


# --- thresholds ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Thresholds:
    # neutral knobs (defaults live in IntegritySettings)
    z: float
    min_group: int
    permutation_rounds: int
    bootstrap_rounds: int
    seed: int
    fixed_rank: float
    shrink_m: float  # pseudo-count towards the difficulty baseline in peer_rate
    # decision thresholds: no defaults anywhere in the repository
    min_n: int  # first-seen plays before performance or timing is judged
    follow_within: timedelta  # a copy pair answered within this of each other
    follow_min: int  # questions both got wrong (copy) or the leader got wrong first (relay) before a test
    follow_z: float  # copy: same wrong answer more often than chance, Holm over the pairs at its tail
    follow_relay_z: float  # relay: right after the leader was wrong, against the follower's own record, Holm
    reading_floor_s: float
    reading_cps: float  # floor = max(reading_floor_s, text length / reading_cps)
    below_floor_share: float
    narrow_sd_log: float  # sd of ln(seconds) at or below this ...
    flat_corr: float  # ... and |spearman(seconds, length)| at or below this: narrow and length-insensitive
    hard_residual_z: float
    away_z: float
    upstream_min: int
    upstream_z: float
    split: date | None = None
    # the canary and the signal context: required by the CLI only for the checks that read them
    canary_alpha: float | None = None  # false flags per season, Bonferroni over canary_m
    canary_beta: float | None = None  # only labels the end state `no sign`
    canary_follow: float | None = None  # H1: share of wrong answers after a long copy that follow the note
    # placebo, draw check and exclusion; separate so a strict α doesn't blind them
    canary_control_alpha: float | None = None
    canary_nudge: float | None = None  # composite H0: honest readers nudged to the decoy up to this share
    canary_m: int | None = None  # people who can play ranked this season, fixed for the season
    away_undeclared_s: float | None = None


# --- the replay ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Play:
    """One ranked attempt as services/xp.grant received it."""

    correct: bool | None
    mode: str  # "daily" or "mock"
    ranked: bool  # mock_sessions.counted; True for dailies
    area: str | None
    answer_kind: str
    difficulty: int
    options: int
    right_options: int
    hint: bool  # False for a timeout, whatever hint_used says
    repeat: bool
    late: bool
    passed: bool
    again_today: bool  # False for a daily timeout
    lp: float  # stored attempts.lp


def replay_lp(
    plays: Sequence[Play], start: float, *, fixed: float | None = None, miss0: int = 0
) -> list[float]:
    """LP per play in grading order, as services/xp.grant computes it: the bad run counts only first-time ranked
    plays, an unranked play moves nothing and leaves the run alone. Walked (fixed None): from `start`, clipped at
    0 and rounded as grant stores it. Fixed: every play priced at `fixed` points, no walk and no clip, so the
    placement head start is gone (the bad run still walks)."""
    points, miss, out = start, miss0, []
    for p in plays:
        run = p.ranked and not p.repeat and not p.again_today
        at = points if fixed is None else fixed
        lp = rank_rules.lp_award(
            p.correct,
            at,
            p.difficulty,
            p.mode,
            area=p.area,
            answer_kind=p.answer_kind,
            options=p.options,
            right_options=p.right_options,
            hint=p.hint,
            repeat=p.repeat,
            late=p.late,
            passed=p.passed,
            again_today=p.again_today,
            miss_streak=miss if run else 0,
        )
        amount = lp.amount if p.ranked else 0.0
        if run:
            miss = min(rank_rules.next_miss_streak(miss, p.correct, p.passed, p.late), 99)
        if fixed is not None:
            out.append(amount)
            continue
        after = max(0.0, round(points + amount, 2))
        out.append(round(after - points, 2))
        points = after
    return out


def miss_after(plays: Iterable[Play], miss0: int = 0) -> int:
    """The bad run after these plays, as grant leaves users.miss_streak: a season change doesn't reset it."""
    miss = miss0
    for p in plays:
        if p.ranked and not p.repeat and not p.again_today:
            miss = min(rank_rules.next_miss_streak(miss, p.correct, p.passed, p.late), 99)
    return miss


# --- flags derived from a player's history (mirroring xp.last_seen and xp.answered_today) -------------------


@dataclass(frozen=True)
class Row:
    """One attempt of one user, any mode."""

    id: int
    question_id: int
    mode: str
    created_at: datetime
    submitted_at: datetime | None
    correct: bool | None
    answered: bool  # answer != {}
    day: date | None
    area: str | None
    run_started_at: datetime | None  # mock_sessions.started_at
    counted: bool  # mock_sessions.counted; True otherwise
    late: bool
    passed: bool
    hint_used: bool
    lp: float


@dataclass(frozen=True)
class QuestionInfo:
    """A question's current values (the guide lists them as approximations of the values at answer time)."""

    area: str
    answer_kind: str
    difficulty: int
    options: int
    right_options: int
    text_len: int  # the text and the live options' texts
    graded: bool
    has_images: bool


def graded_at(r: Row) -> datetime:
    """When the row was graded: a practice or live answer on creation, a timed one on submit."""
    if r.mode in ("practice", "live"):
        return r.created_at
    return r.submitted_at or NEVER


def grading_order(r: Row) -> tuple[datetime, int, int]:
    """The order grant saw the rows in: by grading time; at the same instant the nightly job closes the dailies
    before the mock questions (services/maintenance.run), then by id."""
    return graded_at(r), 0 if r.mode == "daily" else 1, r.id


def _before(r: Row, play: Row) -> bool:
    return grading_order(r) < grading_order(play)


def hidden_mock(r: Row, since: datetime) -> bool:
    return r.mode == "mock" and not r.answered and r.submitted_at is not None and r.submitted_at >= since


def season_anchor(r: Row) -> datetime:
    return r.run_started_at or r.created_at


@dataclass(frozen=True)
class PerPlayer:
    """Season 1b days: from `rules_from` a day with no shared draw has no daily_questions row, and
    `first_started` holds when the first player started each question that day."""

    rules_from: date
    first_started: Mapping[tuple[date, int], datetime]


def running_since(
    day: date,
    area: str | None,
    drawn_at: Mapping[tuple[date, str], datetime],
    question_id: int | None = None,
    per_player: PerPlayer | None = None,
) -> datetime:
    """daily._running_since: when the day's question in `area` started running, never before midnight. With no
    shared draw on a day from the switch, when the first player started this question that day."""
    midnight = madrid_midnight(day)
    drawn = drawn_at.get((day, area or ""))
    if drawn is None and per_player is not None and question_id is not None and day >= per_player.rules_from:
        drawn = per_player.first_started.get((day, question_id))
    return max(midnight, drawn) if drawn else midnight


def _hidden_since(
    play: Row, drawn_at: Mapping[tuple[date, str], datetime], per_player: PerPlayer | None = None
) -> datetime | None:
    if play.mode != "daily":
        return None
    return running_since(
        play.day or madrid_day(play.created_at), play.area, drawn_at, play.question_id, per_player
    )


def is_repeat(
    play: Row,
    history: Sequence[Row],
    drawn_at: Mapping[tuple[date, str], datetime],
    per_player: PerPlayer | None = None,
) -> bool:
    """xp.last_seen as the real path called it: the season from the play's own clock (a daily's submit, the
    nightly job's for a timeout; a mock run's start), another graded row of the question before this one was
    graded, its season anchor in that season; for a daily, mock questions hidden since it started running
    don't count."""
    clock = play.run_started_at if play.mode == "mock" and play.run_started_at else graded_at(play)
    season_start = madrid_midnight(first_day("season", madrid_day(clock)))
    hidden = _hidden_since(play, drawn_at, per_player)
    return any(
        r.id != play.id
        and r.question_id == play.question_id
        and r.correct is not None
        and _before(r, play)
        and season_anchor(r) >= season_start
        and not (hidden and hidden_mock(r, hidden))
        for r in history
    )


def is_again_today(
    play: Row,
    history: Sequence[Row],
    drawn_at: Mapping[tuple[date, str], datetime],
    per_player: PerPlayer | None = None,
) -> bool:
    """xp.answered_today as called: never for a daily timeout (the nightly job passes nothing); otherwise
    another row of the question submitted (or practised) before this one, shown since the Madrid midnight of
    this play's submit; for a daily answer, hidden mock questions don't count."""
    if play.mode == "daily" and not play.answered:
        return False
    now = graded_at(play)
    start = madrid_midnight(madrid_day(now))
    hidden = _hidden_since(play, drawn_at, per_player)
    return any(
        r.id != play.id
        and r.question_id == play.question_id
        and (r.mode == "practice" or r.submitted_at is not None)
        and _before(r, play)
        and r.created_at >= start
        and not (hidden and hidden_mock(r, hidden))
        for r in history
    )


def pre_seen(
    play: Row,
    history: Sequence[Row],
    drawn_at: Mapping[tuple[date, str], datetime] | None = None,
    per_player: PerPlayer | None = None,
) -> bool:
    """Any earlier graded row of the question, in any mode and season: the player had seen its answer.
    Mock questions closed unanswered while the daily was running (hidden from the player) don't count."""
    hidden = _hidden_since(play, drawn_at or {}, per_player)
    return any(
        r.id != play.id
        and r.question_id == play.question_id
        and r.correct is not None
        and _before(r, play)
        and not (hidden and hidden_mock(r, hidden))
        for r in history
    )


def pre_seen_lp_share(plays: Iterable[tuple[float, bool]]) -> tuple[float, int]:
    """(share of the positive LP earned on pre-seen questions, number of pre-seen plays) over (lp, pre_seen)."""
    total = seen = 0.0
    n = 0
    for lp, was_seen in plays:
        n += was_seen
        if lp > 0:
            total += lp
            seen += lp if was_seen else 0.0
    return (seen / total if total else 0.0), n


def to_play(
    play: Row,
    history: Sequence[Row],
    drawn_at: Mapping[tuple[date, str], datetime],
    question: QuestionInfo,
    per_player: PerPlayer | None = None,
) -> Play:
    return Play(
        correct=play.correct,
        mode=play.mode,
        ranked=play.counted,
        area=play.area or question.area,
        answer_kind=question.answer_kind,
        difficulty=question.difficulty,
        options=question.options,
        right_options=question.right_options,
        hint=play.hint_used and play.answered,
        repeat=is_repeat(play, history, drawn_at, per_player),
        late=play.late,
        passed=play.passed,
        again_today=is_again_today(play, history, drawn_at, per_player),
        lp=play.lp,
    )


# --- baselines -------------------------------------------------------------------------------------------------


def difficulty_baseline(first_answers: Iterable[tuple[int, bool]]) -> dict[int, float]:
    """The cohort's first-answer accuracy per difficulty; 0.5 where nobody answered."""
    counts: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for d, right in first_answers:
        counts[d][0] += right
        counts[d][1] += 1
    out = {d: 0.5 for d in range(1, 6)}
    out.update({d: r / n for d, (r, n) in counts.items() if n})
    return out


def peer_rate(q_right: int, q_n: int, y: bool, p_d: float, m: float) -> float:
    """Leave-one-out rate on the question, shrunk towards the difficulty baseline: (R - y + m p_d) / (N - 1 + m)."""
    denom = q_n - 1 + m
    if denom <= 0:
        return p_d
    return (q_right - y + m * p_d) / denom


def _logit(p: float) -> float:
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


def _expit(x: float) -> float:
    return 1 / (1 + math.exp(-x)) if x >= 0 else math.exp(x) / (1 + math.exp(x))


def ability_shift(base: Sequence[tuple[bool, float]]) -> tuple[float, float]:
    """(mode, variance) of a person's ability δ in logits, with right ~ Bernoulli(expit(logit(peer) + δ)) over
    (right, peer rate) pairs and a N(0, ABILITY_SD²) prior: how much better than their peers they are."""
    prior = 1 / ABILITY_SD**2
    logits = [_logit(p) for _, p in base]
    d = 0.0
    for _ in range(100):
        qs = [_expit(x + d) for x in logits]
        g = sum(y - q for (y, _), q in zip(base, qs, strict=True)) - d * prior
        h = sum(q * (1 - q) for q in qs) + prior
        step = max(-2.0, min(2.0, g / h))
        d += step
        if abs(step) < 1e-9:
            break
    info = sum(_expit(x + d) * (1 - _expit(x + d)) for x in logits) + prior
    return d, 1 / info


# Normal quadrature for the uncertainty of δ: evenly spaced, weights from the density.
_NODES = [-4 + 8 * k / 16 for k in range(17)]
_WEIGHTS = [math.exp(-x * x / 2) for x in _NODES]
_WEIGHTS = [w / sum(_WEIGHTS) for w in _WEIGHTS]


@dataclass(frozen=True)
class Anomaly:
    """Right answers on `test` items against what the person's own `base` items predict."""

    n: int
    right: int
    expected: float
    p: float
    base_n: int

    def z(self) -> float | None:
        return z_of(self.p) if self.n else None


def anomaly(base: Sequence[tuple[bool, float]], test: Sequence[tuple[bool, float]]) -> Anomaly:
    """A within-person test: the ability δ is fitted on `base`, and the p-value of the right answers on `test` is
    the exact Poisson-binomial tail averaged over δ's uncertainty. A person who is simply stronger than their
    peers is stronger on both, so this is about N(0, 1) for an honest one, unlike a residual against the peers."""
    k = sum(y for y, _ in test)
    if not test:
        return Anomaly(0, 0, 0.0, 1.0, len(base))
    d, var = ability_shift(base)
    sd = math.sqrt(var)
    logits = [_logit(q) for _, q in test]
    p = expected = 0.0
    for x, w in zip(_NODES, _WEIGHTS, strict=True):
        qs = [_expit(lg + d + sd * x) for lg in logits]
        p += w * poisson_binomial_sf(qs, k)
        expected += w * sum(qs)
    return Anomaly(len(test), k, expected, min(1.0, p), len(base))


# --- cohort checks ---------------------------------------------------------------------------------------------


def permutation_p(a: Sequence[float], b: Sequence[float], *, rounds: int, seed: int) -> float | None:
    """One-sided p of mean(a) - mean(b) at least as large as observed, with the labels shuffled."""
    if not a or not b:
        return None
    observed = statistics.fmean(a) - statistics.fmean(b)
    pooled = list(a) + list(b)
    rng = random.Random(seed)
    hits = 0
    for _ in range(rounds):
        rng.shuffle(pooled)
        stat = statistics.fmean(pooled[: len(a)]) - statistics.fmean(pooled[len(a) :])
        hits += stat >= observed - 1e-12
    return (hits + 1) / (rounds + 1)


def gradient(by_difficulty: Mapping[int, tuple[int, int]], min_side: int) -> float | None:
    """Hard (difficulty 4-5) accuracy over easy (1-2) accuracy; near 1 is flat. Context, never a flag."""
    hard = [by_difficulty[d] for d in by_difficulty if d >= HARD]
    easy = [by_difficulty[d] for d in by_difficulty if d <= 2]
    hr, hn = sum(r for r, _ in hard), sum(n for _, n in hard)
    er, en = sum(r for r, _ in easy), sum(n for _, n in easy)
    if hn < max(min_side, 1) or en < max(min_side, 1) or er == 0:
        return None
    return (hr / hn) / (er / en)


def top_composition(ordered_keys: Sequence[int], group_of: Mapping[int, str], k: int) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for key in ordered_keys[:k]:
        out[group_of.get(key) or "none"] += 1
    return dict(out)


# --- follow-the-leader -----------------------------------------------------------------------------------------


def canonical_answer(answer: Mapping[str, Any], answer_kind: str) -> str | None:
    """One comparable string per answer: 'pass', 'o:1,4' for options, 'n:12.5|3' for numbers, 'v:<text>'."""
    if not answer:
        return None
    if answer.get("unsure"):
        return "pass"
    options = answer.get("options")
    if options or answer_kind.startswith("choice"):
        return "o:" + ",".join(str(o) for o in sorted(options or []))
    text = str(answer.get("value") or "")
    parsed = keys.numbers(text) or ([n] if (n := keys.number(text)) else None)
    if parsed:
        return "n:" + "|".join(f"{float(x['v']):.10g}" for x in parsed)
    return "v:" + keys.normal_text(text)


@dataclass(frozen=True)
class DailyAnswer:
    user: int
    question_id: int
    started_at: datetime
    submitted_at: datetime
    answer: str
    right: bool
    passed: bool
    seen: bool = False  # the player had seen this question's answer before (practice, another mode)

    @property
    def wrong(self) -> bool:
        return not self.right and not self.passed


@dataclass(frozen=True)
class CopyPair:
    """Two players, a < b, on the questions both answered within `within` of each other. A shared wrong answer is
    symmetric evidence: it says the two are linked, not which one copied."""

    a: int
    b: int
    items: int
    both_wrong: int
    shared_wrong: int  # the same wrong answer
    expected: float  # by chance, from how the other players' wrong answers spread
    p: float  # exact upper tail of shared_wrong
    a_submitted_first: int
    a_started_first: int
    median_dt_s: float | None

    def z(self) -> float | None:
        return z_of(self.p) if self.both_wrong else None


@dataclass(frozen=True)
class Relay:
    """A leader and a later player on the same question, at any delay: the leader saw the right answer on
    submitting, so a relayed key shows as the follower being right where the leader was wrong, more often than
    the follower's own other answers predict."""

    leader: int
    follower: int
    after: int  # questions the follower answered after the leader
    test: Anomaly  # on those the leader got wrong (not a pass)
    median_dt_s: float | None


def _coincide(others_wrong: Mapping[str, int], a: str, b: str) -> float:
    """Chance that two independent wrong answers are the same, from the other players' wrong answers: add-a-half
    smoothed over the answers seen and one more for any other, so a wrong answer nobody else gave still has a
    chance and a question nobody else got wrong gives about a half."""
    values = set(others_wrong) | {a, b}
    total = sum(others_wrong.values()) + 0.5 * (len(values) + 1)
    return sum(((others_wrong.get(v, 0) + 0.5) / total) ** 2 for v in values) + (0.5 / total) ** 2


def _apart(o: DailyAnswer, a: DailyAnswer, b: DailyAnswer, within: timedelta) -> bool:
    """Someone who could not have been copying with either of the pair: outside the window of both."""
    return all(o.user != x.user and abs(o.submitted_at - x.submitted_at) > within for x in (a, b))


def follow_pairs(
    answers: Sequence[DailyAnswer], within: timedelta, min_items: int, shrink_m: float
) -> tuple[list[CopyPair], list[Relay]]:
    """The pairs that have enough items to be tested: copy pairs with at least `min_items` questions both got
    wrong within `within` of each other (how wrong answers spread is read from the players outside that window,
    so a ring of copiers doesn't make its own answer look popular), relays with at least `min_items` questions the leader got wrong before
    the follower answered. The peer rate on a question leaves the pair out and is shrunk towards the overall
    rate, so the relay test asks about the follower against their own record, not against the cohort. A question
    the follower had seen before is neither evidence nor part of their record."""
    by_q: dict[int, list[DailyAnswer]] = defaultdict(list)
    mine: dict[int, dict[int, DailyAnswer]] = defaultdict(dict)
    for a in answers:
        by_q[a.question_id].append(a)
        mine[a.user][a.question_id] = a
    overall = (sum(a.right for a in answers) + 1) / (len(answers) + 2)
    rights = {q: sum(a.right for a in qa) for q, qa in by_q.items()}

    def peer(q: int, *leave: DailyAnswer) -> float:
        return (rights[q] - sum(a.right for a in leave) + shrink_m * overall) / (
            len(by_q[q]) - len(leave) + shrink_m
        )

    copies: dict[tuple[int, int], dict[str, Any]] = {}
    relays: dict[tuple[int, int], dict[str, Any]] = {}
    for q, qa in by_q.items():
        for x, y in itertools.combinations(qa, 2):
            if x.user == y.user:
                continue
            a, b = (x, y) if x.user < y.user else (y, x)
            dt = abs(a.submitted_at - b.submitted_at)
            if dt <= within:
                c = copies.setdefault(
                    (a.user, b.user), {"items": 0, "sub": 0, "start": 0, "dt": [], "ps": [], "shared": 0}
                )
                c["items"] += 1
                c["sub"] += a.submitted_at < b.submitted_at
                c["start"] += a.started_at < b.started_at
                c["dt"].append(dt.total_seconds())
                if a.wrong and b.wrong:
                    others = Counter(o.answer for o in qa if o.wrong and _apart(o, a, b, within))
                    c["ps"].append(_coincide(others, a.answer, b.answer))
                    c["shared"] += a.answer == b.answer
            if a.submitted_at == b.submitted_at:
                continue
            lead, f = (a, b) if a.submitted_at < b.submitted_at else (b, a)
            r = relays.setdefault((lead.user, f.user), {"after": 0, "dt": [], "test": []})
            r["after"] += 1
            r["dt"].append((f.submitted_at - lead.submitted_at).total_seconds())
            if lead.wrong and not f.seen:
                r["test"].append((q, f.right, peer(q, lead, f)))

    copy_out = [
        CopyPair(
            a=a,
            b=b,
            items=c["items"],
            both_wrong=len(c["ps"]),
            shared_wrong=c["shared"],
            expected=sum(c["ps"]),
            p=poisson_binomial_sf(c["ps"], c["shared"]),
            a_submitted_first=c["sub"],
            a_started_first=c["start"],
            median_dt_s=statistics.median(c["dt"]),
        )
        for (a, b), c in sorted(copies.items())
        if len(c["ps"]) >= min_items
    ]
    relay_out = []
    for (leader, follower), r in sorted(relays.items()):
        if len(r["test"]) < min_items:
            continue
        tested = {q for q, _, _ in r["test"]}
        base = [(a.right, peer(q, a)) for q, a in mine[follower].items() if q not in tested and not a.seen]
        relay_out.append(
            Relay(
                leader=leader,
                follower=follower,
                after=r["after"],
                test=anomaly(base, [(y, p) for _, y, p in r["test"]]),
                median_dt_s=statistics.median(r["dt"]),
            )
        )
    return copy_out, relay_out


@dataclass(frozen=True)
class Follow:
    """The pairs tested and the ones Holm rejects, each test its own family at its configured level."""

    copies: list[CopyPair]
    relays: list[Relay]
    copy_flagged: list[CopyPair] = field(default_factory=list)
    relay_flagged: list[Relay] = field(default_factory=list)

    @property
    def flagged(self) -> set[int]:
        """Both players of a copy pair (who copied isn't known), the follower of a relay."""
        return {u for c in self.copy_flagged for u in (c.a, c.b)} | {r.follower for r in self.relay_flagged}

    @property
    def tested(self) -> set[int]:
        return {u for c in self.copies for u in (c.a, c.b)} | {r.follower for r in self.relays}

    def expected_false(self, t: Thresholds) -> float:
        """At most this many people flagged by chance: Holm keeps each family's chance of any false pair at its
        level, and a copy pair names two."""
        return (2 * tail(t.follow_z) if self.copies else 0.0) + (
            tail(t.follow_relay_z) if self.relays else 0.0
        )


def follow_flags(copies: Sequence[CopyPair], relays: Sequence[Relay], t: Thresholds) -> Follow:
    copy_hit = holm([c.p for c in copies], tail(t.follow_z))
    relay_hit = holm([r.test.p for r in relays], tail(t.follow_relay_z))
    return Follow(
        list(copies),
        list(relays),
        [c for c, hit in zip(copies, copy_hit, strict=True) if hit],
        [r for r, hit in zip(relays, relay_hit, strict=True) if hit],
    )


# --- latency ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Latency:
    n: int
    sd_log: float | None  # pstdev of ln(max(seconds, 0.5)); None when n < 2
    corr_length: float | None  # spearman(seconds, text length); None when n < 3 or a side is constant
    below_floor: int
    median_s: float | None
    floor_n: int = 0  # plays the floor applies to (questions with images are left out); 0 means n


def reading_floor(text_len: int, t: Thresholds) -> float:
    return max(t.reading_floor_s, text_len / t.reading_cps) if t.reading_cps > 0 else t.reading_floor_s


def latency_profile(
    samples: Sequence[tuple[float, int]], t: Thresholds, *, images: Sequence[bool] = ()
) -> Latency:
    """(seconds, text length) per play. Plays on questions with images keep their latency for the spread but
    not for the reading floor, which only knows the text."""
    seconds = [s for s, _ in samples]
    exempt = list(images) or [False] * len(samples)
    floor = [(s, n) for (s, n), img in zip(samples, exempt, strict=True) if not img]
    return Latency(
        n=len(samples),
        sd_log=statistics.pstdev([math.log(max(s, 0.5)) for s in seconds]) if len(seconds) >= 2 else None,
        corr_length=spearman(seconds, [float(n) for _, n in samples]),
        below_floor=sum(1 for s, n in floor if s < reading_floor(n, t)),
        median_s=statistics.median(seconds) if seconds else None,
        floor_n=len(floor),
    )


def timing_positive(lat: Latency, t: Thresholds) -> bool | None:
    """Mostly below the reading floor, or narrow and blind to the question's length (a constant latency is
    both). None under min_n."""
    if lat.n < t.min_n:
        return None
    floor_n = lat.floor_n or lat.n
    if floor_n and lat.below_floor / floor_n >= t.below_floor_share:
        return True
    flat = lat.corr_length is None or abs(lat.corr_length) <= t.flat_corr
    return lat.sd_log is not None and lat.sd_log <= t.narrow_sd_log and flat


# --- the person ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Person:
    key: int
    n: int
    right: int
    timeouts: int
    late: int
    n_first: int
    n_preseen: int
    pre_seen_lp_share: float
    hard_z: float | None  # hard items against the person's own easier ones
    hard_n: int
    hard_base_n: int
    gradient: float | None
    away_z: float | None
    away_n: int
    home_n: int
    latency: Latency
    following: bool
    upstream_matches: int
    upstream_expected: float
    upstream_p: float  # exact upper tail of the matches
    upstream_n: int
    upstream_typed: int
    follow_tested: bool = False  # in a copy pair or the follower of a relay that was tested
    canary: Canary | None = None  # None: no copy-arm trials (or nothing collected)
    signals: Context | None = None  # context only: never part of a family

    def upstream_z(self) -> float | None:
        return z_of(self.upstream_p) if self.upstream_n else None


def families(p: Person, t: Thresholds, following: bool) -> dict[str, bool | None]:
    """True (positive), False (looked, nothing) or None (not enough data) per evidence family."""
    perf: list[bool] = []
    if p.n_first >= t.min_n:
        if p.hard_z is not None and min(p.hard_n, p.hard_base_n) >= t.min_n:
            perf.append(p.hard_z >= t.hard_residual_z)
        if p.away_z is not None and min(p.away_n, p.home_n) >= t.min_n:
            perf.append(p.away_z >= t.away_z)
    timing = timing_positive(p.latency, t) if p.n_first >= t.min_n else None
    prov: list[bool] = []
    if following or p.following or p.follow_tested:
        prov.append(following or p.following)
    uz = p.upstream_z()
    if p.upstream_n >= t.upstream_min:
        prov.append(uz is not None and uz >= t.upstream_z)
    if p.canary is not None and p.canary.decision == "reject":
        prov.append(True)  # any other canary outcome is no evidence either way
    return {
        "performance": any(perf) if perf else None,
        "timing": timing,
        "provenance": any(prov) if prov else None,
        "supervised": None,
    }


def conversation(flags: Mapping[str, bool | None]) -> bool:
    """Worth a conversation only when at least two families agree."""
    return sum(v is True for v in flags.values()) >= 2


def independent(flags: Mapping[str, bool | None]) -> bool:
    """Whether a family that doesn't share the accuracy and timing data is among the positives."""
    return flags.get("provenance") is True or flags.get("supervised") is True


def expected_false_flags(eligible: int, z: float) -> float:
    """How many of `eligible` people a one-sided threshold at `z` flags by chance alone."""
    return eligible * tail(z)


# --- small groups in cohort tables -----------------------------------------------------------------------------


def merge_groups(groups: Mapping[str, Sequence[Any]], min_group: int) -> dict[str, list[Any]]:
    """Groups under min_group are pooled as 'other'; a pool still under min_group joins the largest group. Every
    group printed then has min_group people and together they still cover everyone, so no group is left out for
    a reader to recover by subtracting the printed ones from a total."""
    big = {g: list(m) for g, m in groups.items() if len(m) >= min_group}
    small = [u for g in sorted(groups) if len(groups[g]) < min_group for u in groups[g]]
    if not small:
        return big
    if len(small) >= min_group:
        return {**big, OTHER: small}
    if not big:
        return {}
    largest = max(big, key=lambda g: (len(big[g]), g))
    members = big.pop(largest)
    return {**big, f"{largest} + {OTHER}": members + small}


def _null_space(rows: list[list[Fraction]], width: int) -> list[list[Fraction]]:
    """A basis of the vectors orthogonal to every row: a vector is a combination of the rows when it is
    orthogonal to all of these."""
    rows = [r[:] for r in rows]
    pivots: list[int] = []
    for c in range(width):
        r = len(pivots)
        pivot = next((i for i in range(r, len(rows)) if rows[i][c] != 0), None)
        if pivot is None:
            continue
        rows[r], rows[pivot] = rows[pivot], rows[r]
        rows[r] = [x / rows[r][c] for x in rows[r]]
        for i in range(len(rows)):
            if i != r and rows[i][c] != 0:
                f = rows[i][c]
                rows[i] = [x - f * y for x, y in zip(rows[i], rows[r], strict=True)]
        pivots.append(c)
    basis = []
    for free in (c for c in range(width) if c not in pivots):
        v = [Fraction(0)] * width
        v[free] = Fraction(1)
        for r, c in enumerate(pivots):
            v[c] = -rows[r][free]
        basis.append(v)
    return basis


def discloses(tables: Sequence[Mapping[str, Collection[Hashable]]], min_group: int) -> bool:
    """Whether the groups printed by several tables over the same people single out fewer than min_group of them:
    a set of people under min_group whose totals are a sum and difference of printed group totals (a vertical
    minus the one position nested in it, say)."""
    people = {u for table in tables for members in table.values() for u in members}
    label = [{u: g for g, members in table.items() for u in members} for table in tables]
    cells = Counter(tuple(lb.get(u) for lb in label) for u in people)
    order = sorted(cells, key=repr)
    rows = [[Fraction(cell[k] == g) for cell in order] for k, table in enumerate(tables) for g in table]
    null = _null_space(rows, len(order))
    small = [k for k, c in enumerate(order) if cells[c] < min_group]
    for size in range(1, min_group):
        for combo in itertools.combinations(small, size):
            if sum(cells[order[k]] for k in combo) >= min_group:
                continue
            if all(sum(v[k] for k in combo) == 0 for v in null):
                return True
    return False


# --- the AI canary (ADR 0010 D) ----------------------------------------------------------------------------------

VOID = (
    "not single choice",
    "options changed",
    "too few options",
    "too few wrong options",
    "decoy right",
    "hint",
    "not one wrong option",
)


def walk_from(rules_from: date, until: date) -> date:
    """Where the canary's walk starts for a window ending at `until`: the rule date, or the season's 1 September
    once the season started after it. A window that starts later is a new look at the data (exploratory)."""
    return max(rules_from, first_day("season", until - timedelta(days=1)))


@dataclass(frozen=True)
class DecoyPlay:
    """A ranked attempt that carried a decoy, with the question's options as they are now."""

    decoy: int
    chosen: tuple[int, ...]
    answer_kind: str
    passed: bool
    hint: bool
    long_copies: int | None
    resumes: int | None
    live: frozenset[int]
    right: frozenset[int]  # empty if the effective key is not a choice key
    changed: bool = False  # changed upstream after the attempt: the options may not be those offered


def canary_trial(d: DecoyPlay) -> tuple[float, bool] | str:
    """(chance of a hit under H0, hit) or the reason the attempt is no trial. The decoy is drawn uniformly over the
    options offered, independently of the key and the player, so given a wrong answer outside C the chance it is
    the decoy is exactly 1/(n - |C|), however the player's wrong answers spread. A key corrected later is still
    independent of the draw; only the offered set matters."""
    if d.answer_kind != "choice-one":
        return "not single choice"
    if d.changed or d.decoy not in d.live or any(c not in d.live for c in d.chosen):
        return "options changed"
    n = len(d.live)
    if n < MIN_DECOY_OPTIONS:
        return "too few options"
    if not d.right or not d.right <= d.live:
        return "options changed"
    if n - len(d.right) < 2:
        return "too few wrong options"
    if d.decoy in d.right:
        return "decoy right"
    if d.hint:
        return "hint"
    if d.passed or len(d.chosen) != 1 or d.chosen[0] in d.right:
        return "not one wrong option"
    return 1 / (n - len(d.right)), d.chosen[0] == d.decoy


def canary_arm(d: DecoyPlay) -> str | None:
    """`copy` after a long copy (the note went with it); `placebo` with neither a copy nor a reload, which resets
    the page's counters; `unreported` when the page sent no totals (an older page or a tampered one). None: a reload
    and no copy, where a copy may have been lost: no control and no decision, only the listing."""
    if d.long_copies is None:
        return "unreported"
    if d.long_copies >= 1:
        return "copy"
    return "placebo" if d.resumes == 0 else None


def draw_hit(d: DecoyPlay) -> tuple[float, bool] | None:
    """(|C|/n, decoy in C): whether the draw looks at the key, whatever the player did."""
    if (
        d.answer_kind != "choice-one"
        or d.changed
        or d.decoy not in d.live
        or len(d.live) < MIN_DECOY_OPTIONS
        or not d.right
        or not d.right <= d.live
    ):
        return None
    return len(d.right) / len(d.live), d.decoy in d.right


def llr_walk(trials: Sequence[tuple[float, bool]], follow: float, nudge: float = 0.0) -> list[float]:
    """The running log likelihood ratio after each trial of H1 (p1 = p0 + f(1 - p0)) against the composite null's
    edge p0' = p0 + g0(1 - p0). The ratio is a supermartingale for any true rate up to p0', so Ville's bound holds
    for honest readers nudged towards the decoy up to g0."""
    out, llr = [], 0.0
    for p0, hit in trials:
        q0 = p0 + nudge * (1 - p0)
        p1 = p0 + follow * (1 - p0)
        llr += math.log(p1 / q0) if hit else math.log((1 - p1) / (1 - q0))
        out.append(llr)
    return out


@dataclass(frozen=True)
class Canary:
    trials: int
    hits: int
    expected: float  # sum of p0' over the trials
    p: float  # fixed-window P(X >= hits) at p0': context, uncorrected
    decision: str  # reject | no sign | continue | ignored | exploratory | listed
    decided_at: int | None  # the first trial whose LLR reached ln(M/α)
    p_any: float = 1.0  # anytime-valid: min(1, 1/max LR), uncorrected
    llr_final: float = 0.0
    earlier_stretch: bool = False  # a reject whose walk has fallen back below the boundary since
    note: str | None = None  # why it is ignored

    def z(self) -> float | None:
        return z_of(self.p) if self.trials else None


def _walk(
    trials: Sequence[tuple[float, bool]],
    *,
    alpha: float,
    beta: float | None,
    follow: float,
    nudge: float,
    m: int,
    crossed: str,
) -> Canary:
    llr = llr_walk(trials, follow, nudge)
    bound = math.log(m / alpha) - 1e-12
    q0 = [p0 + nudge * (1 - p0) for p0, _ in trials]
    hits = sum(hit for _, hit in trials)
    decided = next((j + 1 for j, x in enumerate(llr) if x >= bound), None)
    if decided is not None:
        decision = crossed
    elif beta is not None and llr[-1] <= math.log(beta / (1 - alpha)):
        decision = "no sign"
    else:
        decision = "continue"
    return Canary(
        trials=len(trials),
        hits=hits,
        expected=sum(q0),
        p=poisson_binomial_sf(q0, hits),
        decision=decision,
        decided_at=decided,
        p_any=min(1.0, math.exp(-max(0.0, *llr))),
        llr_final=llr[-1],
        earlier_stretch=decided is not None and llr[-1] < bound,
    )


def canary_evidence[K: Hashable](
    walks: Mapping[K, Sequence[tuple[float, bool]]],
    *,
    alpha: float,
    beta: float,
    follow: float,
    nudge: float,
    m: int,
) -> dict[K, Canary]:
    """Per key, the copy-arm trials (p0, hit) in grading order. A walk that ever reaches ln(m/alpha) is a reject:
    Ville's bound and Bonferroni over a fixed m per season keep the chance of any false reject at alpha, read at
    any time, and a reject stays one as the window grows over the same trials (a later upstream change or key
    correction can remove or reprice earlier ones). `no sign` only labels a walk that ends at or below
    ln(beta / (1 - alpha)); it clears no one. Keys without trials are absent."""
    return {
        k: _walk(w, alpha=alpha, beta=beta, follow=follow, nudge=nudge, m=m, crossed="reject")
        for k, w in walks.items()
        if w
    }


def listing[K: Hashable](
    walks: Mapping[K, Sequence[tuple[float, bool]]], *, alpha: float, follow: float, nudge: float, m: int
) -> dict[K, Canary]:
    """The same walk over the decoy picks without a reported copy (placebo, unreported and reloaded attempts): the
    keys whose walk crosses the canary's boundary. A pointer for a reviewer, never a family."""
    out = {
        k: _walk(w, alpha=alpha, beta=None, follow=follow, nudge=nudge, m=m, crossed="listed")
        for k, w in walks.items()
        if w
    }
    return {k: c for k, c in out.items() if c.decision == "listed"}


@dataclass(frozen=True)
class Tail:
    trials: int
    hits: int
    expected: float
    p_high: float
    p_low: float
    verdict: str  # "near chance" | "off"


def _tail(trials: Sequence[tuple[float, bool]]) -> tuple[int, float, float, float]:
    ps = [p for p, _ in trials]
    hits = sum(hit for _, hit in trials)
    low, high = poisson_binomial_tails(ps, hits)
    return hits, sum(ps), high, low


def _two_sided(trials: Sequence[tuple[float, bool]], alpha: float) -> Tail:
    hits, expected, high, low = _tail(trials)
    return Tail(
        len(trials), hits, expected, high, low, "off" if min(high, low) < alpha / 2 else "near chance"
    )


def placebo_tail(trials: Sequence[tuple[float, bool]], alpha: float) -> Tail:
    """Hits without a long copy at p0, two-sided at alpha/2 per tail: an excess means the decoy is picked without
    the note, a deficit that it is visible (and avoided) without it. Either makes the copy arm unreliable."""
    return _two_sided(trials, alpha)


def draw_tail(hits: Sequence[tuple[float, bool]], alpha: float) -> Tail:
    """The decoy is a right option as often as |C|/n says, two-sided at alpha/2 per tail."""
    return _two_sided(hits, alpha)


def loo_off[K: Hashable](
    per_person: Mapping[K, Sequence[tuple[float, bool]]], alpha: float, tail: str
) -> bool:
    """Whether the pooled tail (`high` or `low`, at alpha/2) is off and stays off without the one person who
    pushes it most that way, so a single player can't switch the control off."""

    def p(trials: Sequence[tuple[float, bool]]) -> float:
        _, _, high, low = _tail(trials)
        return high if tail == "high" else low

    if p([x for v in per_person.values() for x in v]) >= alpha / 2:
        return False
    excess = {k: sum(h for _, h in v) - sum(q for q, _ in v) for k, v in per_person.items()}
    worst = max(excess, key=excess.__getitem__) if tail == "high" else min(excess, key=excess.__getitem__)
    return p([x for k, v in per_person.items() if k != worst for x in v]) < alpha / 2


def nudge_check(trials: Sequence[tuple[float, bool]], *, alpha: float, nudge: float) -> bool:
    """Whether copy-arm trials (p0, hit) hit the decoy more often than the composite null's edge p0' allows, upper
    tail at alpha: honest readers nudged beyond g0, or followers the walk doesn't catch. A warning only."""
    q0 = [p0 + nudge * (1 - p0) for p0, _ in trials]
    return bool(trials) and poisson_binomial_sf(q0, sum(h for _, h in trials)) < alpha


@dataclass(frozen=True)
class Recorded:
    """The signal totals of one ranked attempt that carries them."""

    away_undeclared_s: int | None
    away_declared_s: int | None
    pasted: bool | None
    long_copies: int | None
    resumes: int
    decoy: bool = False


@dataclass(frozen=True)
class Context:
    n: int
    reported: int
    away_any: int
    away_over: int
    away_median_s: float | None  # among the answers with any
    reported_d: int
    declared_any: int
    declared_median_s: float | None
    pasted: int
    text_n: int
    copied: int  # attempts with a long copy
    copies_n: int
    long_copies: int
    resumed: int
    resumes: int
    unreported: int  # decoy attempts without totals
    decoy_n: int


def _median_above_zero(values: Iterable[int | None]) -> float | None:
    above = [v for v in values if v]
    return statistics.median(above) if above else None


def context(rows: Sequence[Recorded], away_s: float) -> Context | None:
    """Totals of a person's attempts that carry signals; None when none does (not collected)."""
    if not rows:
        return None
    away = [r.away_undeclared_s for r in rows if r.away_undeclared_s is not None]
    declared = [r.away_declared_s for r in rows if r.away_declared_s is not None]
    copies = [r.long_copies for r in rows if r.long_copies is not None]
    pasted = [r.pasted for r in rows if r.pasted is not None]
    return Context(
        n=len(rows),
        reported=len(away),
        away_any=sum(v > 0 for v in away),
        away_over=sum(v > away_s for v in away),
        away_median_s=_median_above_zero(away),
        reported_d=len(declared),
        declared_any=sum(v > 0 for v in declared),
        declared_median_s=_median_above_zero(declared),
        pasted=sum(pasted),
        text_n=len(pasted),
        copied=sum(v >= 1 for v in copies),
        copies_n=len(copies),
        long_copies=sum(copies),
        resumed=sum(r.resumes >= 1 for r in rows),
        resumes=sum(r.resumes for r in rows),
        unreported=sum(r.decoy and r.long_copies is None for r in rows),
        decoy_n=sum(r.decoy for r in rows),
    )
