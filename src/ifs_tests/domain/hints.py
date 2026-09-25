"""Hints: a nudge generated from the answer key, never the answer itself. One per question, before answering;
it halves the XP (domain/xp.py). The seed makes a question's hint the same every time it is asked for."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .grading import tolerance
from .keys import Key


@dataclass(frozen=True)
class Hint:
    text: str
    removed_options: list[int] = field(default_factory=list)


def _fmt(x: float, up: bool) -> str:
    """Three significant figures, rounded away from the answer, written the way the answer field reads numbers:
    a decimal point, no thousands separators, no exponent."""
    if x == 0:
        return "0"
    exponent = math.floor(math.log10(abs(x))) - 2
    digits = (math.ceil if up else math.floor)(round(x / 10.0**exponent, 6))
    decimals = max(-exponent, 0)
    text = f"{digits * 10.0**exponent:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _between(lo: float, hi: float) -> str:
    return f"Between {_fmt(lo, up=False)} and {_fmt(hi, up=True)}."


def _around(v: float, rng: random.Random) -> tuple[float, float]:
    """A range holding `v` without being centred on it."""
    spread = max(abs(v), 1.0)
    return v - spread * rng.uniform(0.15, 0.35), v + spread * rng.uniform(0.15, 0.35)


def _too_tight(n: dict[str, float]) -> bool:
    """A range this narrow would sit inside the grading tolerance: every number in it would count as right. And
    zero would be everyone's guess in any range around it."""
    return n["v"] == 0 or max(abs(n["v"]), 1.0) * 0.15 <= tolerance(n)


def hint(key: Key | None, options: list[int], seed: int) -> Hint | None:
    """None when a hint can't help without giving the answer away: ungraded, too few options, several right
    options on a single choice, a number too small for a range, a one- or two-character text."""
    if not key or key["kind"] == "self":
        return None
    rng = random.Random(seed)
    if key["kind"] == "choice":
        right = set(key["options"])
        if key["mode"] == "all":
            return Hint(f"{len(right)} of the {len(options)} options are right.")
        wrong = [o for o in options if o not in right]
        if len(right) != 1 or len(wrong) < 2:
            return None
        removed = sorted(rng.sample(wrong, len(options) - 2))
        return Hint("Two options left: one of them is right.", removed)
    first = key["accept"][0]
    if key["kind"] == "number":
        if _too_tight(first):
            return None
        lo, hi = _around(first["v"], rng)
        return Hint(_between(lo, hi))
    if key["kind"] == "range":
        lo, _ = _around(first["lo"], rng)
        _, hi = _around(first["hi"], rng)
        return Hint(_between(lo, hi))
    if key["kind"] == "numbers":
        values = first["values"]
        return Hint(f"{len(values)} values; the first is {_fmt(values[0]['v'], up=False)}.")
    text = str(first)
    if len(text) <= 2:
        return None
    return Hint(f'{len(text)} characters, starting with "{text[0]}".')
