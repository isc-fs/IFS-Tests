"""Live quiz rules (ADR 0005): join codes, sub-department tables, which table answers which question, speed
points. Pure: no I/O."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# No look-alikes (0/O, 1/I/L), so a code read off a projector is typed right first time.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
EVERYONE_ELSE = "Everyone else"

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
    level: int


@dataclass
class Table:
    name: str
    member_ids: list[int]
    captain_id: int | None
    topics: list[str] = field(default_factory=list)


def seat_by_subdepartment(players: list[Player]) -> list[Table]:
    """One table per sub-department present, from each player's first one; the rest at one table. The captain
    is the member with the highest level. Never balanced: tables are specialists (ADR 0005)."""
    groups: dict[str, list[Player]] = {}
    for p in players:
        code = next((c for c in p.subdepartments if c in SUBDEPARTMENTS), "")
        groups.setdefault(code, []).append(p)
    tables = []
    for code in sorted(groups, key=lambda c: (c == "", c)):
        members = groups[code]
        captain = max(members, key=lambda p: (p.level, -p.user_id))
        name, _, topics = SUBDEPARTMENTS[code] if code else (EVERYONE_ELSE, "", ())
        tables.append(Table(name, [p.user_id for p in members], captain.user_id, list(topics)))
    return tables


def owner(topic: str | None, tables: list[tuple[int, list[str]]], catch_all: int | None) -> int | None:
    """The table that answers a question on `topic`: the first that owns it, else the catch-all table."""
    return next((tid for tid, topics in tables if topic and topic in topics), catch_all)


def speed_points(correct: bool | None, elapsed_s: float, budget_s: int | None) -> int:
    """Kahoot-style: 1000 for an instant right answer, down to 500 at the buzzer; nothing when wrong."""
    if not correct:
        return 0
    if not budget_s:
        return 1000
    return round(1000 * (1 - min(max(elapsed_s / budget_s, 0.0), 1.0) / 2))
