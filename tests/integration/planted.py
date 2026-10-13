"""The world the integrity report is tested against: forty days of one shared elec daily question, played by
eighteen people whose behaviour is planted, deterministic and known (no randomness), written as ORM rows with the
LP each play really earned (walked through `rank.lp_award` exactly as `xp.grant` does), so the replay of every one
of them reproduces what is stored. An honest player's wrong answer can be anyone's wrong answer, the leader's
included.

    leader        10:00, wrong on 16 fixed days, a human's pace; copied, so in the copy pairs (who copied is
                  not something the data says)
    follower      copies the leader's answer every day, 3-5 s after opening the question
    simultaneous  opens with the leader, answers 140-160 s later (narrow, blind to length) with the leader's answer
    relayer       always answers ten minutes after the leader: right where the leader was wrong (the key the
                  leader saw on submitting), a third right on its own otherwise
    relayer_late  the same, two hours after the leader
    strong_honest 90 % right, after the leader every day, within half an hour of them on the even days only
    practised     practised 24 of the 40 questions the day before the season's first daily: fast and right there
    honest        a plain honest player, with one daily left to run out
    upstream      answers the 8 corrected questions with the upstream key, the rest honestly; practised 6
                  questions first and left one daily to run out
    metronome     a narrow pace that follows the text length: reading, not an answer known in advance
    prodigy       right on every question but the stored-key-wrong one: a strong player, not a flag
    looker        first to play each day, a quarter right on the easy questions and right on every hard one: the
                  look-it-up signature, performance alone, so not a conversation
    mech*         three Mechanical members (one strong on easy, weak on hard)
    drive*        two Driverless 'mingo's: groups too small to print on their own
    alumna        copied the leader until she left the team on 6 October: flagged, never printed

From the rule date on (RULES_FROM, 4 September: day 2) every attempt of the eighteen carries what the services
write, a placebo (no long copy, no reload), a seeded decoy over the four options and, on a quarter of the days, a
little undeclared time away. Seven more members play, each starting at least 45 minutes from anyone else (so no copy
pair, whatever else they do). They are the canary's cast, calibrated to CANARY_ENV and `reference()`:

    canary_follower  Cass: copies and answers the decoy on 18 days (on 2 more the decoy is the key, on 1 a hint was
                     used, on 2 the question changed upstream after her attempt), honest at about 60 % otherwise;
                     one attempt starts a minute before the rule date's midnight and ends after it: it carries
                     signals and must be left out. Rejected, provenance alone.
    late_starter     Lena: 3 copy days answered with a wrong option that is not the decoy, then follows every
                     day; one of those attempts has been purged (every signal NULL). Rejected, later.
    translator       Tia: long copies on 11 days (rulebook into a translator), hours of away time, answers
                     independent of the decoy: allowed behaviour, "no sign"; also one uncounted mock run.
    tab_switcher     Tom: honest, a lot of undeclared away time, reopens every question twice: appears nowhere.
    poisoner         Pia: answers the decoy without copying on 16 days and once after a reload, copies on 4
                     others: tries to push the cohort placebo off. Her own placebo is off (ignored), the pool
                     without her is calm, she is listed.
    forger           Omar: follows the note on 20 days, on 5 of them reporting no long copy and on the rest
                     sending no totals at all: no copy-arm trial, so no decision, but listed.
    performer        Pete: right on every hard question and on a quarter of the easy ones (a performance flag),
                     reopens every question once and is away for minutes: maxed context, which can never be a
                     second family.

Three questions had their wording changed upstream: one after the day's attempts (not yet reviewed), one after
them and acknowledged since (only its audit row is left), one before them (which changes nothing).
"""

from __future__ import annotations

import functools
import itertools
import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.orm import Session

from ifs_tests.db.models import (
    AnswerKey,
    AnswerOption,
    Attempt,
    AuditLog,
    DailyQuestion,
    MockSession,
    Question,
    Quiz,
    QuizQuestion,
    User,
)
from ifs_tests.domain import grading, rank
from ifs_tests.services import review

MADRID = ZoneInfo("Europe/Madrid")
SEASON = 2026
FIRST_DAY = date(2026, 9, 2)
DAYS = 40
LAST_DAY = FIRST_DAY + timedelta(days=DAYS - 1)  # 2026-10-11
UNTIL = date(2026, 10, 12)  # excluded: plays from that day on are left out
OPTION_CHARS = 7
SUSPECT = 5  # the day whose stored key is wrong: everyone answers the true option
UP_DAYS = tuple(range(21, 29))  # the questions a reviewer corrected before the first daily
TIMEOUTS = {
    "honest": 12,
    "upstream": 14,
}  # the day each leaves to run out: the nightly job closes it at 03:00
SECRET_DETAIL = "audit-detail-secret-7d1"


def day_of(i: int) -> date:
    return FIRST_DAY + timedelta(days=i)


def madrid(day: date, hour: int, minute: int = 0, seconds: float = 0.0) -> datetime:
    return datetime.combine(day, time(hour, minute), MADRID) + timedelta(seconds=seconds)


def hard(i: int) -> bool:
    return i % 2 == 1


def difficulty(i: int) -> int:
    return 4 if hard(i) else 2


def key_pos(i: int) -> int:
    """The position of the upstream (FS-Quiz) answer on day i."""
    return i % 4


def effective_pos(i: int) -> int:
    """What the app grades against on day i: the reviewer's correction where there is one."""
    return (i + 2) % 4 if i in UP_DAYS else key_pos(i)


def true_pos(i: int) -> int:
    """The really right option: the stored key is wrong on SUSPECT only."""
    return (key_pos(i) + 1) % 4 if i == SUSPECT else effective_pos(i)


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda k: xs[k])
    out = [0.0] * len(xs)
    for rank_, k in enumerate(order):
        out[k] = float(rank_)
    return out


