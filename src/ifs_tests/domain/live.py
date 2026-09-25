"""Live quiz rules (ADR 0005): join codes, sub-department tables, which table answers which question, speed
points. Pure: no I/O."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

# No look-alikes (0/O, 1/I/L), so a code read off a projector is typed right first time.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
EVERYONE_ELSE = "Everyone else"
# A session nobody ended by then was abandoned: the nightly job finishes it and shares its XP.
ABANDONED_AFTER = timedelta(days=1)

# The Team Directory's departments in Notion, by vertical, and the question topics each answers best.
SUBDEPARTMENTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "AE": ("Aerodynamics", "Mechanical", ("aero",)),
    "BS": ("Braking and Steering", "Mechanical", ("dynamics",)),
    "CH": ("Chassis and Structural", "Mechanical", ("structures",)),
    "CM": ("Composites and Manufacturing", "Mechanical", ("structures",)),
    "SP": ("Suspension and Dynamics", "Mechanical", ("dynamics",)),
    "BT": ("Batteries", "Tractive System", ("hv",)),
    "MI": ("Motor Inverter", "Tractive System", ("hv", "powertrain")),
    "PT": ("Powertrain", "Tractive System", ("powertrain",)),
    "TR": ("Transmission", "Tractive System", ("powertrain",)),
    "CS": ("Cooling System", "Tractive System", ("powertrain",)),
    "CE": ("Control Electronics", "Electronics", ("electronics",)),
    "ES": ("Electronic Subsystems", "Electronics", ("electronics",)),
    "TE": ("Telemetry", "Electronics", ("electronics",)),
    "DV": ("Driverless", "Driverless", ("dv",)),
    "IN": ("Integration", "Driverless", ("dv",)),
    "PL": ("Pipeline", "Driverless", ("dv",)),
    "BU": ("Business Plan", "Management", ("scoring",)),
    "CO": ("Cost Report", "Management", ("scoring",)),
    "DE": ("Design", "Management", ("scoring",)),
    "TS": ("Testing", "Other", ("dynamics",)),  # its Notion colour matches no vertical: TDs to confirm
    "SPO": ("Sponsorship", "Business", ()),
    "MKT": ("Marketing", "Business", ()),
}


def new_code(rng: random.Random) -> str:
    return "".join(rng.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


@dataclass(frozen=True)
class Player:
    user_id: int
    subdepartments: tuple[str, ...]
    rank: float  # rank points: the best player at a table captains it


@dataclass
class Table:
    name: str
    member_ids: list[int]
    captain_id: int | None
    topics: list[str] = field(default_factory=list)


def seat_by_subdepartment(players: list[Player]) -> list[Table]:
    """One table per sub-department present, from each player's first one; the rest at one table. The captain
    is the member with the highest rank. Never balanced: tables are specialists (ADR 0005)."""
    groups: dict[str, list[Player]] = {}
    for p in players:
        code = next((c for c in p.subdepartments if c in SUBDEPARTMENTS), "")
        groups.setdefault(code, []).append(p)
    tables = []
    for code in sorted(groups, key=lambda c: (c == "", c)):
        members = groups[code]
        name, _, topics = SUBDEPARTMENTS[code] if code else (EVERYONE_ELSE, "", ())
        best = captain({p.user_id: p.rank for p in members})
        tables.append(Table(name, [p.user_id for p in members], best, list(topics)))
    return tables


def captain(ranks: dict[int, float]) -> int | None:
    """The member with the most rank points ({user_id: points}), the earlier one on a tie; nobody at an
    empty table."""
    return max(ranks, key=lambda uid: (ranks[uid], -uid), default=None)


def route(
    topics: Sequence[str | None], tables: Sequence[tuple[int, Sequence[str]]], catch_all: int | None
) -> list[int | None]:
    """The table that answers each question, in order: one that owns its topic, else the catch-all table. A
    topic several tables own goes to whichever of them has had the fewest questions so far (the earlier table on
    a tie), so every owner gets its share instead of the first one getting them all."""
    load = dict.fromkeys((tid for tid, _ in tables), 0)
    out: list[int | None] = []
    for topic in topics:
        owners = [tid for tid, owned in tables if topic and topic in owned]
        tid = min(owners, key=lambda t: load[t]) if owners else catch_all
        if tid in load:
            load[tid] += 1
        out.append(tid)
    return out


def reach(
    pool: Sequence[str | None],
    count: int,
    tables: Sequence[tuple[int, Sequence[str]]],
    catch_all: int | None,
    rng: random.Random,
    draws: int = 100,
) -> dict[int, float]:
    """How often each table gets at least one question, so the lobby can warn before the start: the routing
    rule run on draws of `count` topics from the pool the quiz picks from. When the pool is no bigger than
    `count` (a past quiz, in its order), every question is asked and one run says exactly who gets what."""
    runs = [list(pool)] if count >= len(pool) else [rng.sample(pool, count) for _ in range(draws)]
    hits = dict.fromkeys((tid for tid, _ in tables), 0)
    for topics in runs:
        for tid in set(route(topics, tables, catch_all)):
            if tid in hits:
                hits[tid] += 1
    return {tid: n / len(runs) for tid, n in hits.items()}


def speed_points(correct: bool | None, elapsed_s: float, budget_s: int | None) -> int:
    """Kahoot-style: 1000 for an instant right answer, down to 500 at the buzzer; nothing when wrong."""
    if not correct:
        return 0
    if not budget_s:
        return 1000
    return round(1000 * (1 - min(max(elapsed_s / budget_s, 0.0), 1.0) / 2))
