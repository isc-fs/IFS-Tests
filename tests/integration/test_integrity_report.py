"""`ifs-tests integrity-report` and `integrity-reveal` against a database with planted, known behaviour
(tests/integration/planted.py): who it flags and who it must not, what it never prints, that it only reads, and
that the LP replay it stands on reproduces what the real services stored."""

from __future__ import annotations

import hashlib
import hmac
import itertools
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import psycopg
import pytest
from sqlalchemy import Engine, delete, event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from ifs_tests.db.models import (
    AnswerKey,
    AnswerOption,
    Attempt,
    DailyQuestion,
    MockSession,
    Question,
    Quiz,
    QuizQuestion,
    User,
)
from ifs_tests.db.session import read_only_engine
from ifs_tests.domain import integrity as rules
from ifs_tests.services import daily, hints, mock, practice, signals
from ifs_tests.services import integrity as service
from ifs_tests.settings import IntegritySettings

from ..api.helpers import close_run_outs
from . import planted
from .conftest import (
    INTEGRITY_SALT,
    INTEGRITY_THRESHOLDS,
    freeze_today,
    run,
    set_integrity_env,
)
from .planted import CANARY_ENV, World

pytestmark = pytest.mark.integration

SALT = INTEGRITY_SALT
BASE = ["integrity-report", "--until", "2026-10-12", "--salt-stdin"]