def _spearman(xs: list[float], ys: list[float]) -> float:
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    return float(cov / (sum((a - mx) ** 2 for a in rx) ** 0.5 * sum((b - my) ** 2 for b in ry) ** 0.5))


_lengths = [60 + 5 * k for k in range(DAYS)]
random.Random(5).shuffle(_lengths)
TEXT_LEN = [length + 4 * OPTION_CHARS for length in _lengths]  # len(text) + the four option texts


def _unrelated_to_length(start: int) -> list[float]:
    """A jitter in [0, 1] per day with (almost) no rank correlation with the text length."""
    for seed in range(start, start + 20000):
        order = list(range(DAYS))
        random.Random(seed).shuffle(order)
        if abs(_spearman([float(x) for x in TEXT_LEN], [float(x) for x in order])) < 0.03:
            return [x / (DAYS - 1) for x in order]
    raise AssertionError("no jitter found")


JITTER = _unrelated_to_length(100)
JITTER_FAST = _unrelated_to_length(900)


def human_seconds(i: int, base: float, slope: float) -> float:
    """Reading takes longer on a longer text, and a person's pace wobbles: wide, and tracking the length."""
    return base + slope * TEXT_LEN[i] + 4.0 * ((i * 7 + 3) % 5)


# profile -> (name, email prefix, vertical, position)
CLASSIC_PROFILES: dict[str, tuple[str, str, str, str]] = {
    "leader": ("Leader Lou", "lou", "Electronics", "member"),
    "follower": ("Follower Fay", "fay", "Electronics", "member"),
    "simultaneous": ("Simul Sam", "sam", "Electronics", "member"),
    "relayer": ("Relay Rae", "rae", "Electronics", "member"),
    "relayer_late": ("Relay Rex", "rex", "Electronics", "member"),
    "strong_honest": ("Strong Sue", "sue", "Electronics", "member"),
    "practised": ("Practised Pat", "pat", "Electronics", "member"),
    "honest": ("Honest Hal", "hal", "Electronics", "member"),
    "metronome": ("Metro Nome", "nome", "Electronics", "member"),
    "prodigy": ("Prodigy Pru", "pru", "Electronics", "member"),
    "looker": ("Looker Lia", "lia", "Electronics", "member"),
    "upstream": ("Upstream Uma", "uma", "Electronics", "member"),
    "mech": ("Mech Max", "max", "Mechanical", "member"),
    "mech2": ("Mech Mia", "mia", "Mechanical", "member"),
    "mech3": ("Mech Moe", "moe", "Mechanical", "member"),
    "drive1": ("Drive Dan", "dan", "Driverless", "mingo"),
    "drive2": ("Drive Dee", "dee", "Driverless", "mingo"),
    "alumna": ("Alma Alumna", "alma", "Electronics", "member"),
}

SIGNAL_PROFILES: dict[str, tuple[str, str, str, str]] = {
    "canary_follower": ("Canary Cass", "cass", "Electronics", "member"),
    "late_starter": ("Late Lena", "lena", "Electronics", "member"),
    "translator": ("Translate Tia", "tia", "Electronics", "member"),
    "tab_switcher": ("Tabs Tom", "tom", "Electronics", "member"),
    "poisoner": ("Poison Pia", "pia", "Electronics", "member"),
    "forger": ("Forger Omar", "omar", "Electronics", "member"),
    "performer": ("Perform Pete", "pete", "Electronics", "member"),
}
PROFILES = CLASSIC_PROFILES | SIGNAL_PROFILES
CLASSIC = list(CLASSIC_PROFILES)
SIGNAL_PLAYERS = list(SIGNAL_PROFILES)
IDS = {name: 900001 + k for k, name in enumerate(PROFILES)}
PLAYERS = list(PROFILES)  # everyone with plays, the alumna too
ACTIVE = [name for name in PLAYERS if name != "alumna"]
ALUMNA_LAST_DAY = 33  # 5 October: she left on the 6th
FAMILIES = {  # who the report must flag, and for which families
    "leader": {"provenance"},
    "follower": {"timing", "provenance"},
    "simultaneous": {"timing", "provenance"},
    "relayer": {"provenance"},
    "relayer_late": {"provenance"},
    "upstream": {"provenance"},
    "looker": {"performance"},
    "canary_follower": {"provenance"},  # the canary alone: one family, so not a conversation
    "late_starter": {"provenance"},
    "performer": {"performance"},  # maxed context adds no family
}
FLAGGED = set(FAMILIES)
CONVERSATION = {name for name, families in FAMILIES.items() if len(families) >= 2}
COUNT = {
    v: sum(1 for n in PLAYERS if PROFILES[n][2] == v) for v in ("Electronics", "Mechanical", "Driverless")
}
QUIET = ("translator", "tab_switcher", "poisoner", "forger")  # context or noise, never a flag

