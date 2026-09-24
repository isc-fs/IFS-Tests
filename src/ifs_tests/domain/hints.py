"""Hints: a nudge generated from the answer key, never the answer itself. One per question, before answering;
it halves the XP (domain/xp.py). The seed makes a question's hint the same every time it is asked for."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .keys import Key


@dataclass(frozen=True)
class Hint:
    text: str
    removed_options: list[int] = field(default_factory=list)


def _fmt(x: float) -> str:
    s = f"{x:.3g}"
    return f"{x:,.0f}" if "e" in s else s


def _around(v: float, rng: random.Random) -> tuple[float, float]:
    """A range holding `v` without being centred on it."""
    spread = abs(v) or 1.0
    return v - spread * rng.uniform(0.15, 0.35), v + spread * rng.uniform(0.15, 0.35)


def hint(key: Key | None, options: list[int], seed: int) -> Hint | None:
    """None when there is nothing to give away safely (ungraded, or too few options)."""
    if not key or key["kind"] == "self":
        return None
    rng = random.Random(seed)
    if key["kind"] == "choice":
        right = set(key["options"])
        if key["mode"] == "all":
            return Hint(f"{len(right)} of the {len(options)} options are right.")
        wrong = [o for o in options if o not in right]
        if len(options) < 3 or not wrong:
            return None
        removed = sorted(rng.sample(wrong, len(options) - 2))
        return Hint("Two options left: one of them is right.", removed)
    first = key["accept"][0]
    if key["kind"] == "number":
        lo, hi = _around(first["v"], rng)
        return Hint(f"Between {_fmt(lo)} and {_fmt(hi)}.")
    if key["kind"] == "range":
        lo, _ = _around(first["lo"], rng)
        _, hi = _around(first["hi"], rng)
        return Hint(f"Between {_fmt(lo)} and {_fmt(hi)}.")
    if key["kind"] == "numbers":
        values = first["values"]
        return Hint(f"{len(values)} values; the first is {_fmt(values[0]['v'])}.")
    text = str(first)
    return Hint(f'{len(text)} characters, starting with "{text[0]}".')
