"""First-pass topic tagging by keyword.

FS-Quiz has no topic field. This gives every question a best-guess area
and subtopic so the bank can be split between departments; it is a
starting point for human review (roadmap feat/4), not ground truth.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path
from typing import Any

AREAS = {
    "mech": ["dynamics", "aero", "structures", "powertrain"],
    "elec": ["hv", "dv", "electronics"],
    "rules": ["scoring"],
}

KEYWORDS = {
    "dynamics": r"tyre|tire|slip|cornering|lateral|yaw|understeer|oversteer|steer|weight transfer|roll\b|rolling|camber|toe|"
    r"suspension|spring|damper|wheelbase|track ?width|centre of gravity|center of gravity|\bcog\b|\bcg\b|grip|friction coefficient|\bμ",
    "aero": r"aero|downforce|drag|\bcd\b|\bcl\b|wing|diffuser|air density|lift coefficient",
    "structures": r"stress|strain|young|modulus|bending|torsion|buckling|beam|tube|frame|chassis|monocoque|impact attenuator|"
    r"weld|bolt|composite|laminate|carbon|material|yield|fatigue|moment of inertia|deflection|harness",
    "powertrain": r"gear|rpm|engine|fuel|intake|restrictor|exhaust|clutch|brake|drivetrain|differential|sprocket|chain|"
    r"cooling|radiator|heat|thermal|combustion|crank|wheel speed|drive shaft",
    "hv": r"accumulator|battery|batteries|\bcells?\b|tractive system|\bts\b|\bhv\b|high voltage|imd|insulation|isolation|\bams\b|\bbms\b|"
    r"precharge|pre-charge|discharge|tsal|\bair\b|\bairs\b|energy meter|kwh|\bah\b|state of charge|\bsoc\b|inverter|motor controller|"
    r"electric motor|\bkw\b|\bdc\b|fuse",
    "dv": r"driverless|autonomous|\bdv\b|\basms\b|\bebs\b|\bassi\b|\bres\b|remote emergency|mission|lidar|camera|slam|trackdrive|"
    r"\bas (off|ready|driving|finished|emergency)\b|autonomous system|inspection mission|\bdvs?\b",
    "electronics": r"resistor|capacitor|inductor|diode|transistor|mosfet|op-?amp|circuit|ohm|\bω\b|voltage|current|\bcan\b|bus\b|sensor|"
    r"low voltage|\blv\b|\bglv\b|shutdown circuit|\bsdc\b|relay|\bpwm\b|\badc\b|microcontroller|signal|wire|wiring|"
    r"connector|ground|\bbit\b|frequency|oscilloscope|bspd|apps|plausibility",
    "scoring": r"points?\b|score|penalt|\bdoo\b|\boc\b|cone|lap time|t_?max|t_?min|disqualif|\bdnf\b|endurance|efficiency|autocross|"
    r"skid ?pad|acceleration event|cost (report|event)|business plan|design event|registration|scrutineering|"
    r"rulebook|according to the rules|official|protest|team member|faculty advisor|event|ranking|results",
}

_PATTERNS = {t: re.compile(rf"\b(?:{p})", re.IGNORECASE) for t, p in KEYWORDS.items()}
_AREA_OF = {t: a for a, ts in AREAS.items() for t in ts}


def tag(question: dict[str, Any]) -> tuple[str, str, dict[str, int]]:
    text = " ".join([question["text"] or ""] + [a["text"] or "" for a in question["answers"]])
    hits = {t: len(p.findall(text)) for t, p in _PATTERNS.items()}
    hits = {t: n for t, n in hits.items() if n}
    if not hits:
        return "unclassified", "", hits
    # Scoring words show up in most questions ("points", "event"); only let them
    # win when nothing technical matches as strongly.
    technical = {t: n for t, n in hits.items() if t != "scoring"}
    if technical and max(technical.values()) >= hits.get("scoring", 0):
        best = max(technical, key=lambda t: technical[t])
    else:
        best = "scoring"
    return _AREA_OF[best], best, hits


def report(bank: dict[str, Any], csv_path: Path | None = None) -> str:
    rows = []
    for q in bank["questions"]:
        area, sub, hits = tag(q)
        rows.append((q["question_id"], area, sub, hits, q["text"]))
    if csv_path:
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["question_id", "area", "subtopic", "hits", "text"])
            for qid, area, sub, hits, text in rows:
                w.writerow([qid, area, sub, " ".join(f"{k}:{v}" for k, v in hits.items()), text[:200]])
    areas = Counter(r[1] for r in rows)
    subs = Counter((r[1], r[2]) for r in rows)
    total = len(rows)
    lines = [f"First-pass topic tags for {total} questions (keyword heuristic, needs review)"]
    for area in ["mech", "elec", "rules", "unclassified"]:
        lines.append(f"{area:<14}{areas[area]:>5}  {100 * areas[area] / total:5.1f}%")
        for (a, s), n in sorted(subs.items()):
            if a == area and s:
                lines.append(f"  {s:<12}{n:>5}")
    if csv_path:
        lines.append(f"per-question tags -> {csv_path}")
    return "\n".join(lines)