L_WRONG = {i for i in range(DAYS) if i % 5 in (0, 2)} | {SUSPECT}
SH_WRONG = {7, 19, 23, 35}
SH_UPSTREAM_PICK = 23
PRACTISED = {i for i in range(DAYS) if i % 10 not in (1, 4, 5, 8)}
PRACTICE = {"practised": PRACTISED, "upstream": {0, 2, 3, 6, 10, 11}}  # who practised which days' questions
WRONG = {
    "honest": {6, 30, 3, 13, 25, 33, 39},
    "upstream": {14, 36, 1, 9, 17, 29, 37},
    "mech": {8} | {i for i in range(DAYS) if hard(i) and i not in (11, 15, 17, 29, 31, 37)},
    "mech2": {10, 38, 1, 9, 17, 27, 37},
    "mech3": {2, 26, 11, 15, 21, 29, 31},
    "drive1": {16, 34, 7, 19, 23, 33, 39},
    "drive2": {4, 22, 1, 13, 29, 35, 37},
    "practised": {1, 14, 38, 25},
    "metronome": {10, 38, 15, 3, 27, 33, 35},
    "prodigy": set(),
    "looker": {i for i in range(DAYS) if not hard(i) and i % 8 != 0},
}
WRONG["performer"] = WRONG["looker"]
START = {  # Madrid time of day each profile opens its daily
    "leader": (10, 0),
    "follower": (10, 5),
    "simultaneous": (10, 0),
    "alumna": (10, 7),
    "relayer": (10, 10),
    "relayer_late": (12, 5),
    "looker": (5, 0),
    "honest": (8, 0),
    "upstream": (14, 30),
    "practised": (16, 0),
    "mech": (12, 0),
    "mech2": (12, 45),
    "mech3": (13, 30),
    "drive1": (17, 0),
    "drive2": (17, 45),
    "metronome": (18, 30),
    "prodigy": (20, 0),
}
RELAYERS = ("relayer", "relayer_late")


def relayed(i: int) -> bool:
    """The days the relayers are handed the key: the leader was wrong and saw it (on the suspect question the key
    is wrong too, and nobody can pass on a right answer)."""
    return i in L_WRONG and i != SUSPECT


def strong_honest_start(i: int) -> tuple[int, int]:
    return (10, 20) if i % 2 == 0 else (19, 0)


def leader_wrong_pos(i: int) -> int:
    avoid = {effective_pos(i)} | ({key_pos(i)} if i in UP_DAYS else set())
    return _wrong(i, avoid, 0)


def _wrong(i: int, avoid: set[int], salt: int) -> int:
    candidates = [p for p in range(4) if p not in avoid]
    return candidates[(i + salt) % len(candidates)]


def leader_pos(i: int) -> int:
    if i == SUSPECT:
        return true_pos(i)
    return leader_wrong_pos(i) if i in L_WRONG else effective_pos(i)


def independent_pos(profile: str, i: int, right: bool, salt: int) -> int:
    """An honest player's option: the right one, or any wrong one (the leader's too) but, on a corrected question,
    the upstream one."""
    if i == SUSPECT:
        return true_pos(i)
    if right:
        return effective_pos(i)
    avoid = {effective_pos(i)}
    if i in UP_DAYS:
        avoid.add(key_pos(i))
    return _wrong(i * (salt + 1), avoid, salt)


def pick(profile: str, i: int) -> int:
    """Position of the option `profile` chooses on day i."""
    if profile in SIGNAL_PROFILES:
        return signal_plan().moves[(profile, i)].pos
    if profile in ("leader", "follower", "simultaneous", "alumna"):
        return leader_pos(i)
    salt = list(PROFILES).index(profile)
    if profile in RELAYERS:
        return effective_pos(i) if relayed(i) else independent_pos(profile, i, i % 3 == 0, salt)
    if profile == "strong_honest":
        if i == SH_UPSTREAM_PICK:
            return key_pos(i)
        return independent_pos(profile, i, i not in SH_WRONG, salt)
    if profile == "upstream" and i in UP_DAYS:
        return key_pos(i)
    return independent_pos(profile, i, i not in WRONG[profile], salt)


def start_and_seconds(profile: str, i: int) -> tuple[datetime, float]:
    day = day_of(i)
    if profile in SIGNAL_PROFILES:
        if profile == "canary_follower" and i == BOUNDARY_DAY:
            return madrid(day, 23, 59), 120.0
        base, slope = SIGNAL_PACE[profile]
        return madrid(day, *SIGNAL_START[profile]), human_seconds(i, base, slope)
    hour, minute = strong_honest_start(i) if profile == "strong_honest" else START[profile]
    start = madrid(day, hour, minute)
    if profile == "follower":
        return start, 3.0 + 2.0 * JITTER_FAST[i]
    if profile == "simultaneous":
        return start, 140.0 + 20.0 * JITTER[i]
    if profile == "practised" and i in PRACTISED:
        return start, 6.0 + 0.1 * (i % 5)
    if (
        profile == "metronome"
    ):  # the same rate of reading whatever the text: narrow, but it follows the length
        return start, 60.0 + 0.1 * TEXT_LEN[i]
    base, slope = {"leader": (10.0, 0.25), "strong_honest": (15.0, 0.3)}.get(profile, (20.0, 0.4))
    return start, human_seconds(i, base, slope)


# --- the signals world --------------------------------------------------------------------------------------------

RULES_FROM = day_of(
    2
)  # 2026-09-04: the first day whose attempts carry signals, and where per-person windows start
RULES_INDEX = 2
BOUNDARY_DAY = (
    RULES_INDEX - 1
)  # canary_follower answers this day's question across the midnight that starts RULES_FROM
OPTIONS = 4

# The report's test settings. The world is calibrated to them: they are not the production ones (which are not in
# the repository) and the report must never print any of them.
CANARY_ENV = {
    "IFS_INTEGRITY_CANARY_ALPHA": "0.05",
    "IFS_INTEGRITY_CANARY_BETA": "0.2",
    "IFS_INTEGRITY_CANARY_FOLLOW": "0.5",
    "IFS_INTEGRITY_CANARY_CONTROL_ALPHA": "0.1",
    "IFS_INTEGRITY_CANARY_NUDGE": "0.1",
    "IFS_INTEGRITY_CANARY_M": "20",
    "IFS_INTEGRITY_AWAY_UNDECLARED_S": "20",
}


