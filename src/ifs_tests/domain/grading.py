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


NUMBER_HELP = "Type just a number, like 3.5 or 3,5: no units, % or other text."


def _list_help(counts: set[int]) -> str:
    many = f"{next(iter(counts))} numbers" if len(counts) == 1 else "the numbers"
    return f"Type {many} separated by semicolons, like 12.5; 40: no units or other text."


def _thousands(text: str) -> str:
    return f"Is {text} {text.replace(',', '.')} or {text.replace(',', '')}? Type the one you mean."


def unreadable(key: keys.Key | None, value: str | None) -> str | None:
    """Why a typed answer can't be graded, said the way the player should fix it; None when it can. An empty
    answer isn't unreadable: it's no answer, graded wrong (what a clock running out sends)."""
    text = keys.clean(value or "")
    if key is None or key["kind"] not in ("number", "numbers", "range") or not text:
        return None
    if key["kind"] == "numbers":
        counts = {len(a["values"]) for a in key["accept"]}
        for n in sorted(counts):
            parts = keys.split_values(text, n)
            if len(parts) >= 2 and all(keys.number(p) for p in parts):
                break
        else:
            return _list_help(counts)
        # The count is shown with the question when every accepted answer agrees on it; otherwise it's secret.
        if len(counts) == 1 and len(parts) not in counts:
            return _list_help(counts)
        return next((_thousands(p) for p in parts if keys.ambiguous(p)), None)
    if keys.number(text) is None:
        return NUMBER_HELP
    return _thousands(text.replace(" ", "")) if keys.ambiguous(text) else None


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
