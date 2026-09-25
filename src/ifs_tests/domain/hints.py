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


def _window(n: dict[str, float], rng: random.Random) -> tuple[float, float] | None:
    """A range holding the answer 10-40 % in from one end, so neither end nor the middle is right: the range is
    at least twelve tolerances wide, which keeps the middle more than one tolerance away. None when it would be
    wider than 1.5 times the answer (a small whole number) or the answer is zero (everyone's guess)."""
    v, spread = n["v"], max(abs(n["v"]), 1.0)
    width = max(spread * rng.uniform(0.3, 0.7), 12 * tolerance(n))
    if v == 0 or width > 1.5 * spread:
        return None
    inside = rng.uniform(0.1, 0.4)
    if rng.random() < 0.5:
        inside = 1 - inside
    return v - inside * width, v + (1 - inside) * width


def _around_range(lo: float, hi: float, rng: random.Random) -> tuple[float, float]:
    """A range holding [lo, hi] with more room on one side than the range is wide, so its middle is outside."""
    spread = max(abs(lo), abs(hi), 1.0)
    near = spread * rng.uniform(0.1, 0.2)
    far = near + (hi - lo) + spread * rng.uniform(0.1, 0.3)
    if rng.random() < 0.5:
        near, far = far, near
    return lo - near, hi + far


def hint(key: Key | None, options: list[int], seed: int) -> Hint | None:
    """None when a hint can't help without giving the answer away: ungraded, too few options, several right
    options on a single choice, a number (or a list's first) too small for a range, zero, a one- or
    two-character text. A number's range is off-centre, so its middle isn't right."""
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
        window = _window(first, rng)
        return Hint(_between(*window)) if window else None
    if key["kind"] == "range":
        return Hint(_between(*_around_range(first["lo"], first["hi"], rng)))
    if key["kind"] == "numbers":
        values = first["values"]
        window = _window(values[0], rng)
        return Hint(f"{len(values)} values; the first is {_between(*window).lower()}") if window else None
    text = str(first)
    if len(text) <= 2:
        return None
    return Hint(f'{len(text)} characters, starting with "{text[0]}".')