@dataclass(frozen=True)
class Params:
    alpha: float = 0.05
    beta: float = 0.2
    follow: float = 0.5
    control_alpha: float = 0.1
    nudge: float = 0.1
    m: int = 20
    away_s: float = 20.0


PARAMS = Params()
PARAMS_MIN_GROUP = 3  # IntegritySettings.min_group, whose default the tests keep

SIGNAL_START = {  # at least 45 minutes from anyone else's start
    "canary_follower": (1, 0),
    "late_starter": (2, 15),
    "translator": (3, 30),
    "tab_switcher": (6, 30),
    "performer": (9, 0),
    "poisoner": (21, 30),
    "forger": (22, 30),
}
SIGNAL_PACE = {  # base seconds and seconds per character: the attempt must outlast its away time
    "canary_follower": (40.0, 0.5),
    "late_starter": (150.0, 0.5),
    "translator": (420.0, 0.4),
    "tab_switcher": (400.0, 0.3),
    "performer": (380.0, 0.3),
    "poisoner": (20.0, 0.4),
    "forger": (30.0, 0.4),
}
POISON_DAYS = 16
COPY_MISSES = 4  # the poisoner's copy-arm trials: honest wrong answers after a long copy


class Away(TypedDict, total=False):
    away_u: int | None
    away_d: int | None


@dataclass(frozen=True)
class Move:
    """What one of the signal members does on one day, and the signals the attempt carries. `copies` None with
    `resumes` 0 is a page that sent no totals; both None is an attempt that carries nothing (before the rule
    date, or purged)."""

    pos: int
    copies: int | None = 0
    resumes: int | None = 0
    away_u: int | None = None
    away_d: int | None = None
    hint: bool = False
    purged: bool = False  # every signal column NULL, the decoy too
    collected: bool = True


@dataclass(frozen=True)
class Plan:
    decoy: dict[tuple[str, int], int]  # position of the decoy, per player and day, from RULES_FROM on
    moves: dict[tuple[str, int], Move]  # the signal members, every day
    changed: dict[str, int]  # day index whose question changed: after (unreviewed), acked, before


def classic_away(name: str, i: int, seconds: float) -> int:
    """The undeclared time away of one of the eighteen: 30 s on one day in four, over the test threshold, and never
    on an attempt too short to hold it."""
    if seconds < 60 or (i + list(PROFILES).index(name)) % 4:
        return 0
    return 30


def _wrong_days(k: int, share: float) -> set[int]:
    rng = random.Random(1000 + k)
    return {i for i in range(DAYS) if rng.random() < share}


def _binomial_tail(n: int, k: int, upper: bool, p: float = 1 / 3) -> float:
    """P(X >= k) (upper) or P(X <= k) for X ~ Binomial(n, p)."""
    ks = range(k, n + 1) if upper else range(0, min(k, n) + 1)
    return sum(math.comb(n, j) * p**j * (1 - p) ** (n - j) for j in ks)


def _other_wrong(i: int, decoy: int) -> int:
    """A wrong option that is neither the decoy nor the upstream answer of a corrected question."""
    avoid = {effective_pos(i), decoy} | ({key_pos(i)} if i in UP_DAYS else set())
    return _wrong(i, avoid, 1)