def pseudo(user_id: int, salt: str = SALT) -> str:
    return hmac.new(salt.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()[:8]


def report(*args: str, salt: str = SALT) -> str:
    return run(["integrity-report", "--until", "2026-10-12", *args, "--salt-stdin"], salt + "\n")


@pytest.fixture
def world(db: Session) -> World:
    built = planted.build(db)
    people_with_a_placebo, _, _ = planted.placebo_pool()
    assert people_with_a_placebo >= planted.PARAMS_MIN_GROUP, "the pooled placebo needs min_group people"
    assert planted.placebo_power() >= 1 - float(CANARY_ENV["IFS_INTEGRITY_CANARY_BETA"]), (
        "and enough trials to see a follower at the configured strength"
    )
    return built


def set_canary_env(
    monkeypatch: pytest.MonkeyPatch, rules_from: str | None = planted.RULES_FROM.isoformat()
) -> None:
    """The canary and context settings the planted world is calibrated to, and the app's rule date (the one
    switch). `rules_from` None leaves it unset."""
    for name, value in CANARY_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("IFS_RULES_1B_FROM", raising=False)
    if rules_from is not None:
        monkeypatch.setenv("IFS_RULES_1B_FROM", rules_from)


@pytest.fixture
def integrity_env(monkeypatch: pytest.MonkeyPatch, app_engine: Engine) -> Iterator[str]:
    """The report pointed at the test database as its superuser (the read-only transaction is what is tested here,
    the role in test_db_roles.py), with every setting it needs for any check. Yields the DSN."""
    dsn = app_engine.url.render_as_string(hide_password=False)
    set_integrity_env(monkeypatch, dsn)
    set_canary_env(monkeypatch)
    yield dsn


def integrity_settings(**over: str) -> IntegritySettings:
    """The report's settings as the environment gives them, and nothing from the machine's .env file."""
    cls: Any = IntegritySettings
    named = {k.removeprefix("IFS_INTEGRITY_").lower(): v for k, v in CANARY_ENV.items()} | over
    return cast(
        IntegritySettings,
        cls(_env_file=None, **{k.lower(): v for k, v in INTEGRITY_THRESHOLDS.items()}, **named),
    )


# --- reading the markdown the report prints ------------------------------------------------------------------


SEPARATOR = re.compile(r"\s*\|?[\s:|-]*-[\s:|-]*\|?\s*")


@dataclass
class Table:
    heading: str
    header: list[str]
    rows: list[list[str]]

    def idx(self, name: str) -> int:
        lowered = [h.lower() for h in self.header]
        for test in (lambda h: h == name, lambda h: h.startswith(name), lambda h: name in h):
            for k, h in enumerate(lowered):
                if test(h):
                    return k
        raise AssertionError(f"no column {name!r} in {self.header}")

    def has(self, name: str) -> bool:
        return any(name in h.lower() for h in self.header)

    def column(self, name: str) -> list[str]:
        k = self.idx(name)
        return [r[k] for r in self.rows if len(r) > k]

    def records(self) -> list[dict[str, str]]:
        return [dict(zip(self.header, r, strict=False)) for r in self.rows]

    def get(self, row: list[str], name: str) -> str:
        return row[self.idx(name)]


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def tables(out: str) -> list[Table]:
    lines = out.splitlines()
    found: list[Table] = []
    heading = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
        is_row = line.lstrip().startswith("|")
        if is_row and i + 1 < len(lines) and SEPARATOR.fullmatch(lines[i + 1]):
            rows: list[list[str]] = []
            j = i + 2
            while (
                j < len(lines)
                and lines[j].lstrip().startswith("|")
                and not (j + 1 < len(lines) and SEPARATOR.fullmatch(lines[j + 1]))
            ):
                rows.append(cells(lines[j]))
                j += 1
            found.append(Table(heading, cells(line), rows))
            i = j
            continue
        i += 1
    return found


def headings(out: str) -> list[str]:
    return [line[3:].strip().lower() for line in out.splitlines() if line.startswith("## ")]


def section(out: str, name: str) -> str:
    """The text of the `## ` section whose heading mentions `name`."""
    lines = out.splitlines()
    for k, line in enumerate(lines):
        if line.startswith("## ") and name in line.lower():
            end = next((j for j in range(k + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
            return "\n".join(lines[k:end])
    raise AssertionError(f"no section about {name!r} in {headings(out)}")


NEGATIVE = {
    "",
    "no",
    "false",
    "-",
    "—",
    "–",
    "n",
    "0",
    "insufficient",
    "pending",
    "n/a",
    "none",
    "not flagged",
}


def positive(cell: str) -> bool:
    return cell.strip().lower() not in NEGATIVE


def number(cell: str) -> float:
    m = re.search(r"-?\d+(?:[.,]\d+)?", cell.replace(",", ""))
    return float(m.group()) if m else math.nan


def one(found: list[Table], what: str) -> Table:
    assert len(found) == 1, f"expected one {what} table, found {[t.heading for t in found]}"
    return found[0]


def copy_table(out: str) -> Table:
    return one([t for t in tables(out) if t.has("pair a") and t.has("both wrong")], "copy pairs")


def relay_table(out: str) -> Table:
    return one([t for t in tables(out) if t.has("follower") and t.has("leader wrong")], "relays")


def people_table(out: str) -> Table:
    return one([t for t in tables(out) if t.has("pseudonym") and t.has("conversation")], "people")


def upstream_table(out: str) -> Table:
    return one([t for t in tables(out) if t.has("pseudonym") and t.has("matches")], "upstream-key")


def people(out: str) -> dict[str, dict[str, str]]:
    t = people_table(out)
    k = t.idx("pseudonym")
    return {r[k]: dict(zip(t.header, r, strict=False)) for r in t.rows}


def cell(record: dict[str, str], name: str) -> str:
    for key, value in record.items():
        if key.lower().startswith(name):
            return value
    raise AssertionError(f"no {name!r} in {list(record)}")


def pseudonyms(w: World, *names: str) -> set[str]:
    return {pseudo(w.ids[n]) for n in names}


def everyone_else(*names: str) -> list[str]:
    return [n for n in planted.PLAYERS if n not in names]


# --- the planted profiles ---------------------------------------------------------------------------------------


def test_report_flags_the_planted_profiles(world: World, integrity_env: str) -> None:
    out = run(
        [
            "integrity-report",
            "--until",
            "2026-10-12",
            "--checks",
            "all",
            "--salt-stdin",
        ],
        SALT + "\n",
    )  # the per-person window starts at the rule date: the default
    p = {name: pseudo(uid) for name, uid in world.ids.items()}
    window = range(planted.RULES_INDEX, planted.DAYS)
    wrong_days = len(planted.L_WRONG & set(window))

    # 1. follow-the-leader on the shared daily. Copy pairs name both players: the leader is in them too. The
    # alumna copied as well and is flagged with them, but never printed.
    copy = copy_table(out)
    pairs = {frozenset((copy.get(r, "pair a"), copy.get(r, "pair b"))) for r in copy.rows}
    ring = [p["leader"], p["follower"], p["simultaneous"]]
    assert pairs == {frozenset(x) for x in itertools.combinations(ring, 2)} | {
        frozenset((x, "not active")) for x in ring
    }
    for row in copy.rows:
        both = int(number(copy.get(row, "both wrong")))
        assert int(number(copy.get(row, "same wrong answer"))) == both
        if "not active" not in row:
            assert (int(number(copy.get(row, "together"))), both) == (len(window), wrong_days), row
            assert number(copy.get(row, "z")) >= 2.5
    simultaneous = next(r for r in copy.rows if {r[0], r[1]} == {p["leader"], p["simultaneous"]})
    assert copy.get(simultaneous, "a submitted first") != copy.get(simultaneous, "a started first"), (
        "the leader submits first and the simultaneous one opened it with them: both orders are context"
    )
    relays = relay_table(out)
    followers = set(relays.column("follower"))
    assert followers == {p["relayer"], p["relayer_late"]}
    for (
        row
    ) in relays.rows:  # right on every day the key was passed on: all the leader's wrong days but the suspect
        assert int(number(relays.get(row, "right"))) == int(number(relays.get(row, "leader wrong"))) - 1
        assert number(relays.get(row, "z")) >= 2.5
    late = [r for r in relays.rows if relays.get(r, "follower") == p["relayer_late"]]
    assert all(number(relays.get(r, "median dt")) > 3600 for r in late), "a relay has no window"
    outside = out.replace(section(out, "ai canary"), "")  # the canary's list may name a player with no family
    for name in set(planted.ACTIVE) - planted.FLAGGED:
        assert p[name] not in outside, f"{name} is named without being flagged"
    assert p["alumna"] not in out

    # 2. who is worth a conversation: two families, and only the follower and the simultaneous one have two
    found = people(out)
    assert set(found) == pseudonyms(world, *planted.FLAGGED), "exactly the planted profiles are flagged"
    assert p["prodigy"] not in found and p["strong_honest"] not in found, "a strong player is not a flag"
    for name, expected in planted.FAMILIES.items():
        record = found[p[name]]
        fired = {f.strip() for f in re.split(r"[,;+/]", cell(record, "families").lower()) if f.strip()}
        assert fired == expected, (name, fired)
        for family in ("performance", "timing", "provenance"):
            assert positive(cell(record, family)) is (family in expected), (name, family)
        assert positive(cell(record, "independent")) is ("provenance" in expected), name
        assert positive(cell(record, "conversation")) is (name in planted.CONVERSATION), name
    # pre-seen is a column of its own, not a silent filter; a timeout is counted and kept out of the pace
    uma = found[p["upstream"]]
    seen = len(
        [i for i in planted.PRACTICE["upstream"] if i in window]
    )  # the practice before the window counts too
    assert cell(uma, "n_preseen") == str(seen)
    assert len(window) - seen - 1 <= int(cell(uma, "n_first")) <= len(window) - seen
    assert 0 < number(cell(uma, "pre-seen lp share")) <= 1
    assert cell(uma, "timeouts").startswith("1/")
    assert number(cell(uma, "sd log")) < 0.5, "the 12-hour wait of a closed daily is not a latency"
    chance = one([t for t in tables(out) if t.has("family") and t.has("eligible")], "families")
    eligible = {r[0]: int(number(chance.get(r, "eligible"))) for r in chance.rows}
    assert eligible["performance"] == len(planted.ACTIVE) - 1, "practised has too few first-seen hard items"
    assert eligible["timing"] == len(planted.ACTIVE)
    assert {r[0]: int(number(chance.get(r, "flagged"))) for r in chance.rows}["timing"] == len(
        planted.CONVERSATION
    )
    table = people_table(out)
    assert table.has("canary hits/trials") and not any(h.lower() == "canary (ai)" for h in table.header)
    for header in CONTEXT_HEADERS:
        assert table.has(header), header

    # 3. upstream keys: the one who answered the corrected questions with the old key, and not the control
    upstream = upstream_table(out)
    rows = {r[upstream.idx("pseudonym")]: r for r in upstream.rows}
    mine = rows[p["upstream"]]
    assert int(number(upstream.get(mine, "matches"))) == len(planted.UP_DAYS)
    assert number(upstream.get(mine, "z")) >= 2.5
    for name in everyone_else("upstream"):
        if p[name] in rows:
            assert number(upstream.get(rows[p[name]], "z")) < 2.5, name

    # 4. a stored key that nobody can match is listed as a question, never a person
    suspect = [t for t in tables(out) if t.has("wilson") and t.has("question")]
    listed = [r for t in suspect for r in t.rows]
    assert [r for r in listed if str(world.suspect) in r], "the suspect key is listed"
    assert len(listed) == 1, listed
    assert re.search(rf"0\s*/\s*{len(planted.PLAYERS)}\b", " ".join(listed[0]))  # the alumna answered it too

    # 5. the replay behind check 0a reproduces every stored LP
    fidelity = next(line for line in out.splitlines() if "fidelity" in line.lower() and "%" in line)
    assert re.search(r"\b100(\.0+)?\s*%", fidelity), fidelity

    # 6. the decision thresholds are never printed (conftest.INTEGRITY_THRESHOLDS)
    for value in ("0:30:00", "30 min", f"{rules.tail(2.5):.4f}", f"{rules.tail(2.0):.4f}", "n >= 10"):
        assert value not in out, value


def test_the_alumna_who_copied_is_flagged_but_never_printed(
    world: World, integrity_env: str, db: Session
) -> None:
    snap = service.fetch(db, service.Window(date(2026, 9, 1), planted.UNTIL), frozenset(rules.CHECKS))
    t = service.thresholds(integrity_settings())
    fl = service.follow(snap, t)
    assert world.ids["alumna"] in fl.flagged, "she is part of who answered when"
    assert world.ids["alumna"] not in {p.key for p in service.persons(snap, t)}
    out = service.report(snap, SALT.encode(), frozenset(rules.CHECKS) - {"split"}, t)
    assert pseudo(world.ids["alumna"]) not in out
    assert "not active" in section(out, "follow")


def test_the_honest_controls_are_tested_and_come_out_clean(
    world: World, integrity_env: str, db: Session
) -> None:
    """The controls are in the tests, not beside them: honest players share wrong answers by chance (the leader's
    too) and the strong one is relay-tested against the leader every day, at and away from the leader's time."""
    snap = service.fetch(db, service.Window(date(2026, 9, 1), planted.UNTIL), frozenset(rules.CHECKS))
    t = service.thresholds(integrity_settings())
    fl = service.follow(snap, t)
    ring = {world.ids[n] for n in ("leader", "follower", "simultaneous", "alumna")}
    chance = [c for c in fl.copies if not {c.a, c.b} <= ring]
    assert any(c.shared_wrong > 0 for c in chance), "an honest coincidence was tested"
    assert not set(fl.copy_flagged) & set(chance)
    sue = world.ids["strong_honest"]
    tested = [r for r in fl.relays if r.follower == sue and r.leader == world.ids["leader"]]
    assert tested and tested[0].test.right > 0 and sue not in fl.flagged
    assert sue in fl.tested
    honest = {world.ids[n] for n in set(planted.ACTIVE) - planted.FLAGGED}
    assert not fl.flagged & honest


def test_the_supervised_family_is_pending_until_the_in_room_benchmark_exists(
    world: World, integrity_env: str
) -> None:
    out = report("--checks", "people")
    table = people_table(out)
    assert table.rows and {c.lower() for c in table.column("supervised")} == {"pending"}


def test_nothing_that_identifies_anyone_or_reveals_a_key_is_ever_printed(
    world: World, integrity_env: str
) -> None:
    out = run(
        [
            "integrity-report",
            "--until",
            "2026-10-12",
            "--checks",
            "all",
            "--split",
            "2026-09-20",
            "--salt-stdin",
        ],
        SALT + "\n",
    )
    lowered = out.lower()
    assert not [s for s in world.secrets() if s in out], (
        "a question, an option, a key or an audit detail leaked"
    )
    for name in planted.PROFILES:
        assert world.names[name] not in out and world.names[name].lower() not in lowered
        assert world.emails[name] not in out
    for word in ("@plant.test", "display_name", "email", "password", "plant.test"):
        assert word not in lowered
    assert not re.findall(r"(?<![0-9a-f])9000\d\d(?![0-9a-f])", out), "a user id"
    assert not [
        uid for uid in world.ids.values() if str(uid) in {c for line in out.splitlines() for c in cells(line)}
    ]

    per_person = [t for t in tables(out) if t.has("pseudonym") or t.has("follower") or t.has("pair a")]
    assert per_person, "the per-person tables exist"
    banned = re.compile(r"vertical|position|rank|date|day\b|email|name\b|\bid\b|user|question|lp\b(?! share)")
    for t in per_person:
        hits = [h for h in t.header if banned.search(h.lower())]
        assert not hits, f"{t.heading!r} prints {hits}"
    # a pseudonym only ever sits in a row of a per-person table
    pseudos = {pseudo(uid) for uid in world.ids.values()}
    row_lines = {tuple(r) for t in per_person for r in t.rows}
    for line in out.splitlines():
        if any(q in line for q in pseudos):
            assert line.lstrip().startswith("|") and tuple(cells(line)) in row_lines, line

    # a rate or a z never comes without its n
    for t in tables(out):
        if any(re.search(r"\bz\b|rate|share|accuracy|%|ρ|rho", h.lower()) for h in t.header):
            assert any(
                re.search(r"(?<![a-z])n(?![a-z])|plays|people|questions", h.lower()) or "(n)" in h.lower()
                for h in t.header
            ), f"{t.heading!r} has a rate or z without n: {t.header}"


def test_cohort_checks_print_no_person_and_never_cross_or_total_small_groups(
    world: World, integrity_env: str
) -> None:
    out = run(BASE, SALT + "\n")  # the default: elo, labels, permutation, keys, fidelity
    pseudos = {pseudo(uid) for uid in world.ids.values()}
    assert not [q for q in pseudos if q in out], "a cohort check printed a pseudonym"
    assert not [s for s in world.secrets() if s in out]
    for h in headings(out):
        assert not re.search(r"follow|upstream|profile|home|people|split", h), h
    assert re.search(r"fidelity.*\b100", out, re.IGNORECASE)

    tabs = tables(out)
    by_vertical, by_position = elo_tables(out)
    for t in (by_vertical, by_position):
        groups = [r[0] for r in t.rows]
        assert not [lb for lb in groups if re.search(r"total|all\b", lb, re.IGNORECASE)], groups
        assert not [lb for lb in groups if "Electronics" in lb and "member" in lb.lower()], (
            "groups were crossed"
        )
        assert all(int(c) >= 3 for c in t.column("people")), "a group under min_group"
    # the two Driverless mingos are too few to print on their own: they join the largest group, so nothing is
    # left out for a subtraction to recover
    assert [r[0] for r in by_vertical.rows] == ["Electronics + other", "Mechanical"]
    assert [r[0] for r in by_position.rows] == ["member + other"]
    assert by_vertical.column("people") == [
        str(planted.COUNT["Electronics"] + planted.COUNT["Driverless"]),
        str(planted.COUNT["Mechanical"]),
    ]
    assert_same_sums(by_vertical, by_position)
    stored, fixed = by_vertical.idx("stored"), by_vertical.idx("replayed")
    assert stored != fixed

    # the top-10 composition has a column per printed vertical group, never one for a small vertical
    (composition,) = [t for t in tabs if t.heading.lower().startswith("top")]
    assert composition.header[1:] == ["Electronics + other", "Mechanical"]

    # 0b: the labels, by area and whether a reviewer confirmed them
    labels = one([t for t in tabs if t.has("questions") and t.has("labels")], "labels")
    per_area: dict[str, int] = {}
    for r in labels.rows:
        per_area[r[labels.idx("area")]] = per_area.get(r[labels.idx("area")], 0) + int(
            number(labels.get(r, "questions"))
        )
    assert per_area == {"elec": planted.DAYS, "rules": 6, "mech": 4}
    assert sum(1 for r in labels.rows if r[labels.idx("area")] == "elec") >= 2  # confirmed and not

    # 0c: Mechanical against everyone else, both counted, nothing else about anyone
    perm = one([t for t in tabs if t.has("n_mech")], "permutation")
    (counted,) = perm.rows
    n_elec = str(planted.COUNT["Electronics"] + planted.COUNT["Driverless"])
    assert [perm.get(counted, k) for k in ("n_mech", "n_elec", "rounds", "seed")] == [
        str(planted.COUNT["Mechanical"]),
        n_elec,
        "5000",
        "0",
    ]
    assert 0 < number(perm.get(counted, "p")) <= 1

    # 2b: the suspect key, as a question
    assert str(world.suspect) in " ".join(" ".join(r) for t in tabs if t.has("wilson") for r in t.rows)


ADDITIVE = ("people", "plays", "pooled", "pre-seen", "replay mismatch")
CONTEXT_HEADERS = (
    "undeclared away any/over/n",
    "declared away any/n",
    "pasted/text n",
    "long copies attempts/n",
    "resumes attempts/n",
    "decoy attempts without totals/n",
)


def elo_tables(out: str) -> tuple[Table, Table]:
    found = {t.heading.lower(): t for t in tables(out) if t.heading.lower().startswith("by ")}
    return found["by vertical"], found["by position"]


def totals(t: Table) -> dict[str, int]:
    return {name: sum(int(number(c)) for c in t.column(name)) for name in ADDITIVE}


def assert_same_sums(a: Table, b: Table) -> None:
    """Both tables cover the same people with nothing left out: a column's sum is the same in both, so no
    subtraction of one table from the other is anyone."""
    assert totals(a) == totals(b)


def test_a_lone_vertical_inside_a_full_position_table_is_pooled(
    world: World, integrity_env: str, db: Session
) -> None:
    db.execute(
        update(User).where(User.id.in_([world.ids["drive1"], world.ids["drive2"]])).values(position="member")
    )
    db.execute(update(User).where(User.id == world.ids["honest"]).values(vertical="Board"))
    db.commit()
    out = report("--checks", "elo")
    by_vertical, by_position = elo_tables(out)
    assert [r[0] for r in by_position.rows] == ["member"]  # every position printed
    assert "Board" not in section(out, "elo") and "Driverless" not in section(out, "elo")
    other = next(r for r in by_vertical.rows if r[0] == "other")
    assert by_vertical.get(other, "people") == "3"  # the Board member with the two from Driverless
    assert_same_sums(by_vertical, by_position)
    (composition,) = [t for t in tables(out) if t.heading.lower().startswith("top")]
    assert "Board" not in " ".join(composition.header)


def test_a_position_nested_in_a_vertical_withholds_the_position_table(
    world: World, integrity_env: str, db: Session
) -> None:
    """Three Mechanical technical directors in a Mechanical vertical of four: the vertical minus the directors would
    be the fourth, so the position table is not printed."""
    db.execute(update(User).where(User.id == world.ids["honest"]).values(vertical="Mechanical"))
    mechanics = [world.ids[n] for n in ("mech", "mech2", "mech3")]
    db.execute(update(User).where(User.id.in_(mechanics)).values(position="technical_director"))
    db.commit()
    out = report("--checks", "elo")
    found = {t.heading.lower() for t in tables(out)}
    assert "by vertical" in found and "by position" not in found
    assert "Withheld" in section(out, "elo")


def test_the_fixed_rank_changes_only_the_replayed_column(world: World, integrity_env: str) -> None:
    low = report("--checks", "elo", "--fixed-rank", "350")
    default = report("--checks", "elo")
    high = report("--checks", "elo", "--fixed-rank", "600")
    assert low == default  # IFS_INTEGRITY_FIXED_RANK defaults to 350
    assert low != high

    a, b = elo_tables(low)[0], elo_tables(high)[0]
    assert a.column("stored") == b.column("stored")
    assert a.column("people") == b.column("people") and a.column("plays") == b.column("plays")
    assert a.column("replayed") != b.column("replayed")


def test_the_neutral_knobs_come_from_the_environment(
    world: World, integrity_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = report("--checks", "elo,permutation")
    monkeypatch.setenv("IFS_INTEGRITY_MIN_GROUP", "1")
    small = report("--checks", "elo,permutation")
    groups = [r[0] for t in tables(small) if t.has("people") for r in t.rows]
    assert any("Driverless" in g for g in groups) and any("mingo" in g for g in groups), "min_group is read"
    assert "Driverless" not in section(baseline, "elo")

    monkeypatch.delenv("IFS_INTEGRITY_MIN_GROUP")
    monkeypatch.setenv("IFS_INTEGRITY_PERMUTATION_ROUNDS", "200")
    monkeypatch.setenv("IFS_INTEGRITY_SEED", "7")
    perm = one([t for t in tables(report("--checks", "permutation")) if t.has("n_mech")], "permutation")
    assert [perm.get(perm.rows[0], k) for k in ("rounds", "seed")] == ["200", "7"]

    monkeypatch.delenv("IFS_INTEGRITY_PERMUTATION_ROUNDS")
    monkeypatch.delenv("IFS_INTEGRITY_SEED")
    monkeypatch.setenv("IFS_INTEGRITY_Z", "2.58")
    wide = report("--checks", "elo")
    narrow_cells = [
        c for t in tables(baseline) if t.has("wilson") for r in t.rows for c in r if c.startswith("[")
    ]
    wide_cells = [c for t in tables(wide) if t.has("wilson") for r in t.rows for c in r if c.startswith("[")]
    assert narrow_cells and narrow_cells != wide_cells, "z is read: the Wilson intervals changed"


def test_the_read_only_engine_has_its_guard_rails(integrity_env: str) -> None:
    engine = read_only_engine(integrity_env)
    try:
        with engine.connect() as c:
            shown = {
                name: c.execute(text(f"SHOW {name}")).scalar_one()
                for name in (
                    "transaction_read_only",
                    "transaction_isolation",
                    "default_transaction_read_only",
                    "statement_timeout",
                    "lock_timeout",
                    "idle_in_transaction_session_timeout",
                )
            }
            first_pid = c.execute(text("SELECT pg_backend_pid()")).scalar_one()
            with pytest.raises(DBAPIError) as e:
                c.execute(text("CREATE TEMP VIEW v AS SELECT 1"))
            assert isinstance(e.value.orig, psycopg.errors.ReadOnlySqlTransaction)
        assert shown == {
            "transaction_read_only": "on",
            "transaction_isolation": "repeatable read",
            "default_transaction_read_only": "on",
            "statement_timeout": "2min",
            "lock_timeout": "5s",
            "idle_in_transaction_session_timeout": "1min",
        }
        with engine.connect() as c:  # no pool: every connection is a new backend, closed with its owner
            assert c.execute(text("SELECT pg_backend_pid()")).scalar_one() != first_pid
        assert isinstance(engine.pool, NullPool)
    finally:
        engine.dispose()


def test_the_report_is_deterministic_and_the_salt_changes_every_pseudonym(
    world: World, integrity_env: str
) -> None:
    first = run([*BASE, "--checks", "all"], SALT + "\n")
    assert first == run([*BASE, "--checks", "all"], SALT + "\n"), (
        "seeded: the same data prints the same report"
    )

    other = "c" * 64
    second = report("--checks", "all", salt=other)
    assert not [q for q in (pseudo(uid) for uid in world.ids.values()) if q in second], (
        "another review's salt"
    )
    assert pseudo(world.ids["follower"], other) in second
    assert set(people(second)) == pseudonyms_with(world, other, *planted.FLAGGED)
    assert len(copy_table(second).rows) == len(copy_table(first).rows)
    assert len(relay_table(second).rows) == len(relay_table(first).rows)


def pseudonyms_with(w: World, salt: str, *names: str) -> set[str]:
    return {pseudo(w.ids[n], salt) for n in names}


def test_the_window_selects_days_but_the_replay_walks_from_the_season_start(
    world: World, integrity_env: str, db: Session
) -> None:
    t = service.thresholds(integrity_settings())

    def counts(since: date, until: date) -> tuple[int, int]:
        snap = service.fetch(db, service.Window(since, until), frozenset(rules.CHECKS))
        db.rollback()
        pair = next(
            c
            for c in service.follow(snap, t).copies
            if {c.a, c.b} == {world.ids["leader"], world.ids["follower"]}
        )
        return pair.items, pair.both_wrong

    def wrong_in(days: range) -> int:
        return len([i for i in days if i in planted.L_WRONG])

    # --since is a Madrid day, inclusive: 20 September is day 18 of the 40
    assert counts(date(2026, 9, 20), planted.UNTIL) == (22, wrong_in(range(18, 40)))
    # --until is the announcement date, excluded: 2 October is day 30
    assert counts(date(2026, 9, 1), date(2026, 10, 2)) == (30, wrong_in(range(0, 30)))
    assert counts(date(2026, 9, 12), date(2026, 10, 2)) == (20, wrong_in(range(10, 30)))
    # the replay still starts with the season, so a short window is as faithful as the whole
    short = report("--checks", "fidelity", "--since", "2026-10-05")
    assert re.search(r"\b100(\.0+)?\s*%", short)


def test_check_selection(world: World, integrity_env: str) -> None:
    only_follow = report("--checks", "follow")
    assert copy_table(only_follow) and relay_table(only_follow)
    assert "## upstream-key" not in only_follow
    assert not any("people" in h or "upstream" in h for h in headings(only_follow))

    # `people` needs follow, upstream-key, profile and home-away, and computes them without printing them
    alone = report("--checks", "people")
    assert set(people(alone)) == pseudonyms(world, *planted.FLAGGED)
    assert not any(re.search(r"follow|upstream|profile|home", h) for h in headings(alone)), headings(alone)

    both = report("--checks", "follow,people")
    assert len([h for h in headings(both) if "follow" in h]) == 1
    assert len([h for h in headings(both) if "people" in h]) == 1
    assert not [
        h for h in headings(both) if re.search(r"label|fidelity|upstream|profile|home|permutation", h)
    ]

    assert report("--checks", "cohort") == report()
    everything = report("--checks", "all")
    for name in ("label", "permutation", "fidelity", "follow", "upstream", "profile", "home", "people"):
        assert any(name in h for h in headings(everything)), name
    assert "p10" in section(everything, "profile") and "p90" in section(everything, "profile")

    # a spec for a split that was not asked for is ignored; one that was asked for needs its date
    assert not any("split" in h for h in headings(report("--checks", "follow", "--split", "2026-09-20")))
    with pytest.raises(SystemExit):
        report("--checks", "split")
    for outside in ("2026-09-01", "2026-10-12", "2026-08-20"):  # the families are read before it: inside only
        with pytest.raises(SystemExit, match="--split"):
            report("--checks", "people,split", "--split", outside)


def test_split_prints_only_the_flagged(world: World, integrity_env: str) -> None:
    out = report("--checks", "follow,people,split", "--split", "2026-09-20")
    found = set(re.findall(r"(?<![0-9a-f])[0-9a-f]{8}(?![0-9a-f])", section(out, "split")))
    flagged = pseudonyms(world, *planted.FLAGGED)
    assert found and found <= flagged
    assert pseudonyms(world, "follower", "simultaneous") <= found
    (families,) = [t for t in tables(section(out, "split")) if t.has("families before")]
    fay = next(r for r in families.rows if r[0] == pseudo(world.ids["follower"]))
    assert families.get(fay, "families before") == "timing" and families.get(fay, "n before") == str(
        18 - planted.RULES_INDEX
    )
    (moved,) = [t for t in tables(section(out, "split")) if t.has("people (n)")]
    assert {r[0] for r in moved.rows} == {"median log time", "below-floor share"}


def test_split_shows_a_behaviour_that_stopped(world: World, integrity_env: str, db: Session) -> None:
    """The follower stopped copying on 20 September and answered on their own from then on, at a reader's pace:
    over the window their timing is diluted below the threshold, before the split it is plain."""
    later = db.scalars(
        select(Attempt).where(Attempt.user_id == world.ids["follower"], Attempt.day >= date(2026, 9, 20))
    ).all()
    for a in later:
        a.submitted_at = a.created_at + timedelta(
            seconds=planted.human_seconds((cast(date, a.day) - planted.FIRST_DAY).days, 20.0, 0.4)
        )
    db.commit()
    out = report("--checks", "people,split", "--split", "2026-09-20")
    fay = pseudo(world.ids["follower"])
    (families,) = [t for t in tables(section(out, "split")) if t.has("families before")]
    row = next(r for r in families.rows if r[0] == fay)
    assert "timing" in families.get(row, "families before")
    assert "timing" not in families.get(row, "families over the window")


# --- what the SQL may do -----------------------------------------------------------------------------------------


def test_report_sql_is_select_only_and_never_names_identity(world: World, integrity_env: str) -> None:
    engine = read_only_engine(integrity_env)
    with engine.connect():  # the dialect's own first-connect queries are not the report's
        pass
    seen: list[tuple[str, Any, Any]] = []

    @event.listens_for(engine, "before_cursor_execute")
    def record(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        mode = cursor.connection.execute("SHOW transaction_read_only").fetchone()
        isolation = cursor.connection.execute("SHOW transaction_isolation").fetchone()
        seen.append((statement, mode, isolation))

    try:
        with Session(engine) as s:
            service.fetch(s, service.Window(date(2026, 9, 1), planted.UNTIL), frozenset(rules.CHECKS))
            s.rollback()
    finally:
        engine.dispose()
    assert seen, "the fetch ran no statement"
    banned = re.compile(r"\b(email|display_name|password_hash|position_lifts|details)\b", re.IGNORECASE)
    for statement, mode, isolation in seen:
        head = statement.lstrip().upper()
        assert head.startswith(("SELECT", "WITH")), statement[:80]
        # a key test on the audit details is a boolean, not the details: the position changes this season
        statement = statement.replace("audit_log.details ? ", "")
        assert not banned.search(statement), (
            f"names identity: {banned.search(statement)} in {statement[:200]}"
        )
        assert "FOR UPDATE" not in head and "FOR SHARE" not in head
        assert tuple(mode) == ("on",), "every statement of the report runs in a read-only transaction"
        assert tuple(isolation) == ("repeatable read",), "and in one snapshot"


def test_the_report_writes_nothing(world: World, integrity_env: str, db: Session) -> None:
    def counts() -> dict[str, int]:
        db.rollback()
        names = db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).all()
        return {n: db.execute(text(f'SELECT count(*) FROM "{n}"')).scalar_one() for n in names}  # noqa: S608

    before = counts()
    assert before["attempts"] > 0 and before["audit_log"] > 0
    run([*BASE, "--checks", "all", "--split", "2026-09-20"], SALT + "\n")
    run(["integrity-reveal", pseudo(world.ids["honest"]), "--salt-stdin"], SALT + "\n")
    assert counts() == before


def test_an_empty_database_prints_every_section_with_n_a(db: Session, integrity_env: str) -> None:
    out = report("--checks", "all", "--split", "2026-09-20")
    for name in (
        "label",
        "permutation",
        "fidelity",
        "follow",
        "upstream",
        "profile",
        "home",
        "people",
        "split",
    ):
        assert any(name in h for h in headings(out)), name
    assert "n/a" in out
    assert not re.search(r"Traceback|\bnan\b|\bNone\b|\binf\b", out)


# --- the command's guards ------------------------------------------------------------------------------------------


@pytest.fixture
def never_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> Engine:
        raise AssertionError("the report opened a connection before its guards passed")

    monkeypatch.setattr("ifs_tests.db.session.read_only_engine", boom)
    monkeypatch.setattr("ifs_tests.cli.read_only_engine", boom, raising=False)
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "")


UNREACHABLE = "postgresql+psycopg://nobody@127.0.0.1:9/none"


def test_no_salt_no_report(monkeypatch: pytest.MonkeyPatch, never_connect: None) -> None:
    set_integrity_env(monkeypatch, UNREACHABLE, salt=None)
    with pytest.raises(SystemExit, match="(?i)salt"):
        run(["integrity-report", "--until", "2026-10-12"])  # the prompt answers with nothing
    with pytest.raises(SystemExit, match="(?i)salt"):
        run([*BASE], "")  # --salt-stdin with an empty stdin


@pytest.mark.parametrize("length", [0, 1, 31])
def test_a_short_salt_is_refused(monkeypatch: pytest.MonkeyPatch, never_connect: None, length: int) -> None:
    set_integrity_env(monkeypatch, UNREACHABLE, salt=None)
    with pytest.raises(SystemExit, match="(?i)salt"):
        run(BASE, "s" * length + "\n")
    set_integrity_env(monkeypatch, UNREACHABLE, salt="s" * length)
    with pytest.raises(SystemExit, match="(?i)salt"):
        run(["integrity-report", "--until", "2026-10-12"])


def test_a_salt_of_32_characters_is_enough(world: World, integrity_env: str) -> None:
    assert report("--checks", "fidelity", salt="k" * 32)
    with pytest.raises(SystemExit):
        report("--checks", "fidelity", salt="k" * 31)


def test_the_salt_comes_from_stdin_then_the_environment_then_a_prompt(
    world: World, integrity_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_salt, typed, piped = "e" * 40, "t" * 40, "p" * 40
    target = world.ids["honest"]
    set_integrity_env(monkeypatch, integrity_env, salt=env_salt)
    assert str(target) in run(["integrity-reveal", pseudo(target, env_salt)])
    # --salt-stdin wins over the environment
    assert str(target) in run(["integrity-reveal", pseudo(target, piped), "--salt-stdin"], piped + "\n")
    with pytest.raises(SystemExit):
        run(["integrity-reveal", pseudo(target, env_salt), "--salt-stdin"], piped + "\n")

    set_integrity_env(monkeypatch, integrity_env, salt=None)
    prompts: list[str] = []

    def prompt(*args: object, **kwargs: object) -> str:
        prompts.append(str(args[0] if args else kwargs.get("prompt", "")))
        return typed

    monkeypatch.setattr("getpass.getpass", prompt)
    assert str(target) in run(["integrity-reveal", pseudo(target, typed)])
    assert len(prompts) == 1 and "salt" in prompts[0].lower()
    # an environment salt means no prompt at all
    set_integrity_env(monkeypatch, integrity_env, salt=env_salt)
    run(["integrity-reveal", pseudo(target, env_salt)])
    assert len(prompts) == 1


def test_no_dsn_no_thresholds_no_report(monkeypatch: pytest.MonkeyPatch, never_connect: None) -> None:
    set_integrity_env(monkeypatch, UNREACHABLE)
    monkeypatch.delenv("IFS_INTEGRITY_DSN")
    with pytest.raises(SystemExit, match="IFS_INTEGRITY_DSN"):
        run(BASE, SALT + "\n")

    set_integrity_env(monkeypatch, UNREACHABLE)
    monkeypatch.delenv("IFS_INTEGRITY_MIN_N")
    with pytest.raises(SystemExit, match="IFS_INTEGRITY_MIN_N"):
        run(BASE, SALT + "\n")

    monkeypatch.delenv("IFS_INTEGRITY_UPSTREAM_Z")
    monkeypatch.delenv("IFS_INTEGRITY_FOLLOW_WITHIN_MIN")
    with pytest.raises(SystemExit) as e:
        run(BASE, SALT + "\n")
    for name in ("MIN_N", "UPSTREAM_Z", "FOLLOW_WITHIN_MIN"):  # every missing one
        assert f"IFS_INTEGRITY_{name}" in str(e.value.code)
    for name in ("FOLLOW_Z", "FOLLOW_MIN", "AWAY_Z"):  # and none that is set
        assert f"IFS_INTEGRITY_{name}" not in str(e.value.code)

    # a value that is there but not a number is invalid, not missing
    set_integrity_env(monkeypatch, UNREACHABLE)
    monkeypatch.setenv("IFS_INTEGRITY_MIN_N", "ten")
    monkeypatch.setenv("IFS_INTEGRITY_AWAY_Z", "2.0z")
    monkeypatch.delenv("IFS_INTEGRITY_FOLLOW_Z")
    with pytest.raises(SystemExit) as e:
        run(BASE, SALT + "\n")
    message = str(e.value.code)
    assert "invalid IFS_INTEGRITY_AWAY_Z, IFS_INTEGRITY_MIN_N" in message
    assert "missing IFS_INTEGRITY_FOLLOW_Z" in message and "missing IFS_INTEGRITY_MIN_N" not in message


def test_the_window_is_checked(world: World, integrity_env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit):  # the day after the day it runs
        run(["integrity-report", "--until", "2026-10-13", "--salt-stdin"], SALT + "\n")
    freeze_today(monkeypatch, datetime(2026, 10, 5, 12, 0, tzinfo=UTC))
    with pytest.raises(SystemExit):  # a run on 5 October cannot be about plays up to the 12th
        run(BASE, SALT + "\n")
    # "today" is a Madrid day: at 23:59 on the 12th the 13th is still tomorrow, half an hour later it is today
    freeze_today(monkeypatch, datetime(2026, 10, 12, 21, 59, tzinfo=UTC))
    with pytest.raises(SystemExit):
        run(
            ["integrity-report", "--until", "2026-10-13", "--checks", "fidelity", "--salt-stdin"], SALT + "\n"
        )
    freeze_today(monkeypatch, datetime(2026, 10, 12, 22, 30, tzinfo=UTC))
    assert run(
        ["integrity-report", "--until", "2026-10-13", "--checks", "fidelity", "--salt-stdin"], SALT + "\n"
    )
    with pytest.raises(SystemExit, match="season"):
        run([*BASE, "--since", "2026-08-01"], SALT + "\n")
    with pytest.raises(SystemExit, match="season"):
        run([*BASE, "--since", "2026-08-31"], SALT + "\n")  # the day before 1 September
    with pytest.raises(SystemExit, match="season"):
        run(
            ["integrity-report", "--until", "2026-09-15", "--since", "2026-08-31", "--salt-stdin"],
            SALT + "\n",
        )
    assert report(
        "--since", "2026-09-01", "--checks", "fidelity"
    )  # 1 September itself is the season's first day
    with pytest.raises(SystemExit):
        run(["integrity-report", "--salt-stdin"], SALT + "\n")  # --until is required


def test_unknown_checks_are_refused_with_the_valid_names(world: World, integrity_env: str) -> None:
    for bad in ("bogus", "follow,nonsense"):
        with pytest.raises(SystemExit, match="Unknown checks") as e:
            report("--checks", bad)
        assert "upstream-key" in str(e.value.code) and "home-away" in str(e.value.code)


# --- the reveal -------------------------------------------------------------------------------------------------------


def lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.strip()]


def test_reveal_prints_only_the_named_pseudonyms(world: World, integrity_env: str) -> None:
    fay = world.ids["follower"]
    out = run(["integrity-reveal", pseudo(fay), "--salt-stdin"], SALT + "\n")
    (line,) = lines(out)
    assert line.index(pseudo(fay)) < line.index(str(fay)) < line.index("Follower Fay")
    assert world.emails["follower"] not in out
    assert not [n for k, n in world.names.items() if k != "follower" and n in out]

    both = run(["integrity-reveal", pseudo(fay), pseudo(world.ids["honest"]), "--salt-stdin"], SALT + "\n")
    assert len(lines(both)) == 2 and "Honest Hal" in both and "Follower Fay" in both
    assert "Relay Rae" not in both and "Leader Lou" not in both


def test_reveal_exits_1_for_an_unknown_pseudonym_or_the_wrong_salt(world: World, integrity_env: str) -> None:
    with pytest.raises(SystemExit) as e:
        run(["integrity-reveal", "deadbeef", "--salt-stdin"], SALT + "\n")
    assert e.value.code == 1 or isinstance(e.value.code, str)
    with pytest.raises(SystemExit):
        run(["integrity-reveal", pseudo(world.ids["follower"], "z" * 40), "--salt-stdin"], SALT + "\n")
    with pytest.raises(SystemExit):
        run(["integrity-reveal", "--salt-stdin"], SALT + "\n")  # nothing named


def test_reveal_finds_alumni_only_when_asked(world: World, integrity_env: str) -> None:
    alma = pseudo(world.ids["alumna"])
    with pytest.raises(SystemExit):
        run(["integrity-reveal", alma, "--salt-stdin"], SALT + "\n")
    out = run(["integrity-reveal", alma, "--include-alumni", "--salt-stdin"], SALT + "\n")
    assert "Alma Alumna" in out and str(world.ids["alumna"]) in out
    # active users are still found with the flag, and listed first
    both = run(
        ["integrity-reveal", alma, pseudo(world.ids["honest"]), "--include-alumni", "--salt-stdin"],
        SALT + "\n",
    )
    assert len(lines(both)) == 2 and both.index("Honest Hal") < both.index("Alma Alumna")


# --- the replay through the real services --------------------------------------------------------------------------


def md(month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, second, tzinfo=planted.MADRID)


def make_question(db: Session, area: str, name: str, difficulty: int = 3) -> tuple[Question, list[int]]:
    """A graded single choice with four options; the key is the first of the returned ids."""
    q = Question(
        type="single-choice",
        text=name,
        time_s=600,
        area=area,
        difficulty=difficulty,
        answer_kind="choice-one",
        graded=True,
        playable=True,
        source_hash=name,
    )
    db.add(q)
    db.flush()
    ids: list[int] = []
    for p in range(4):
        o = AnswerOption(question_id=q.id, position=p, text=f"{name}-{p}")
        db.add(o)
        db.flush()
        ids.append(o.id)
    db.add(AnswerKey(question_id=q.id, key={"kind": "choice", "mode": "one", "options": [ids[0]]}))
    db.flush()
    return q, ids


def test_replay_fidelity_through_the_real_services(db: Session, integrity_env: str) -> None:
    """The proof that replay_lp reproduces what xp.grant stored, on rows the services wrote themselves: a hint, a
    daily left to run out and closed by the nightly job, a repeat, a mock run with a pass, a late answer, a bad
    run and its comeback, a daily answered in the middle of the run, a question ended unanswered, a second
    (uncounted) run of the same quiz, a daily started before midnight and answered after it, a daily whose
    question ran out unseen in an ended mock run first (hidden from the daily, which must still pay in full), a bad
    run from August carried across the season change (users.miss_streak is never reset), and a daily and a mock
    question closed by the nightly job at the same instant (the dailies first, whatever the ids)."""
    user = User(
        email="svc@plant.test",
        password_hash="x",
        display_name="Svc Sam",
        vertical="Electronics",
        position="member",
    )
    db.add(user)
    hint_q, hint_o = make_question(db, "elec", "hint", 3)
    repeat_q, repeat_o = make_question(db, "mech", "repeat", 4)
    out_q, _ = make_question(db, "rules", "runs-out", 2)
    night_q, night_o = make_question(db, "elec", "night", 3)
    hidden_q, hidden_o = make_question(db, "elec", "hidden", 3)
    filler = [make_question(db, "elec", f"filler{k}")[0] for k in range(3)]
    plan = ["right", "pass", "late", "wrong", "wrong", "wrong", "right", "leave"]
    mock_questions = [
        make_question(db, ("elec", "rules", "mech")[k % 3], f"mock{k}", 2 + k % 3) for k in range(len(plan))
    ]
    august = [make_question(db, "elec", f"aug{k}", 3) for k in range(3)]
    tie_q, _ = make_question(db, "mech", "tie", 4)
    for k, (q, _) in enumerate(august):
        db.add(DailyQuestion(day=date(2026, 8, 28 + k), area="elec", question_id=q.id))
    day1, day2, day3 = date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)
    for day, chosen in (
        (day1, (repeat_q, hint_q, out_q)),
        (day2, (filler[0], night_q, filler[1])),
        (day3, (filler[2], hidden_q, filler[2])),
    ):
        for area, q in zip(("mech", "elec", "rules"), chosen, strict=True):
            db.add(DailyQuestion(day=day, area=area, question_id=q.id, drawn_at=planted.madrid(day, 0, 1)))
    db.add(Quiz(id=9100, year=2026, vehicle_class="cv", held_on=date(2026, 3, 1), status="complete"))
    db.add(Quiz(id=9101, year=2026, vehicle_class="cv", held_on=date(2026, 3, 2), status="complete"))
    db.add(Quiz(id=9102, year=2026, vehicle_class="cv", held_on=date(2026, 3, 3), status="complete"))
    db.flush()
    db.add(QuizQuestion(quiz_id=9102, question_id=tie_q.id, position=0))
    for position, (q, _) in enumerate(mock_questions):
        db.add(QuizQuestion(quiz_id=9100, question_id=q.id, position=position))
    db.add(QuizQuestion(quiz_id=9101, question_id=hidden_q.id, position=0))
    db.commit()

    def pick(ids: list[int], right: bool) -> list[int]:
        return [ids[0] if right else ids[1]]

    # 28-30 August, the previous season: three dailies wrong, a bad run of three that September doesn't reset
    for k, (_, ids) in enumerate(august):
        _, a = daily.start(db, user, "elec", md(8, 28 + k, 9))
        daily.answer(db, user, a.id, pick(ids, False), None, md(8, 28 + k, 9, 1))
    # 4 October: practice on a question that becomes a daily the next day
    practice.answer(db, user, repeat_q.id, pick(repeat_o, True), None, md(10, 4, 18))
    # 5 October: a daily with a hint, a repeat answered wrong, and one left to run out
    _, hinted = daily.start(db, user, "elec", md(10, 5, 9))
    hints.timed(db, user, hinted.id, md(10, 5, 9, 0, 10))
    daily.answer(db, user, hinted.id, pick(hint_o, True), None, md(10, 5, 9, 1))
    _, again = daily.start(db, user, "mech", md(10, 5, 9, 5))
    daily.answer(db, user, again.id, pick(repeat_o, False), None, md(10, 5, 9, 6))
    daily.start(db, user, "rules", md(10, 5, 9, 20))
    # 6 October, 03:00: the nightly job charges the one that ran out
    assert close_run_outs(db, md(10, 6, 3)) == 1
    # a counted mock run: right, pass, late, three wrong in a row, the comeback, then ended on the last question
    now = md(10, 6, 9)
    first_run = mock.start(db, user, 9100, now)
    state = mock.state(db, user, first_run.id, now)
    for action in plan:
        assert state.current is not None
        q, a = state.current
        if action == "leave":
            break
        ids = next(o for (mq, o) in mock_questions if mq.id == q.id)
        if action == "late" and a.deadline_at:
            now = a.deadline_at + timedelta(seconds=10)
        else:
            now += timedelta(seconds=45)
        options = None if action == "pass" else pick(ids, action in ("right", "late"))
        state = mock.answer(db, user, first_run.id, a.id, options, None, now, unsure=action == "pass")
    # a daily answered in the middle of the run: the bad run in progress goes on across modes, and the run's
    # last question is charged after it
    _, between = daily.start(db, user, "rules", md(10, 6, 10, 30))
    daily.answer(db, user, between.id, pick(_options(db, filler[1]), False), None, md(10, 6, 10, 31))
    mock.end(db, user, first_run.id, md(10, 6, 11))
    # the same quiz again the same day: not counted, moves no LP
    now = md(10, 6, 14)
    second_run = mock.start(db, user, 9100, now)
    state = mock.state(db, user, second_run.id, now)
    while state.current is not None:
        q, a = state.current
        ids = next(o for (mq, o) in mock_questions if mq.id == q.id)
        now += timedelta(seconds=20)
        state = mock.answer(db, user, second_run.id, a.id, pick(ids, True), None, now)
    # a daily started before midnight and answered after it
    _, night = daily.start(db, user, "elec", md(10, 6, 23, 58))
    daily.answer(db, user, night.id, pick(night_o, True), None, md(10, 7, 0, 3))
    # 7 October: today's question is on screen in a mock run that is ended unanswered (hidden from the daily),
    # and then the daily itself is answered
    hidden_run = mock.start(db, user, 9101, md(10, 7, 9))
    mock.state(db, user, hidden_run.id, md(10, 7, 9))
    mock.end(db, user, hidden_run.id, md(10, 7, 9, 1))
    _, unseen = daily.start(db, user, "elec", md(10, 7, 9, 10))
    daily.answer(db, user, unseen.id, pick(hidden_o, True), None, md(10, 7, 9, 11))
    # 7 October, evening: a mock question shown, then a daily started, both left; the nightly job at 03:00 closes
    # them at the same instant, the daily first although the mock question has the lower id
    tie_run = mock.start(db, user, 9102, md(10, 7, 22))
    mock.state(db, user, tie_run.id, md(10, 7, 22))
    daily.start(db, user, "rules", md(10, 7, 22, 5))
    assert close_run_outs(db, md(10, 8, 3)) == 1
    assert mock.close_expired(db, md(10, 8, 3)) == 1
    db.expire_all()

    assert db.scalar(select(User.miss_streak).where(User.id == user.id)) is not None
    attempts = db.scalars(
        select(Attempt)
        .where(
            Attempt.user_id == user.id,
            Attempt.mode.in_(("daily", "mock")),
            Attempt.submitted_at.is_not(None),
            Attempt.created_at >= md(9, 1),
        )
        .order_by(Attempt.submitted_at, Attempt.mode, Attempt.id)  # 'daily' < 'mock'
    ).all()
    # the scenario really covered what it claims to
    assert any(a.mode == "daily" and a.hint_used for a in attempts)
    assert any(a.mode == "daily" and a.late and a.answer == {} for a in attempts), "a daily closed by the job"
    assert any(a.mode == "mock" and a.late and a.answer == {} for a in attempts), (
        "a mock question ended unanswered"
    )
    assert any(a.mode == "mock" and a.late and a.answer != {} for a in attempts), "a late answer"
    assert any(a.passed for a in attempts)
    assert db.scalar(select(func.count()).select_from(MockSession).where(MockSession.counted.is_(False))) == 1
    in_first_run = [a for a in attempts if a.session_id == first_run.id]
    assert sum(1 for a in in_first_run if a.correct is False and not a.late and not a.passed) == 3
    order = [(a.mode, a.session_id) for a in attempts]
    assert ("daily", None) in order[order.index(("mock", first_run.id)) :], (
        "a daily between two answers of a run"
    )
    stored = [a.lp for a in attempts]
    assert any(x != 0 for x in stored) and all(a.lp == 0 for a in attempts if a.session_id == second_run.id)
    hidden_daily = next(a for a in attempts if a.id == unseen.id)
    assert hidden_daily.lp > 0
    tied = [a for a in attempts if a.submitted_at == md(10, 8, 3)]
    assert [a.mode for a in tied] == ["daily", "mock"] and tied[0].id > tied[1].id

    snap = service.fetch(
        db, service.Window(date(2026, 9, 1), date(2026, 10, 12)), frozenset({"fidelity", "elo"})
    )
    played = service.ranked_plays(snap)[user.id]
    assert [row.id for row, _ in played] == [a.id for a in attempts], "grading order is submit order"
    assert [p.lp for _, p in played] == pytest.approx(stored, abs=1e-9)
    assert service.miss0(snap, user.id) == 3, "the August bad run is carried into the season"
    start = round(db.scalars(select(User.rank_points).where(User.id == user.id)).one() - sum(stored), 2)
    replayed = rules.replay_lp([p for _, p in played], start, miss0=3)
    assert replayed == pytest.approx(stored, abs=1e-9)
    assert rules.replay_lp([p for _, p in played], start) != pytest.approx(stored, abs=1e-9), (
        "without the carried run the replay would not reproduce the season's first plays"
    )
    assert [p.ranked for _, p in played].count(False) == len(plan)  # the uncounted run is replayed, as no LP

    flags = [p for _, p in played]
    assert any(p.hint for p in flags) and any(p.repeat for p in flags) and any(p.passed for p in flags)
    timeouts = [p for (row, p) in played if not row.answered]
    assert len(timeouts) == 5 and all(p.late and not p.hint for p in timeouts)
    daily_timeout = next(p for (row, p) in played if not row.answered and row.mode == "daily")
    assert daily_timeout.again_today is False
    unseen_play = next(p for (row, p) in played if row.id == unseen.id)
    assert (unseen_play.repeat, unseen_play.again_today) == (False, False), (
        "a hidden mock timeout is not seen"
    )

    thresholds = service.thresholds(integrity_settings())
    text_ = service.report(snap, b"s" * 32, frozenset({"fidelity"}), thresholds)
    line = next(ln for ln in text_.splitlines() if "fidelity" in ln.lower() and "%" in ln)
    assert re.search(r"\b100(\.0+)?\s*%", line), line

    # The window is half open on submit time, to the Madrid midnight: the daily of 6 October answered at 00:03
    # on the 7th is in the window that ends on the 8th and not in the one that ends on the 7th, though it is a daily
    # of the 6th; the daily closed at 03:00 on the 6th is not in the window that ends on the 6th.
    def plays_until(day: str) -> int:
        out = run(["integrity-report", "--until", day, "--checks", "fidelity", "--salt-stdin"], SALT + "\n")
        return int(re.search(r"n_plays: ([\d,]+)", out).group(1).replace(",", ""))  # type: ignore[union-attr]

    assert plays_until("2026-10-06") == 2
    assert plays_until("2026-10-08") - plays_until("2026-10-07") == 3  # the night daily and the 7th's two


def _options(db: Session, q: Question) -> list[int]:
    return list(
        db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == q.id).order_by("position"))
    )


# --- the AI canary and the signal context (ADR 0010 D) ---------------------------------------------------------------
# The planted world carries a decoy and totals on every attempt from planted.RULES_FROM on. What the report must
# say about each signal member is worked out by planted.reference(), a walk of the plan that shares no code with the
# report; the tests compare the two.

PSEUDONYM = re.compile(r"[0-9a-f]{8}")


def label(c: rules.Canary) -> str:
    """A decision as the report words it: `ignored (placebo off)`, `reject`, `no sign`, ..."""
    if c.decision.startswith("ignored") and "(" not in c.decision and c.note:
        return f"ignored ({c.note})"
    return c.decision


def canary_summary(db: Session, **settings: str) -> Any:
    snap = service.fetch(
        db, service.Window(planted.RULES_FROM, planted.UNTIL), frozenset({"canary"}), planted.RULES_FROM
    )
    db.rollback()
    summary = service.canary_summary(snap, service.thresholds(integrity_settings(**settings)))
    assert summary is not None
    return summary


def canary_text(out: str) -> str:
    return section(out, "ai canary")


def flagged_table(out: str) -> Table:
    return one([t for t in tables(canary_text(out)) if t.has("decided at")], "canary decisions")


def listing_table(out: str) -> Table:
    return one([t for t in tables(canary_text(out)) if t.has("unreported share")], "listing")


def controls_table(out: str) -> Table:
    return one([t for t in tables(canary_text(out)) if t.has("verdict")], "controls")


def tally(out: str, name: str) -> int:
    t = one([t for t in tables(canary_text(out)) if t.header[:2] == ["decoy attempts", "n"]], "tallies")
    (row,) = [r for r in t.rows if r[0] == name]
    return int(number(row[1]))


def hits_trials(record: dict[str, str]) -> tuple[int, int]:
    m = re.match(r"(\d+)/(\d+)", cell(record, "canary hits/trials"))
    assert m, record
    return int(m.group(1)), int(m.group(2))


def canary_report(*extra: str) -> str:
    return report("--checks", "canary,people", *extra)


def test_the_canary_decisions_match_an_independent_walk_of_the_planted_plan(
    world: World, db: Session
) -> None:
    summary = canary_summary(db)
    ref = planted.reference()
    ids = {world.ids[n]: n for n in planted.PLAYERS}
    decided = {ids[k]: c for k, c in summary.people.items()}
    assert set(decided) == {n for n in planted.PLAYERS if ref[n].decision is not None}, (
        "someone with copy-arm trials is decided, and only them: the forger sent none, the tab-switcher and Pete "
        "reloaded, the eighteen never copied"
    )
    for name, c in decided.items():
        trials, hits = ref[name].arms["copy"]
        assert (c.trials, c.hits) == (trials, hits), name
    # the follower and the late starter are rejected, at the trial the walk first crossed
    for name in ("canary_follower", "late_starter"):
        assert decided[name].decision == "reject", name
        assert decided[name].decided_at == ref[name].decided_at, name
    assert decided["canary_follower"].hits == decided["canary_follower"].trials, "she never misses"
    assert decided["late_starter"].trials > decided["late_starter"].hits > 0, (
        "she started late and missed first"
    )
    assert decided["late_starter"].decided_at > decided["canary_follower"].decided_at
    # the translator copied a lot and reads their translation: never a reject
    assert label(decided["translator"]).startswith("no sign") and decided["translator"].decision != "reject"
    # the poisoner is excluded by her own placebo and the pool still sees
    assert label(decided["poisoner"]) == "ignored (own placebo off)"
    assert summary.placebo_status == "ok" and summary.draw_status == "ok" and summary.reliable
    assert summary.excluded >= 2  # the poisoner and the forger, who is no copy-arm person but pushes the pool
    assert sorted(summary.flagged) == sorted([world.ids["canary_follower"], world.ids["late_starter"]])
    assert set(summary.listed) == {world.ids["poisoner"], world.ids["forger"]}
    assert not summary.exploratory and not summary.over_m


def test_the_trial_counts_follow_the_rules_of_a_trial(world: World, integrity_env: str, db: Session) -> None:
    """Cass: a long copy before every follow day, one with a hint (void), two where the decoy is the key (void),
    two on questions changed after her attempt (void, one of them acknowledged), one on a question changed before
    (counts), and one attempt that started a minute before the rule date's midnight (left out)."""
    summary = canary_summary(db)
    cass = summary.people[world.ids["canary_follower"]]
    plan = planted.signal_plan()
    follow = [m for (n, i), m in plan.moves.items() if n == "canary_follower" and i >= planted.RULES_INDEX]
    copy_days = [m for m in follow if (m.copies or 0) >= 1]
    assert len(copy_days) > cass.trials, "some of her copies are not trials"
    assert cass.trials == 15
    before = plan.changed["before"]
    facts = [f for f in planted.facts(plan) if f.player == "canary_follower" and f.trial and f.arm == "copy"]
    assert before in {f.day for f in facts}, "a change before the attempt leaves it a trial"
    assert plan.changed["after"] not in {f.day for f in facts}
    assert plan.changed["acked"] not in {f.day for f in facts}
    boundary = db.scalars(
        select(Attempt).where(
            Attempt.user_id == world.ids["canary_follower"],
            Attempt.day == planted.day_of(planted.BOUNDARY_DAY),
        )
    ).one()
    assert boundary.long_copies == 1 and boundary.decoy_option_id is not None and boundary.resumes == 0
    assert boundary.created_at < planted.madrid(planted.RULES_FROM, 0)
    assert cast(datetime, boundary.submitted_at) >= planted.madrid(planted.RULES_FROM, 0)
    assert boundary.answer["options"] == [boundary.decoy_option_id], "it would be a hit, if it counted"


def test_the_attempts_that_must_not_count_leave_the_context_too(
    world: World, integrity_env: str, db: Session
) -> None:
    """Cass's attempt that started a minute before the rule date's midnight carries signals (a page that sent them
    early) and is dropped: it is no trial and no part of her context. Lena's purged attempt carries nothing. The
    uncounted mock run has no signal at all, so it is none of the translator's context either."""
    mock_attempt = db.scalars(select(Attempt).where(Attempt.mode == "mock")).one()
    assert mock_attempt.resumes is None and mock_attempt.decoy_option_id is None
    boundary = db.scalars(
        select(Attempt).where(
            Attempt.user_id == world.ids["canary_follower"],
            Attempt.day == planted.day_of(planted.BOUNDARY_DAY),
        )
    ).one()
    snap = service.fetch(
        db,
        service.Window(planted.RULES_FROM, planted.UNTIL),
        frozenset({"follow", "upstream-key", "profile", "home-away", "canary", "people"}),
        planted.RULES_FROM,
    )
    db.rollback()
    assert snap.signals is not None
    assert boundary.id not in snap.signals.rows and mock_attempt.id not in snap.signals.rows
    found = {p.key: p for p in service.persons(snap, service.thresholds(integrity_settings()))}
    window = planted.DAYS - planted.RULES_INDEX
    for name, n in (("canary_follower", window), ("translator", window), ("late_starter", window - 1)):
        context = found[world.ids[name]].signals
        assert context is not None and context.n == n, name
    purged = [m for (who, _), m in planted.signal_plan().moves.items() if who == "late_starter" and m.purged]
    assert len(purged) == 1


def test_the_acknowledged_change_still_voids_the_attempts_of_that_question(
    world: World, integrity_env: str, db: Session
) -> None:
    after, acked, before = (db.get(Question, world.changed[k]) for k in ("after", "acked", "before"))
    assert after is not None and acked is not None and before is not None
    assert after.key_changed_at is not None and before.key_changed_at is not None
    assert acked.key_changed_at is None, "a reviewer's acknowledgement cleared the flag"
    snap = service.fetch(
        db, service.Window(planted.RULES_FROM, planted.UNTIL), frozenset({"canary"}), planted.RULES_FROM
    )
    db.rollback()
    assert snap.signals is not None
    changed = snap.signals.changed_after
    assert changed[acked.id] is not None, "the audit row of the acknowledgement stands in for the flag"
    assert changed[after.id] is not None
    when = changed[acked.id]
    assert when is not None and when > planted.madrid(
        planted.day_of(planted.signal_plan().changed["acked"]), 23
    )
    assert before.key_changed_at is not None
    assert before.key_changed_at < planted.madrid(planted.day_of(planted.signal_plan().changed["before"]), 0)

    out = canary_report()
    expected = len(
        [
            f
            for f in planted.facts()
            if f.day in (planted.signal_plan().changed["after"], planted.signal_plan().changed["acked"])
        ]
    )
    assert tally(out, "void: options changed") == expected >= 2 * (len(planted.ACTIVE) - 1)
    assert tally(out, "void: hint") == 1


def test_the_flagged_table_names_the_follower_and_the_late_starter_with_both_p_values(
    world: World, integrity_env: str
) -> None:
    out = canary_report()
    ref = planted.reference()
    table = flagged_table(out)
    found = {r[0]: r for r in table.rows}
    assert set(found) == pseudonyms(world, "canary_follower", "late_starter")
    for name in ("canary_follower", "late_starter"):
        row = found[pseudo(world.ids[name])]
        trials, hits = ref[name].arms["copy"]
        assert (int(number(table.get(row, "trials"))), int(number(table.get(row, "hits")))) == (trials, hits)
        assert int(number(table.get(row, "decided at"))) == ref[name].decided_at
        assert number(table.get(row, "expected")) > 0
        assert re.fullmatch(r"\d\.\d{4} \(-?\d+\.\d{2}\)", table.get(row, "fixed-window p")), row
        assert 0 < number(table.get(row, "anytime p")) <= 1
        assert PSEUDONYM.fullmatch(row[0])
    assert all(PSEUDONYM.fullmatch(r[0]) for r in listing_table(out).rows)
    assert "earlier stretch" not in out, "nobody's walk fell back below the boundary"


def test_the_people_table_has_the_canary_cell_and_the_context_columns(
    world: World, integrity_env: str
) -> None:
    out = canary_report()
    found = people(out)
    ref = planted.reference()
    for name in ("canary_follower", "late_starter"):
        record = found[pseudo(world.ids[name])]
        trials, hits = ref[name].arms["copy"]
        assert hits_trials(record) == (hits, trials), name
        assert "reject" in cell(record, "canary hits/trials")
        assert positive(cell(record, "provenance")) and not positive(cell(record, "performance"))
    # a person with no copy-arm trial has none to show
    assert cell(found[pseudo(world.ids["leader"])], "canary hits/trials").lower().startswith("no trials")
    assert not positive(cell(found[pseudo(world.ids["performer"])], "provenance"))


def test_a_canary_reject_alone_is_one_family_not_a_conversation(world: World, integrity_env: str) -> None:
    out = canary_report()
    for name in ("canary_follower", "late_starter"):
        record = people(out)[pseudo(world.ids[name])]
        fired = {f.strip() for f in re.split(r"[,;+/]", cell(record, "families").lower()) if f.strip()}
        assert fired == {"provenance"}, name
        assert positive(cell(record, "independent")) and not positive(cell(record, "conversation"))


def test_a_canary_reject_with_a_second_family_is_a_conversation(
    world: World, integrity_env: str, db: Session
) -> None:
    """Give Cass the timing family as well (she answers within seconds of opening): provenance and timing are two
    families, and provenance is independent of the other."""
    db.execute(
        update(Attempt)
        .where(Attempt.user_id == world.ids["canary_follower"], Attempt.mode == "daily")
        .values(submitted_at=Attempt.created_at + timedelta(seconds=3))
    )
    db.commit()
    record = people(canary_report())[pseudo(world.ids["canary_follower"])]
    fired = {f.strip() for f in re.split(r"[,;+/]", cell(record, "families").lower()) if f.strip()}
    assert fired == {"timing", "provenance"}
    assert positive(cell(record, "conversation")) and positive(cell(record, "independent"))
    assert "reject" in cell(record, "canary hits/trials")


def test_maxed_context_is_never_a_family_and_never_a_second_one(world: World, integrity_env: str) -> None:
    """Pete is right on every hard question (a performance flag) and is away for minutes on every answer and
    reopens every question: the context columns are full and still it is one family, so no conversation. Tom,
    the heavy tab-switcher with nothing else, appears in no table at all."""
    out = canary_report()
    pete = people(out)[pseudo(world.ids["performer"])]
    assert cell(pete, "families").lower() == "performance"
    assert not positive(cell(pete, "conversation")) and not positive(cell(pete, "independent"))
    assert re.match(r"(\d+)/\1/\1\b", cell(pete, "undeclared away")), "every answer is over the threshold"
    assert re.match(r"(\d+)/\1\b", cell(pete, "resumes attempts/n")), "every attempt was reopened"
    assert pseudo(world.ids["tab_switcher"]) not in out, "a lot of away time is not a flag"
    assert pseudo(world.ids["translator"]) not in out, "nor is a lot of copying that does not follow the note"
    assert set(people(out)) == pseudonyms(world, *planted.FLAGGED)


def test_the_cohort_table_shows_the_median_share_and_withholds_what_is_too_small(
    world: World, integrity_env: str
) -> None:
    out = canary_report()
    t = one([t for t in tables(out) if t.header[:2] == ["share", "people (n)"]], "signals across the cohort")
    rows = {r[0]: r for r in t.rows}
    over = rows["undeclared away over the threshold"]
    assert number(t.get(over, "p50")) > 0, "a quarter of the eighteen's days are over it"
    assert int(number(t.get(over, "people"))) >= 3
    pasted = rows["pasted (text answers)"]
    assert t.get(pasted, "p50") == "n/a" and t.get(pasted, "p90") == "n/a", "no text answer in this world"
    for r in t.rows:
        for column in ("p50", "p90"):
            v = t.get(r, column)
            assert v == "n/a" or (v.endswith("%") and int(v[:-1]) % 5 == 0), (r[0], v)
    assert "Caution" in out


def test_a_poisoner_and_a_forger_are_listed_never_flagged(
    world: World, integrity_env: str, db: Session
) -> None:
    out = canary_report()
    table = listing_table(out)
    found = {r[0]: r for r in table.rows}
    assert set(found) == pseudonyms(world, "poisoner", "forger")
    pia, omar = found[pseudo(world.ids["poisoner"])], found[pseudo(world.ids["forger"])]
    ref = planted.reference()
    for row, name in ((pia, "poisoner"), (omar, "forger")):
        trials = sum(t for a, (t, _) in ref[name].arms.items() if a != "copy")
        hits = sum(h for a, (_, h) in ref[name].arms.items() if a != "copy")
        assert (int(number(table.get(row, "trials"))), int(number(table.get(row, "hits")))) == (trials, hits)
        assert re.fullmatch(r"\d\.\d{4} \(-?\d+\.\d{2}\)", table.get(row, "fixed-window p")), row
    assert number(table.get(pia, "unreported share")) == 0
    assert number(table.get(pia, "reloaded share")) > 0, "her one decoy pick after a reload is walked too"
    assert number(table.get(omar, "unreported share")) > 0, "most of the forger's attempts sent no totals"
    people_found = people(out)
    assert (
        pseudo(world.ids["poisoner"]) not in people_found and pseudo(world.ids["forger"]) not in people_found
    )
    assert "never a family" in canary_text(out)
    assert not {pseudo(world.ids["poisoner"]), pseudo(world.ids["forger"])} & {
        r[0] for r in flagged_table(out).rows
    }


def test_the_forger_has_no_decision_and_the_poisoner_is_ignored(
    world: World, integrity_env: str, db: Session
) -> None:
    summary = canary_summary(db)
    assert world.ids["forger"] not in summary.people, "no attempt of his reported a long copy"
    assert label(summary.people[world.ids["poisoner"]]) == "ignored (own placebo off)"
    assert summary.unreported_share[world.ids["forger"]] > 0.4
    assert summary.unreported_share[world.ids["poisoner"]] == 0


def test_the_controls_are_printed_and_the_pool_keeps_the_poisoner(
    world: World, integrity_env: str, db: Session
) -> None:
    out = canary_report()
    t = controls_table(out)
    rows = {r[0]: r for r in t.rows}
    draw = next(r for k, r in rows.items() if k.startswith("draw check"))
    placebo = next(r for k, r in rows.items() if k.startswith("placebo"))
    assert t.get(draw, "verdict") == "near chance" and t.get(placebo, "verdict") == "near chance"
    people_in_pool, trials, hits = planted.placebo_pool()
    assert int(number(t.get(placebo, "trials"))) == trials, "everyone's placebo trials, the poisoner's too"
    assert int(number(t.get(placebo, "hits"))) == hits
    assert f"{people_in_pool} people" in placebo[0]
    assert canary_summary(db).excluded == 2, "the poisoner and the forger, by their own placebo"
    assert people_in_pool >= 3, "at least min_group people have a placebo"
    assert planted.placebo_power() >= 0.8, "the pool could see a follower at the configured strength"


def test_nothing_that_decides_the_canary_is_printed(
    world: World, integrity_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The settings are distinct here so that a value cannot be a count; their names may be printed, never their
    values or what follows from them (the boundary, p0 with the nudge, the away threshold)."""
    values = {
        "IFS_INTEGRITY_CANARY_ALPHA": "0.0437",
        "IFS_INTEGRITY_CANARY_BETA": "0.1873",
        "IFS_INTEGRITY_CANARY_FOLLOW": "0.4121",
        "IFS_INTEGRITY_CANARY_CONTROL_ALPHA": "0.0911",
        "IFS_INTEGRITY_CANARY_NUDGE": "0.0733",
        "IFS_INTEGRITY_CANARY_M": "23",
        "IFS_INTEGRITY_AWAY_UNDECLARED_S": "17",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    out = run([*BASE, "--checks", "all", "--split", "2026-09-30"], SALT + "\n")
    for name in ("0.0437", "0.1873", "0.4121", "0.0911", "0.0733"):
        assert name not in out, name
    boundary = math.log(23 / 0.0437)
    follow_p1 = 1 / 3 + 0.4121 * 2 / 3
    for derived in (
        f"{boundary:.2f}",
        f"{boundary:.3f}",
        f"{follow_p1:.3f}",
        f"{1 / 3 + 0.0733 * 2 / 3:.3f}",
    ):
        assert derived not in out, derived
    assert not re.search(r"\b(?:alpha|beta|nudge|follow|control)\s*=\s*\d", out, re.IGNORECASE)
    # names, never values: the variables may be named, in the sentence about M and in the ignored label
    assert not re.search(r"IFS_INTEGRITY_[A-Z_]+\s*=", out)
    lowered = out.lower()
    assert not re.search(r"decoy [a-z]\b|option [a-z]\b|decoy (id|option)\s*\d|option id", lowered)
    assert not [secret for secret in world.secrets() if secret in out]
    for name in planted.PROFILES:
        assert world.names[name] not in out and world.emails[name] not in out


def test_every_pseudonym_in_the_canary_section_is_a_pseudonym(world: World, integrity_env: str) -> None:
    out = canary_report()
    known = {pseudo(uid) for uid in world.ids.values()}
    found = set(re.findall(r"(?<![0-9a-f])[0-9a-f]{8}(?![0-9a-f])", canary_text(out)))
    assert found and found <= known


# --- when nothing is collected, and the window the per-person checks may read ------------------------------------------


def signal_columns() -> dict[str, None]:
    return {
        "away_declared_s": None,
        "away_undeclared_s": None,
        "pasted": None,
        "long_copies": None,
        "resumes": None,
        "decoy_option_id": None,
    }


def test_an_attempt_without_signals_prints_not_collected_in_every_signal_cell(
    world: World, integrity_env: str, db: Session
) -> None:
    """An old row, a purged one or one that carries nothing: the leader's totals are null, the others' are not."""
    db.execute(update(Attempt).where(Attempt.user_id == world.ids["leader"]).values(**signal_columns()))
    db.commit()
    out = canary_report()
    leader = people(out)[pseudo(world.ids["leader"])]
    for header in CONTEXT_HEADERS:
        assert cell(leader, header) == "not collected", header
    assert cell(leader, "canary hits/trials") == "not collected"
    other = people(out)[pseudo(world.ids["follower"])]
    assert "not collected" not in " ".join(other.values())
    assert cell(leader, "families").lower() == "provenance", "the other families stand"


def test_a_purged_season_prints_not_collected_and_has_no_decoys(
    world: World, integrity_env: str, db: Session
) -> None:
    """ADR 0006: a season's signals are nulled 90 days after it ends. The report reads what is there."""
    assert signals.purge(db, datetime(2027, 12, 15, tzinfo=UTC)) > 900, "every daily of the season"
    out = canary_report()
    assert "none in the window" in out
    found = people(out)
    assert set(found) >= pseudonyms(world, "leader", "follower"), "the other families stand"
    assert pseudo(world.ids["canary_follower"]) not in found, "nothing collected, nothing decided"
    for record in found.values():
        assert cell(record, "canary hits/trials") == "not collected"
        for header in CONTEXT_HEADERS:
            assert cell(record, header) == "not collected", header
    assert not [r for t in tables(canary_text(out)) if t.has("decided at") for r in t.rows]
    assert "reject" not in out
    # and only the old season goes: a season that ended less than 90 days ago keeps its totals
    assert signals.purge(db, datetime(2027, 11, 1, tzinfo=UTC)) == 0


def test_a_run_with_no_decoy_at_all_says_so_and_still_fills_the_context_columns(
    world: World, integrity_env: str, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IFS_CANARY is the pilot's switch for drawing a decoy; the report does not read it. With none drawn the
    section says `none in the window`, the context is there, and nothing is decided."""
    monkeypatch.setenv("IFS_CANARY", "false")
    with_flag = canary_report()
    monkeypatch.setenv("IFS_CANARY", "true")
    assert canary_report() == with_flag, "the report does not read IFS_CANARY"
    db.execute(update(Attempt).values(decoy_option_id=None))
    db.commit()
    out = canary_report()
    assert "none in the window" in out
    assert "decided at" not in canary_text(out) or not flagged_table(out).rows
    assert "reject" not in canary_text(out).replace("a reject is final", "")
    found = people(out)
    leader = found[pseudo(world.ids["leader"])]
    assert cell(leader, "canary hits/trials").lower().startswith("no trials")
    assert "not collected" not in cell(leader, "undeclared away")
    assert re.match(r"\d+/\d+/\d+", cell(leader, "undeclared away")), "the context is filled"
    assert pseudo(world.ids["canary_follower"]) not in found, "no decoy, no canary family"


def test_a_cohort_run_reads_no_signals_and_prints_no_signal_line(world: World, integrity_env: str) -> None:
    out = report()
    assert "signals:" not in out and "canary" not in headings(out)
    assert "ai canary" not in " ".join(headings(out))


def test_the_signals_line_of_a_per_person_run_names_the_rule_date(world: World, integrity_env: str) -> None:
    out = report("--checks", "canary")
    line = next(ln for ln in out.splitlines() if "signals:" in ln)
    assert planted.RULES_FROM.isoformat() in line and "IFS_RULES_1B_FROM" in line


def test_a_window_that_starts_after_the_walk_start_is_exploratory_and_says_nothing(
    world: World, integrity_env: str
) -> None:
    later = (planted.RULES_FROM + timedelta(days=6)).isoformat()
    out = canary_report("--since", later)
    text = canary_text(out)
    assert "exploratory" in text
    assert f"starts after the walk start {planted.RULES_FROM}" in text
    assert not [t for t in tables(text) if t.has("decided at") and t.rows], "no one is flagged"
    assert not [t for t in tables(text) if t.has("unreported share") and t.rows], "no one is listed"
    assert "reject" not in " ".join(c for t in tables(out) for r in t.rows for c in r)
    found = people(out)
    assert (
        pseudo(world.ids["canary_follower"]) not in found and pseudo(world.ids["late_starter"]) not in found
    )
    assert pseudo(world.ids["leader"]) in found, "the other families are read as before"
    assert pseudo(world.ids["poisoner"]) not in out and pseudo(world.ids["forger"]) not in out


def test_a_season_long_run_in_a_later_season_is_not_exploratory(
    world: World, integrity_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The walk starts at max(rule date, the season's 1 September): from 2027-28 on that is the season, so the
    default window of a run in that season is the walk."""
    freeze_today(monkeypatch, datetime(2027, 10, 15, 12, tzinfo=UTC))
    out = run(
        ["integrity-report", "--until", "2027-10-12", "--checks", "canary", "--salt-stdin"], SALT + "\n"
    )
    assert "window: [2027-09-01, 2027-10-12)" in out
    assert "exploratory" not in out
    explicit = run(
        [
            "integrity-report",
            "--until",
            "2027-10-12",
            "--since",
            "2027-09-01",
            "--checks",
            "canary",
            "--salt-stdin",
        ],
        SALT + "\n",
    )
    assert "exploratory" not in explicit and explicit == out
    later = run(
        [
            "integrity-report",
            "--until",
            "2027-10-12",
            "--since",
            "2027-09-02",
            "--checks",
            "canary",
            "--salt-stdin",
        ],
        SALT + "\n",
    )
    assert "exploratory" in later or "no trial" in later.lower() or "none in the window" in later


def test_more_players_than_m_ignores_every_decision(
    world: World, integrity_env: str, monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    monkeypatch.setenv("IFS_INTEGRITY_CANARY_M", "3")  # four people have copy-arm trials
    summary = canary_summary(db, canary_m="3")
    assert summary.over_m and not summary.reliable and summary.flagged == []
    assert {label(c) for c in summary.people.values()} == {
        "ignored (more players than IFS_INTEGRITY_CANARY_M)"
    }
    out = canary_report()
    assert not [r for t in tables(canary_text(out)) if t.has("decided at") for r in t.rows]
    assert pseudo(world.ids["canary_follower"]) not in people(out)
    assert "IFS_INTEGRITY_CANARY_M" in canary_text(out)
    assert not re.search(r"IFS_INTEGRITY_CANARY_M\s*[=:]?\s*3\b", out), "the value is not printed"
    monkeypatch.setenv("IFS_INTEGRITY_CANARY_M", "4")  # M people are within M
    assert not canary_summary(db, canary_m="4").over_m
    assert pseudo(world.ids["canary_follower"]) in people(canary_report())


def test_a_world_too_small_to_see_a_follower_decides_nothing(
    world: World, integrity_env: str, db: Session
) -> None:
    """Keep the follower, the late starter, the translator and one player who is almost never wrong: three people
    have a placebo, with a dozen trials between them, too few to have power against a follower, so every decision
    is ignored, the canary flags no one in this run and the section says so."""
    names = planted.SMALL_WORLD
    db.execute(delete(Attempt).where(Attempt.user_id.not_in([world.ids[n] for n in names])))
    db.commit()
    summary = canary_summary(db)
    assert summary.placebo_people >= 3, "enough people, not enough trials"
    assert summary.placebo_status == "too small" and not summary.reliable
    assert {label(c) for c in summary.people.values()} == {"ignored (controls too small)"}
    out = canary_report()
    assert not [r for t in tables(canary_text(out)) if t.has("decided at") for r in t.rows]
    assert pseudo(world.ids["canary_follower"]) not in people(out)
    assert "too small" in canary_text(out)


# --- the command's gates for the canary and the context ----------------------------------------------------------------

CANARY_VARIABLES = sorted(CANARY_ENV)


def refusal(monkeypatch: pytest.MonkeyPatch, *args: str) -> str:
    with pytest.raises(SystemExit) as e:
        run(["integrity-report", "--until", "2026-10-12", *args, "--salt-stdin"], SALT + "\n")
    return str(e.value.code)


@pytest.mark.parametrize(
    ("checks", "extra"), [("canary", []), ("people", []), ("split", ["--split", "2026-09-20"])]
)
def test_the_checks_that_read_the_canary_name_every_unset_setting_in_one_message(
    monkeypatch: pytest.MonkeyPatch, never_connect: None, checks: str, extra: list[str]
) -> None:
    set_integrity_env(monkeypatch, UNREACHABLE)
    monkeypatch.setenv("IFS_RULES_1B_FROM", planted.RULES_FROM.isoformat())
    message = refusal(monkeypatch, "--checks", checks, *extra)
    for name in CANARY_VARIABLES:
        assert name in message, name
    for name in ("IFS_INTEGRITY_MIN_N", "IFS_INTEGRITY_FOLLOW_Z", "IFS_INTEGRITY_DSN"):
        assert name not in message, name
    assert message.count("missing") == 1, "one message, not one per variable"


def test_only_the_unset_canary_settings_are_named(
    monkeypatch: pytest.MonkeyPatch, never_connect: None
) -> None:
    set_integrity_env(monkeypatch, UNREACHABLE)
    set_canary_env(monkeypatch)
    monkeypatch.delenv("IFS_INTEGRITY_CANARY_NUDGE")
    monkeypatch.delenv("IFS_INTEGRITY_AWAY_UNDECLARED_S")
    message = refusal(monkeypatch, "--checks", "people")
    assert "IFS_INTEGRITY_CANARY_NUDGE" in message and "IFS_INTEGRITY_AWAY_UNDECLARED_S" in message
    for name in set(CANARY_VARIABLES) - {"IFS_INTEGRITY_CANARY_NUDGE", "IFS_INTEGRITY_AWAY_UNDECLARED_S"}:
        assert name not in message, name


@pytest.mark.parametrize(
    "checks", ["cohort", "fidelity", "elo,labels", "follow", "upstream-key,profile,home-away"]
)
def test_the_other_checks_need_none_of_the_canary_settings(
    monkeypatch: pytest.MonkeyPatch, never_connect: None, checks: str
) -> None:
    """They get past every gate: the first thing they do is open the connection, which this test forbids."""
    set_integrity_env(monkeypatch, UNREACHABLE)
    monkeypatch.setenv("IFS_RULES_1B_FROM", planted.RULES_FROM.isoformat())
    with pytest.raises(AssertionError, match="opened a connection"):
        run(["integrity-report", "--until", "2026-10-12", "--checks", checks, "--salt-stdin"], SALT + "\n")


@pytest.mark.parametrize(
    ("over", "invalid"),
    [
        ({"IFS_INTEGRITY_CANARY_ALPHA": "0"}, "IFS_INTEGRITY_CANARY_ALPHA"),
        ({"IFS_INTEGRITY_CANARY_ALPHA": "1"}, "IFS_INTEGRITY_CANARY_ALPHA"),
        ({"IFS_INTEGRITY_CANARY_BETA": "-0.1"}, "IFS_INTEGRITY_CANARY_BETA"),
        ({"IFS_INTEGRITY_CANARY_ALPHA": "0.5", "IFS_INTEGRITY_CANARY_BETA": "0.5"}, "IFS_INTEGRITY_CANARY_"),
        ({"IFS_INTEGRITY_CANARY_FOLLOW": "1"}, "IFS_INTEGRITY_CANARY_FOLLOW"),
        ({"IFS_INTEGRITY_CANARY_CONTROL_ALPHA": "0.01"}, "IFS_INTEGRITY_CANARY_CONTROL_ALPHA"),  # below alpha
        ({"IFS_INTEGRITY_CANARY_NUDGE": "0.5"}, "IFS_INTEGRITY_CANARY_NUDGE"),  # not below follow
        ({"IFS_INTEGRITY_CANARY_NUDGE": "-0.1"}, "IFS_INTEGRITY_CANARY_NUDGE"),
        ({"IFS_INTEGRITY_CANARY_M": "0"}, "IFS_INTEGRITY_CANARY_M"),
        ({"IFS_INTEGRITY_CANARY_M": "2.5"}, "IFS_INTEGRITY_CANARY_M"),
        ({"IFS_INTEGRITY_AWAY_UNDECLARED_S": "-1"}, "IFS_INTEGRITY_AWAY_UNDECLARED_S"),
        ({"IFS_RULES_1B_FROM": "26/10/2026"}, "IFS_RULES_1B_FROM"),
    ],
)
def test_an_out_of_range_setting_is_invalid_and_named(
    monkeypatch: pytest.MonkeyPatch, never_connect: None, over: dict[str, str], invalid: str
) -> None:
    set_integrity_env(monkeypatch, UNREACHABLE)
    set_canary_env(monkeypatch)
    for name, value in over.items():
        monkeypatch.setenv(name, value)
    message = refusal(monkeypatch, "--checks", "canary")
    assert f"invalid {invalid}" in message or f", {invalid}" in message, message
    assert "IFS_INTEGRITY_IFS_" not in message, "the app's own variable is named without the prefix"
    assert "missing" not in message


def test_the_rule_date_is_the_one_switch_for_the_per_person_checks(
    monkeypatch: pytest.MonkeyPatch, never_connect: None
) -> None:
    set_integrity_env(monkeypatch, UNREACHABLE)
    set_canary_env(monkeypatch, rules_from=None)
    for checks in ("canary", "people", "follow", "upstream-key", "profile", "home-away", "split", "all"):
        extra = ["--split", "2026-09-20"] if checks in ("split", "all") else []
        assert "IFS_RULES_1B_FROM" in refusal(monkeypatch, "--checks", checks, *extra), checks
    monkeypatch.setenv("IFS_RULES_1B_FROM", "")
    assert "IFS_RULES_1B_FROM" in refusal(monkeypatch, "--checks", "canary"), "blank is unset"
    # the cohort checks run without it
    with pytest.raises(AssertionError, match="opened a connection"):
        run(["integrity-report", "--until", "2026-10-12", "--salt-stdin"], SALT + "\n")


def test_a_per_person_window_cannot_start_before_the_rule_date(
    monkeypatch: pytest.MonkeyPatch, never_connect: None
) -> None:
    set_integrity_env(monkeypatch, UNREACHABLE)
    set_canary_env(monkeypatch)
    before = (planted.RULES_FROM - timedelta(days=1)).isoformat()
    assert "rule date" in refusal(monkeypatch, "--checks", "canary", "--since", before)
    assert "rule date" in refusal(monkeypatch, "--checks", "follow", "--since", "2026-09-01")
    with pytest.raises(
        AssertionError, match="opened a connection"
    ):  # a cohort check may read the days before
        run(["integrity-report", "--until", "2026-10-12", "--since", before, "--salt-stdin"], SALT + "\n")
    with pytest.raises(AssertionError, match="opened a connection"):  # and on the date itself is fine
        run(
            [
                "integrity-report",
                "--until",
                "2026-10-12",
                "--since",
                planted.RULES_FROM.isoformat(),
                "--checks",
                "canary",
                "--salt-stdin",
            ],
            SALT + "\n",
        )
    monkeypatch.setenv("IFS_RULES_1B_FROM", "2026-10-12")  # a window with no day from the rule date in it
    assert "rule date" in refusal(monkeypatch, "--checks", "canary") or "No answers" in refusal(
        monkeypatch, "--checks", "canary"
    )


# --- the rule date's Madrid midnight, across the clock changes ---------------------------------------------------------


def lone_players(db: Session, stamps: list[datetime]) -> list[int]:
    """One player per stamp, each with one counted daily created at that instant and answered a minute later,
    carrying signals and a decoy. Returns the attempt ids."""
    ids = []
    for k, created in enumerate(stamps):
        user = User(
            email=f"dst{k}@plant.test",
            password_hash="x",
            display_name=f"Dee Esty {k}",
            vertical="Electronics",
            position="member",
            status="active",
        )
        q = Question(
            type="single-choice",
            text=f"Clock question {k}",
            area="elec",
            topic="ev",
            difficulty=2,
            answer_kind="choice-one",
            graded=True,
            playable=True,
            source_hash="clock",
        )
        db.add_all([user, q])
        db.flush()
        opts = []
        for p in range(4):
            o = AnswerOption(question_id=q.id, position=p, text=f"c{k}-o{p}")
            db.add(o)
            db.flush()
            opts.append(o.id)
        db.add(
            AnswerKey(
                question_id=q.id, key={"kind": "choice", "mode": "one", "options": [opts[0]]}, display="x"
            )
        )
        day = created.astimezone(planted.MADRID).date()
        if not db.get(DailyQuestion, (day, "elec")):
            db.add(
                DailyQuestion(day=day, area="elec", question_id=q.id, drawn_at=created - timedelta(hours=3))
            )
        a = Attempt(
            user_id=user.id,
            question_id=q.id,
            mode="daily",
            answer={"options": [opts[1]], "value": None, "unsure": False},
            correct=False,
            created_at=created,
            day=day,
            area="elec",
            deadline_at=created + timedelta(minutes=10),
            submitted_at=created + timedelta(minutes=1),
            late=False,
            passed=False,
            decoy_option_id=opts[1],
            resumes=0,
            long_copies=1,
            away_undeclared_s=0,
            away_declared_s=0,
        )
        db.add(a)
        db.flush()
        ids.append(a.id)
    db.commit()
    return ids


@pytest.mark.parametrize(
    ("rules_from", "midnight_utc"),
    [
        (
            date(2026, 10, 25),
            datetime(2026, 10, 24, 22, 0, tzinfo=UTC),
        ),  # clocks go back at 03:00: midnight is CEST
        (
            date(2027, 3, 28),
            datetime(2027, 3, 27, 23, 0, tzinfo=UTC),
        ),  # clocks go forward at 02:00: midnight is CET
        (date(2026, 10, 26), datetime(2026, 10, 25, 23, 0, tzinfo=UTC)),  # the planned rule date: CET already
    ],
)
def test_signals_start_at_the_madrid_midnight_of_the_rule_date_across_clock_changes(
    db: Session, rules_from: date, midnight_utc: datetime
) -> None:
    stamps = [
        midnight_utc
        - timedelta(minutes=1),  # the evening before: an attempt that ends after midnight is dropped
        midnight_utc,  # the very instant
        midnight_utc + timedelta(minutes=30),
        midnight_utc + timedelta(hours=1),  # wrong by an hour if the zone were fixed at the other offset
    ]
    ids = lone_players(db, stamps)
    snap = service.fetch(
        db, service.Window(rules_from, rules_from + timedelta(days=2)), frozenset({"canary"}), rules_from
    )
    db.rollback()
    assert snap.signals is not None
    assert set(snap.signals.rows) == set(ids[1:]), (
        "from the instant of Madrid midnight on, not a minute before"
    )


def test_a_pending_daily_is_left_out_of_the_canary_cohort_until_it_is_granted(db: Session) -> None:
    """From season 1b a daily's correctness is only revealed at the Madrid midnight, and the canary reads the
    decoy pick against it: a result still waiting is not part of the cohort, a granted one is."""
    rules_from = date(2026, 10, 25)
    midnight = datetime(2026, 10, 24, 22, 0, tzinfo=UTC)
    waiting, granted, old_release = lone_players(
        db, [midnight + timedelta(minutes=30), midnight + timedelta(hours=1), midnight + timedelta(hours=2)]
    )
    release = midnight + timedelta(hours=24)
    db.execute(update(Attempt).where(Attempt.id == waiting).values(released_at=release, settled_at=None))
    db.execute(
        update(Attempt)
        .where(Attempt.id == granted)
        .values(released_at=release, settled_at=release + timedelta(minutes=1))
    )
    db.commit()  # the third has neither column: what the previous release wrote
    window = service.Window(rules_from, rules_from + timedelta(days=2))
    snap = service.fetch(db, window, frozenset({"canary"}), rules_from)
    assert snap.signals is not None
    assert set(snap.signals.rows) == {granted, old_release}
    db.execute(update(Attempt).where(Attempt.id == waiting).values(settled_at=release + timedelta(minutes=2)))
    db.commit()
    snap = service.fetch(db, window, frozenset({"canary"}), rules_from)
    assert snap.signals is not None
    assert set(snap.signals.rows) == {waiting, granted, old_release}


def test_replay_of_a_daily_granted_at_day_close_follows_the_grant_not_the_answer(
    db: Session, integrity_env: str
) -> None:
    """From season 1b a daily is graded when answered and granted at the Madrid midnight. Answered first and
    wrong, then four wrong mock answers the same day, it is granted after them: it meets the bad run they built
    (the cushion), where in answer order it would have met none. The report walks the grant order, and leaves a
    result still waiting out of the replay."""
    gated = date(2020, 1, 1)
    user = User(
        email="gate@plant.test",
        password_hash="x",
        display_name="Gate Gus",
        vertical="Driverless",
        position="member",
    )
    db.add(user)
    only_elec, _ = make_question(db, "elec", "only-elec", 3)  # the daily draw has one question to pick
    mock_questions = [make_question(db, "mech", f"gate-mock{k}", 3) for k in range(4)]
    db.add(Quiz(id=9110, year=2026, vehicle_class="cv", held_on=date(2026, 3, 1), status="complete"))
    db.flush()
    for position, (q, _) in enumerate(mock_questions):
        db.add(QuizQuestion(quiz_id=9110, question_id=q.id, position=position))
    db.commit()

    # 5 October: a wrong daily at 09:01, waiting for midnight
    q, daily_attempt = daily.start(db, user, "elec", md(10, 5, 9), rules_from=gated)
    assert q.id == only_elec.id
    daily.answer(db, user, daily_attempt.id, [_options(db, q)[1]], None, md(10, 5, 9, 1))
    # then a counted mock run, all wrong: a bad run of four
    now = md(10, 5, 11)
    run_ = mock.start(db, user, 9110, now)
    state = mock.state(db, user, run_.id, now)
    for _ in mock_questions:
        assert state.current is not None
        mq, a = state.current
        ids = next(o for (m, o) in mock_questions if m.id == mq.id)
        now += timedelta(seconds=45)
        state = mock.answer(db, user, run_.id, a.id, [ids[1]], None, now)
    db.expire_all()
    waiting = db.get_one(Attempt, daily_attempt.id)
    assert waiting.released_at is not None and waiting.settled_at is None and waiting.lp == 0

    window = service.Window(date(2026, 9, 1), date(2026, 10, 12))
    before = service.ranked_plays(service.fetch(db, window, frozenset({"fidelity"})))[user.id]
    assert all(row.mode == "mock" for row, _ in before), "a result still waiting is not replayed"

    assert daily.settle_results(db, md(10, 6, 0, 30)) == (1, 0)  # the night's first page
    db.expire_all()
    attempts = db.scalars(
        select(Attempt).where(Attempt.user_id == user.id, Attempt.submitted_at.is_not(None))
    ).all()
    by_grant = sorted(attempts, key=lambda a: (a.settled_at or a.submitted_at, a.id))
    assert by_grant[-1].id == daily_attempt.id and by_grant[-1].settled_at == md(10, 6, 0, 30)
    stored = [a.lp for a in by_grant]
    assert all(x < 0 for x in stored)

    snap = service.fetch(db, window, frozenset({"fidelity"}))
    played = service.ranked_plays(snap)[user.id]
    assert [row.id for row, _ in played] == [a.id for a in by_grant], "the replay walks the grant order"
    assert [p.lp for _, p in played] == pytest.approx(stored, abs=1e-9)
    start = round(db.scalars(select(User.rank_points).where(User.id == user.id)).one() - sum(stored), 2)
    plays = [p for _, p in played]
    assert rules.replay_lp(plays, start) == pytest.approx(stored, abs=1e-9)
    in_answer_order = [p for _, p in sorted(played, key=lambda rp: (rp[0].submitted_at, rp[0].id))]
    assert rules.replay_lp(in_answer_order, start) != pytest.approx(
        [p.lp for p in in_answer_order], abs=1e-9
    ), "walked in answer order, the daily would not meet the bad run"
