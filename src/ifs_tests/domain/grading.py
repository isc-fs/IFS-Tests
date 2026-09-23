"""Grade one answer against a key from keys.py. Pure: no I/O, no clock."""

from __future__ import annotations

from typing import Any

from . import keys

RELATIVE = 0.001


def tolerance(n: dict[str, Any]) -> float:
    """Half a unit in the key's last decimal place, or 0.1 % of the value if that is larger:
    a key of 0.23 accepts 0.225 to 0.235, a key of 82.9 accepts ±0.08, a key of 64107 accepts ±64."""
    return max(0.5 * 10.0 ** -int(n["d"]), RELATIVE * abs(float(n["v"])))


def _close(given: float, expected: dict[str, Any]) -> bool:
    return abs(given - float(expected["v"])) <= tolerance(expected) + 1e-9


def _numbers(text: str, alternative: dict[str, Any]) -> bool:
    expected = alternative["values"]
    given = keys.numbers(text, len(expected))
    if given is None or len(given) != len(expected):
        return False
    values = [g["v"] for g in given]
    if not alternative["ordered"]:
        values, expected = sorted(values), sorted(expected, key=lambda e: float(e["v"]))
    return all(_close(v, e) for v, e in zip(values, expected, strict=True))


def grade(key: keys.Key | None, options: list[int] | None = None, value: str | None = None) -> bool | None:
    """True or False, or None when the question can't be graded (no key, or reveal-only)."""
    if key is None or key["kind"] == "self":
        return None
    if key["kind"] == "choice":
        chosen, correct = set(options or []), set(key["options"])
        if key["mode"] == "one":
            return len(chosen) == 1 and chosen <= correct
        return chosen == correct
    text = value or ""
    for alternative in key["accept"]:
        if key["kind"] == "number":
            n = keys.number(text)
            if n is not None and _close(n["v"], alternative):
                return True
        elif key["kind"] == "numbers":
            if _numbers(text, alternative):
                return True
        elif key["kind"] == "range":
            n = keys.number(text)
            if n is not None and alternative["lo"] - 1e-9 <= n["v"] <= alternative["hi"] + 1e-9:
                return True
        elif key["kind"] == "text" and keys.normal_text(text) == alternative:
            return True
    return False