def _draw(seed: int) -> Plan | None:
    rng = random.Random(seed)
    decoy = {(n, i): rng.randrange(OPTIONS) for n in PLAYERS for i in range(RULES_INDEX, DAYS)}
    days = [i for i in range(RULES_INDEX, DAYS) if i != SUSPECT]  # nobody can follow the note to a wrong key

    def d(n: str, i: int) -> int:
        return decoy[(n, i)]

    def key_decoy(n: str) -> list[int]:
        return [i for i in days if d(n, i) == effective_pos(i)]

    def off_decoy(n: str) -> list[int]:
        return [i for i in days if d(n, i) != effective_pos(i)]

    moves: dict[tuple[str, int], Move] = {}

    def honest(n: str, k: int, i: int, wrong: set[int], away: Away | None = None, resumes: int = 0) -> Move:
        pos = independent_pos(n, i, i not in wrong, 100 + k)
        if i < RULES_INDEX:
            return Move(pos, copies=None, resumes=None, collected=False)
        return Move(pos, resumes=resumes, **(away or Away()))

    n = "canary_follower"
    if len(key_decoy(n)) < 2 or len(off_decoy(n)) < 18:
        return None
    follow_key = set(rng.sample(key_decoy(n), 2))
    follow_off = sorted(rng.sample(off_decoy(n), 18))
    hint_day = follow_off[6]
    changed = {"after": follow_off[2], "acked": follow_off[9], "before": follow_off[13]}
    for i in range(DAYS):
        away = Away(away_u=60 if i % 7 == 3 else 0, away_d=20 if i % 11 == 4 else 0)
        if i == BOUNDARY_DAY:
            pos = (effective_pos(i) + 1) % OPTIONS
            decoy[(n, i)] = pos
            moves[(n, i)] = Move(pos, copies=1, resumes=0, away_u=0, away_d=0)
        elif i in follow_key:
            moves[(n, i)] = Move(effective_pos(i), copies=1 + i % 2, **away)
        elif i in follow_off:
            moves[(n, i)] = Move(d(n, i), copies=1 + i % 2, hint=i == hint_day, **away)
        else:
            moves[(n, i)] = honest(n, 0, i, _wrong_days(0, 0.4), away)

    n = "late_starter"
    late_off = off_decoy(n)
    if len(late_off) < 19:
        return None
    misses, start, purged = set(late_off[:3]), late_off[3], late_off[5]
    for i in range(DAYS):
        away = Away(away_u=130 + (i % 4) * 15 if i % 3 == 0 else 0, away_d=25 if i % 5 == 1 else 0)
        if i >= RULES_INDEX and i in misses:
            moves[(n, i)] = Move(_other_wrong(i, d(n, i)), copies=1, **away)
        elif i >= start and i != SUSPECT:
            moves[(n, i)] = Move(d(n, i), copies=1, purged=i == purged, **away)
        else:
            moves[(n, i)] = honest(n, 1, i, _wrong_days(1, 0.4), away)

    n = "translator"
    wrong = _wrong_days(2, 0.45)
    wrong_off = [i for i in off_decoy(n) if i in wrong]
    rights = [i for i in days if i not in wrong]
    if len(wrong_off) < 8 or len(rights) < 3:
        return None
    copy_wrong, copy_right = wrong_off[:8], set(rights[:3])
    for i in range(DAYS):
        away = Away(
            away_u=200 + (i * 37) % 201 if i % 5 else 0, away_d=30 + (i % 3) * 20 if i % 4 == 0 else 0
        )
        if i in copy_wrong:  # two hits of eight: under the chance of one in three
            pos = d(n, i) if copy_wrong.index(i) in (0, 2) else _other_wrong(i, d(n, i))
            moves[(n, i)] = Move(pos, copies=1 + i % 3, **away)
        elif i in copy_right:
            moves[(n, i)] = Move(effective_pos(i), copies=1 + i % 2, **away)
        else:
            moves[(n, i)] = honest(n, 2, i, wrong, away)

    n = "tab_switcher"
    wrong = _wrong_days(3, 0.4)
    for i in range(DAYS):
        moves[(n, i)] = honest(n, 3, i, wrong, Away(away_u=300 + (i * 53) % 301), resumes=2)

    n = "poisoner"
    wrong = _wrong_days(4, 0.3)
    offs = off_decoy(n)
    if len(offs) < POISON_DAYS + COPY_MISSES:
        return None
    picked = rng.sample(offs, POISON_DAYS + COPY_MISSES)
    poison, copy_miss = sorted(picked[:POISON_DAYS]), set(picked[POISON_DAYS:])
    reload = poison[8]
    for i in range(DAYS):
        if i in poison:
            moves[(n, i)] = Move(d(n, i), copies=0, resumes=1 if i == reload else 0)
        elif i in copy_miss:
            moves[(n, i)] = Move(_other_wrong(i, d(n, i)), copies=1)
        else:
            moves[(n, i)] = honest(n, 4, i, wrong)

    n = "forger"
    wrong = _wrong_days(5, 0.3)
    offs = off_decoy(n)
    if len(offs) < 20:
        return None
    follow = sorted(rng.sample(offs, 20))
    forged = set(follow[::4])
    for i in range(DAYS):
        if i in forged:  # says it copied nothing
            moves[(n, i)] = Move(d(n, i), copies=0, resumes=0, away_u=0, away_d=0)
        elif i in follow:  # sends no totals at all
            moves[(n, i)] = Move(d(n, i), copies=None, resumes=0)
        else:
            moves[(n, i)] = honest(n, 5, i, wrong)

    n = "performer"
    for i in range(DAYS):
        away = Away(away_u=300 + (i * 17) % 60, away_d=60 + i % 20)
        moves[(n, i)] = honest(n, 6, i, WRONG["looker"], away, resumes=1)
    return Plan(decoy, moves, changed)


@dataclass(frozen=True)
class Fact:
    """One attempt from RULES_FROM on that carries a decoy: what the report must make of it."""

    player: str
    day: int
    pos: int | None  # position chosen, None for a daily left to run out
    decoy: int
    arm: str | None  # copy | placebo | unreported | None (a reload without a copy)
    trial: bool
    hit: bool


def facts(plan: Plan | None = None) -> list[Fact]:
    plan = plan or signal_plan()
    voided = {plan.changed["after"], plan.changed["acked"]}
    out = []
    for n in PLAYERS:
        last = ALUMNA_LAST_DAY if n == "alumna" else DAYS - 1
        for i in range(RULES_INDEX, last + 1):
            move = plan.moves.get((n, i))
            pos: int | None
            copies: int | None
            resumes: int | None
            if move is None:
                pos = None if TIMEOUTS.get(n) == i else pick(n, i)
                copies, resumes, hint = 0, 0, False
            elif move.purged or not move.collected:
                continue
            else:
                pos, copies, resumes, hint = move.pos, move.copies, move.resumes, move.hint
            arm: str | None
            if copies is None:
                arm = "unreported"
            elif copies >= 1:
                arm = "copy"
            else:
                arm = "placebo" if resumes == 0 else None
            dec = plan.decoy[(n, i)]
            trial = (
                pos is not None
                and not hint
                and pos != effective_pos(i)
                and dec != effective_pos(i)
                and i not in voided
            )
            out.append(Fact(n, i, pos, dec, arm, trial, trial and pos == dec))
    return out


@dataclass(frozen=True)
class Ref:
    """What the report must say about one player, by an implementation that shares nothing with it."""

    arms: dict[str, tuple[int, int]]  # arm -> (trials, hits)
    decision: str | None  # the copy-arm walk: reject | no sign | continue; None without copy-arm trials
    decided_at: int | None
    listed: bool  # the arms without a reported copy (placebo, unreported, reloaded) cross the same boundary


def _walk(hits: list[bool], params: Params = PARAMS) -> tuple[str, int | None]:
    p0 = 1 / 3
    p0n, p1 = p0 + params.nudge * (1 - p0), p0 + params.follow * (1 - p0)
    up, down = math.log(p1 / p0n), math.log((1 - p1) / (1 - p0n))
    bound = math.log(params.m / params.alpha)
    llr, crossed = 0.0, None
    for k, hit in enumerate(hits, 1):
        llr += up if hit else down
        if crossed is None and llr >= bound:
            crossed = k
    if crossed is not None:
        return "reject", crossed
    if llr <= math.log(params.beta / (1 - params.alpha)):
        return "no sign", None
    return "continue", None


