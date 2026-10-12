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
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ifs_tests.db.models import (
    AnswerKey,
    AnswerOption,
    Attempt,
    AuditLog,
    DailyQuestion,
    Question,
    User,
)
from ifs_tests.domain import grading, rank

MADRID = ZoneInfo("Europe/Madrid")
SEASON = 2026
FIRST_DAY = date(2026, 9, 2)
DAYS = 40
LAST_DAY = FIRST_DAY + timedelta(days=DAYS - 1)  # 2026-10-11
UNTIL = date(2026, 10, 12)  # the announcement date: excluded
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
PROFILES: dict[str, tuple[str, str, str, str]] = {
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
}
FLAGGED = set(FAMILIES)
CONVERSATION = {name for name, families in FAMILIES.items() if len(families) >= 2}
COUNT = {
    v: sum(1 for n in PLAYERS if PROFILES[n][2] == v) for v in ("Electronics", "Mechanical", "Driverless")
}

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

    def secrets(self) -> list[str]:
        return [*self.texts, SECRET_DETAIL]


def build(db: Session) -> World:
    """Write the world to the database (committed). Needs an empty, migrated one."""
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
        rows = _attempts(name, qids, options)
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
    db.commit()
    return World(IDS, names, emails, qids, qids[SUSPECT], up_qids, texts, plays)


@dataclass
class _Entry:
    day_index: int
    attempt: Attempt
    correct: bool
    repeat: bool
    late: bool


def _attempts(name: str, qids: list[int], options: list[list[int]]) -> list[_Entry]:
    """The player's daily attempts in grading order (submit time), LP still to be filled in."""
    out: list[tuple[datetime, int, _Entry]] = []
    for i in range(ALUMNA_LAST_DAY + 1 if name == "alumna" else DAYS):
        start, seconds = start_and_seconds(name, i)
        late = TIMEOUTS.get(name) == i
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
        )
        out.append((when, i, _Entry(i, attempt, correct, i in PRACTICE.get(name, ()), late)))
    out.sort(key=lambda t: (t[0], t[1]))
    return [e for _, _, e in out]