def reference(plan: Plan | None = None, params: Params = PARAMS) -> dict[str, Ref]:
    by: dict[str, list[Fact]] = {}
    for f in facts(plan):
        if f.trial:
            by.setdefault(f.player, []).append(f)
    out = {}
    for n in PLAYERS:
        rows = sorted(by.get(n, []), key=lambda f: f.day)
        arms = {
            a: (
                sum((f.arm or "neither") == a for f in rows),
                sum((f.arm or "neither") == a and f.hit for f in rows),
            )
            for a in ("copy", "placebo", "unreported", "neither")
        }
        copy = [f.hit for f in rows if f.arm == "copy"]
        decision, at = _walk(copy, params) if copy else (None, None)
        rest = [f.hit for f in rows if f.arm != "copy"]
        listed = bool(rest) and _walk(rest, params)[0] == "reject"
        out[n] = Ref(arms, decision, at, listed)
    return out


def placebo_pool(plan: Plan | None = None, leave_out: tuple[str, ...] = ()) -> tuple[int, int, int]:
    """(people, trials, hits) of the placebo arm, without `leave_out`."""
    rows = [f for f in facts(plan) if f.trial and f.arm == "placebo" and f.player not in leave_out]
    return len({f.player for f in rows}), len(rows), sum(f.hit for f in rows)


def placebo_power(plan: Plan | None = None, params: Params = PARAMS) -> float:
    """Exact power of the pooled placebo's upper tail, at alpha / 2 per tail, against a leak of `follow`."""
    _, n, _ = placebo_pool(plan)
    per_tail = params.control_alpha / 2
    crit = next((k for k in range(n + 1) if _binomial_tail(n, k, upper=True) <= per_tail), n + 1)
    alt = 1 / 3 + params.follow * 2 / 3
    return _binomial_tail(n, crit, upper=True, p=alt) if crit <= n else 0.0


SMALL_WORLD = ("canary_follower", "late_starter", "translator", "strong_honest")


def _draw_p(plan: Plan, only: tuple[str, ...] | None = None, *, upper: bool | None = None) -> float:
    """The smaller tail (or the `upper` / lower one) of the decoy falling on the key as often as chance says."""
    drawn = [
        f
        for f in facts(plan)
        if f.day not in (plan.changed["after"], plan.changed["acked"]) and (only is None or f.player in only)
    ]
    in_key = sum(f.decoy == effective_pos(f.day) for f in drawn)
    tails = [_binomial_tail(len(drawn), in_key, upper=u, p=1 / OPTIONS) for u in (True, False)]
    return min(tails) if upper is None else tails[0 if upper else 1]


def _acceptable(plan: Plan) -> bool:
    """The seed keeps the world as designed: the follower and the late starter are rejected, the translator is
    not, the poisoner and the forger cross the listing's boundary and are not rejected, every honest player's
    own placebo is calm (the poisoner's and the forger's are off), so is the pool without the poisoner, and the
    draw check sees a uniform decoy with enough power left over for the placebo."""
    ref = reference(plan)
    if ref["canary_follower"].decision != "reject" or ref["late_starter"].decision != "reject":
        return False
    if ref["translator"].decision != "no sign":
        return False
    if ref["poisoner"].decision is None or not ref["poisoner"].listed or ref["forger"].decision is not None:
        return False
    if not ref["forger"].listed:
        return False
    for n, r in ref.items():
        if n not in ("canary_follower", "late_starter") and r.decision == "reject":
            return False
        if n not in ("poisoner", "forger") and r.listed:
            return False
        trials, hits = r.arms["placebo"]
        own = _binomial_tail(trials, hits, upper=True)
        if (own < 0.05) != (n in ("poisoner", "forger")) or (n not in ("poisoner", "forger") and own < 0.25):
            return False
    people, pooled, hits = placebo_pool(plan, ("poisoner",))
    upper, lower = _binomial_tail(pooled, hits, upper=True), _binomial_tail(pooled, hits, upper=False)
    if _draw_p(plan, SMALL_WORLD) < 0.2:  # the world cut down to these must still pass its draw check
        return False
    key_upper = _draw_p(plan, upper=True)
    key_lower = _draw_p(plan, upper=False)
    for who in SIGNAL_PLAYERS:  # no accidental match with a corrected question's old key
        if sum(plan.moves[(who, i)].pos == key_pos(i) for i in UP_DAYS) > 1:
            return False
    return people >= 3 and min(upper, lower, key_upper, key_lower) >= 0.2 and placebo_power(plan) >= 0.9


@functools.cache
def signal_plan() -> Plan:
    for seed in itertools.count(1):
        plan = _draw(seed)
        if plan is not None and _acceptable(plan):
            return plan
        assert seed < 5000, "no seed keeps the signals world as designed"
    raise AssertionError  # pragma: no cover


@dataclass
class World:
    ids: dict[str, int]
    names: dict[str, str]
    emails: dict[str, str]
    question_ids: list[int]
    suspect: int
    upstream: list[int]
    texts: list[str]  # question and option texts: no output may ever carry one
    plays: dict[str, int]  # answered plays per profile
    options: list[list[int]]  # per day, the option ids by position
    changed: dict[str, int]  # the question ids whose wording changed upstream, by when (after, acked, before)

    def secrets(self) -> list[str]:
        return [*self.texts, SECRET_DETAIL]


def build(db: Session) -> World:
    """Write the world to the database (committed): the eighteen and the seven signal members, every attempt from
    RULES_FROM on carrying its totals and a decoy as the services write them. Needs an empty, migrated database."""
    plan = signal_plan()
    texts: list[str] = []
    qids: list[int] = []
    options: list[list[int]] = []
    for i in range(DAYS):
        label = f"Planted question {i:02d} "
        body = label + "x" * (_lengths[i] - len(label))
        q = Question(
            type="single-choice",
            text=body,
            time_s=600,
            area="elec",
            topic="ev" if i % 2 == 0 else "sensors",
            difficulty=difficulty(i),
            answer_kind="choice-one",
            graded=True,
            playable=True,
            labels_reviewed=i % 2 == 0,
            source_hash="planted",
        )
        db.add(q)
        db.flush()
        ids = []
        for p in range(4):
            text = f"zq{i:02d}-o{p}"
            assert len(text) == OPTION_CHARS
            o = AnswerOption(question_id=q.id, position=p, text=text)
            db.add(o)
            db.flush()
            ids.append(o.id)
            texts.append(text)
        key = {"kind": "choice", "mode": "one", "options": [ids[key_pos(i)]]}
        override = (
            {"kind": "choice", "mode": "one", "options": [ids[effective_pos(i)]]} if i in UP_DAYS else None
        )
        db.add(AnswerKey(question_id=q.id, key=key, display=f"ANSWER-{i:02d}", override=override))
        db.add(DailyQuestion(day=day_of(i), area="elec", question_id=q.id, drawn_at=madrid(day_of(i), 0, 1)))
        texts += [body, f"ANSWER-{i:02d}"]
        qids.append(q.id)
        options.append(ids)
    for k in range(6):  # rules and mechanical questions nobody plays: the labels table has more than one area
        db.add(
            Question(
                type="single-choice",
                text=f"Rules question {k}",
                area="rules",
                topic="rules",
                answer_kind="choice-one",
                graded=True,
                labels_reviewed=k < 2,
                source_hash="planted",
            )
        )
    for k in range(4):
        db.add(
            Question(
                type="single-choice",
                text=f"Mechanical question {k}",
                area="mech",
                topic="chassis",
                answer_kind="choice-one",
                graded=True,
                labels_reviewed=k == 0,
                source_hash="planted",
            )
        )
    db.flush()

    up_qids = [qids[i] for i in UP_DAYS]
    corrected = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
    for n, qid in enumerate(up_qids):
        for at in (datetime(2026, 8, 20, 6, 0, tzinfo=UTC), corrected + timedelta(minutes=n)):
            db.add(
                AuditLog(
                    action="question.answer",
                    target=f"question:{qid}",
                    at=at,
                    details={"shown": SECRET_DETAIL},
                )
            )
    db.add(
        AuditLog(
            action="question.answer_cleared",
            target=f"question:{qids[0]}",
            at=corrected,
            details={"x": SECRET_DETAIL},
        )
    )
    db.add(
        AuditLog(
            action="user.update",
            target=f"user:{IDS['honest']}",
            at=corrected,
            details={"position": ["mingo", "member"]},
        )
    )

    names = {name: display for name, (display, *_) in PROFILES.items()}
    emails = {name: f"{prefix}@plant.test" for name, (_, prefix, *__) in PROFILES.items()}
    plays: dict[str, int] = {}
    members: list[User] = []
    attempts: list[Attempt] = []
    for name in PLAYERS:
        display, prefix, vertical, position = PROFILES[name]
        rows = _attempts(name, qids, options, plan)
        points = rank.placement(position)
        best = rank.division_of(points)
        miss = 0
        for entry in rows:
            run = not entry.repeat
            lp = rank.lp_award(
                entry.correct,
                points,
                difficulty(entry.day_index),
                "daily",
                area="elec",
                answer_kind="choice-one",
                options=4,
                right_options=1,
                hint=entry.hint,
                repeat=entry.repeat,
                late=entry.late,
                miss_streak=miss if run else 0,
            )
            after = max(0.0, round(points + lp.amount, 2))
            assert after > 0, f"{name} hit the floor: the fixture would not replay exactly"
            entry.attempt.lp = round(after - points, 2)
            points = after
            best = max(best, rank.division_of(points))
            if run:
                miss = rank.next_miss_streak(miss, entry.correct, False, entry.late)
            attempts.append(entry.attempt)
        plays[name] = sum(1 for e in rows if not e.late)
        members.append(
            User(
                id=IDS[name],
                email=emails[name],
                password_hash="x",
                display_name=display,
                vertical=vertical,
                position=position,
                status="alumni" if name == "alumna" else "active",
                left_at=madrid(day_of(ALUMNA_LAST_DAY + 1), 9) if name == "alumna" else None,
                rank_points=points,
                rank_season=SEASON,
                rank_best=best,
            )
        )
    db.add_all(members)
    db.flush()
    db.add_all(attempts)
    for who, days in PRACTICE.items():  # on 1 September, before any daily: right, so the dailies are repeats
        for n, i in enumerate(sorted(days)):
            chosen = options[i][pick(who, i)]
            db.add(
                Attempt(
                    user_id=IDS[who],
                    question_id=qids[i],
                    mode="practice",
                    answer={"options": [chosen], "value": None, "unsure": False},
                    correct=pick(who, i) == effective_pos(i),
                    created_at=madrid(date(2026, 9, 1), 9, n),
                    area="elec",
                )
            )
    _uncounted_mock(db, qids, options)
    db.commit()
    changed = _change_questions(db, qids, plan)
    return World(IDS, names, emails, qids, qids[SUSPECT], up_qids, texts, plays, options, changed)


MOCK_QUIZ = 9900
MOCK_DAY = 30  # the uncounted run is of this day's question, on 4 October, two days after its daily


def _uncounted_mock(db: Session, qids: list[int], options: list[list[int]]) -> None:
    """A second run of a quiz in the season: it earns no LP, and the server writes no signal and no decoy on it
    (`resumes` is null, which is what marks a row that carries signals)."""
    when = madrid(date(2026, 10, 4), 15)
    db.add(Quiz(id=MOCK_QUIZ, year=SEASON, vehicle_class="cv", held_on=date(2026, 3, 1), status="complete"))
    db.flush()
    db.add(QuizQuestion(quiz_id=MOCK_QUIZ, question_id=qids[MOCK_DAY], position=0))
    run = MockSession(
        user_id=IDS["translator"],
        quiz_id=MOCK_QUIZ,
        season=SEASON,
        counted=False,
        position=1,
        started_at=when,
        finished_at=when + timedelta(minutes=1),
    )
    db.add(run)
    db.flush()
    db.add(
        Attempt(
            user_id=IDS["translator"],
            question_id=qids[MOCK_DAY],
            mode="mock",
            answer={"options": [options[MOCK_DAY][effective_pos(MOCK_DAY)]], "value": None, "unsure": False},
            correct=True,
            created_at=when,
            area="elec",
            deadline_at=when + timedelta(seconds=600),
            submitted_at=when + timedelta(seconds=30),
            late=False,
            passed=False,
            session_id=run.id,
            lp=0,
        )
    )


def _change_questions(db: Session, qids: list[int], plan: Plan) -> dict[str, int]:
    """Three questions whose wording the mirror found changed upstream, as it flags them (`key_changed_at`,
    `upstream_change`): one after the day's attempts and still waiting for a reviewer, one after them and
    acknowledged since (a reviewer's `review.update` clears the flag and leaves only its audit row), one before
    them. The first two make the options the decoy was drawn over uncertain; the third changes nothing."""
    after, acked, before = (qids[plan.changed[k]] for k in ("after", "acked", "before"))
    day = {k: day_of(plan.changed[k]) for k in plan.changed}
    for qid, at in (
        (after, madrid(day["after"] + timedelta(days=1), 8)),
        (acked, madrid(day["acked"] + timedelta(days=1), 8)),
        (before, madrid(day["before"] - timedelta(days=1), 8)),
    ):
        q = db.get(Question, qid)
        assert q is not None
        q.upstream_change, q.key_changed_at = "wording", at
    db.commit()
    reviewer = db.get(User, IDS["honest"])
    assert reviewer is not None
    review.update(
        db, reviewer, acked, {"acknowledge_change": True}, madrid(day["acked"] + timedelta(days=2), 9)
    )
    db.execute(  # the audit row is stamped by the clock of the day it was written, not the test's
        update(AuditLog)
        .where(AuditLog.action == "question.update", AuditLog.target == f"question:{acked}")
        .values(at=madrid(day["acked"] + timedelta(days=2), 9))
    )
    db.commit()
    return {"after": after, "acked": acked, "before": before}


@dataclass
class _Entry:
    day_index: int
    attempt: Attempt
    correct: bool
    repeat: bool
    late: bool
    hint: bool = False


def _columns(name: str, i: int, seconds: float, late: bool, options: list[int], plan: Plan) -> dict[str, Any]:
    """The signal columns of one daily attempt, as the services leave them."""
    if name in SIGNAL_PROFILES:
        move = plan.moves[(name, i)]
        if not move.collected or move.purged:
            return {}
        return {
            "decoy_option_id": options[plan.decoy[(name, i)]],
            "resumes": move.resumes,
            "long_copies": move.copies,
            "away_undeclared_s": move.away_u,
            "away_declared_s": move.away_d,
        }
    if i < RULES_INDEX:
        return {}
    cols: dict[str, Any] = {"decoy_option_id": options[plan.decoy[(name, i)]], "resumes": 0}
    if not late:  # a daily the nightly job closed never had its page send anything
        cols |= {
            "long_copies": 0,
            "away_undeclared_s": classic_away(name, i, seconds),
            "away_declared_s": 0,
        }
    return cols


def _attempts(name: str, qids: list[int], options: list[list[int]], plan: Plan) -> list[_Entry]:
    """The player's daily attempts in grading order (submit time), LP still to be filled in."""
    out: list[tuple[datetime, int, _Entry]] = []
    for i in range(ALUMNA_LAST_DAY + 1 if name == "alumna" else DAYS):
        start, seconds = start_and_seconds(name, i)
        late = TIMEOUTS.get(name) == i
        hint = name in SIGNAL_PROFILES and plan.moves[(name, i)].hint
        if late:  # left to run out: the nightly job closes it at 03:00 the next day
            correct, answer, when = False, {}, madrid(day_of(i + 1), 3)
        else:
            chosen = options[i][pick(name, i)]
            right = grading.grade(
                {"kind": "choice", "mode": "one", "options": [options[i][effective_pos(i)]]}, [chosen]
            )
            assert right is not None
            correct, answer, when = (
                right,
                {"options": [chosen], "value": None, "unsure": False},
                start + timedelta(seconds=seconds),
            )
        attempt = Attempt(
            user_id=IDS[name],
            question_id=qids[i],
            mode="daily",
            answer=answer,
            correct=correct,
            created_at=start,
            day=day_of(i),
            area="elec",
            deadline_at=start + timedelta(seconds=600),
            submitted_at=when,
            late=late,
            passed=False,
            hint_used=hint,
            **_columns(name, i, seconds, late, options[i], plan),
        )
        out.append((when, i, _Entry(i, attempt, correct, i in PRACTICE.get(name, ()), late, hint)))
    out.sort(key=lambda t: (t[0], t[1]))
    return [e for _, _, e in out]
