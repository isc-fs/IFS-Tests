"""Answer keys: turn FS-Quiz's free-text correct answers into something the server can grade.

FS-Quiz stores every answer as text. Input answers mix decimal points and commas, lists separated by
"," or ";", ranges written "lo-hi", zero-width spaces and the odd garbled value. A comma followed by a space
always separates values ("118, 122"); a bare one between digits is a decimal comma ("64,107"). "a or b" gives
alternatives, any of which is right. A key is plain JSON:

    {"kind": "choice", "mode": "one" | "all", "options": [option ids]}
    {"kind": "number" | "numbers" | "range" | "text", "accept": [alternative, ...]}
    {"kind": "self"}      an official answer exists but can't be graded automatically: shown, not scored
                          (also a choice question with a single option: it can't be got wrong)

Numbers keep their decimals so a key of "82.9" accepts what rounds to it (see grading.py).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

Key = dict[str, Any]

_JUNK = {0x200B: None, 0x200C: None, 0x200D: None, 0xFEFF: None, 0xA0: " ", 0x202F: " ", 0x2009: " "}
_DASHES = {0x2212: "-", 0x2013: "-", 0x2014: "-"}
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:[.,](\d+))?|\.(\d+))(?:e([+-]?\d+))?$", re.IGNORECASE)
_THOUSANDS = re.compile(r"^[+-]?[1-9]\d{0,2},\d{3}$")
_RANGE = re.compile(r"^([+-]?\d+(?:[.,]\d+)?)\s*-\s*([+-]?\d+(?:[.,]\d+)?)$")
_SEQUENCE = re.compile(r"^\d+(?:-\d+){2,}$")
_OR = re.compile(r"\sor\s", re.IGNORECASE)  # no quantifiers: linear on long runs of spaces
# A question that asks for three decimals, or for a decimal comma, settles "59,988": FS-Quiz writes such keys so.
_DECIMAL_COMMA = re.compile(
    r"\b(?:three|3)\s+decimal|\bdecimal\s+comma|\bcommas?\s+instead\s+of\s+(?:dots?|points?)", re.IGNORECASE
)
_UNIT = re.compile(r"^[+-]?(?:\d+(?:[.,]\d+)?|\.\d+)\s*(?:[^\W\d_]|[%°])")  # 12.5 kW, 46%, 3.8 to 3.9
MAX_TEXT = 24


def clean(text: str) -> str:
    return unicodedata.normalize("NFKC", text.translate(_JUNK).translate(_DASHES)).strip()


def number(text: str) -> dict[str, Any] | None:
    """'82,9' -> {'v': 82.9, 'd': 1}: the value and how many decimals it was given with. Also '.23' and
    '2.3e-1'."""
    text = clean(text)
    if re.search(r",\s", text):
        return None
    text = text.replace(" ", "")
    m = _NUMBER.match(text)
    if not m:
        return None
    decimals = len(m.group(1) or m.group(2) or "") - int(m.group(3) or 0)
    return {"v": float(text.replace(",", ".")), "d": max(decimals, 0)}


def ambiguous(text: str) -> bool:
    """'64,107': a decimal comma or a thousands separator? Only a player's answer is asked; keys are read with
    a decimal comma, as FS-Quiz writes them."""
    return bool(_THOUSANDS.match(clean(text).replace(" ", "")))


def decimal_comma(question: str) -> bool:
    """The question asks for three decimals or a decimal comma, so a player's '59,988' can only mean 59.988.
    Read from the question's text, which players see: it says nothing about the key."""
    return bool(_DECIMAL_COMMA.search(question))


def split_values(text: str, expected: int | None = None) -> list[str]:
    """Split a list of numbers. ';' wins, then ', ' or spaces; a bare ',' only splits when it can't be a
    decimal comma: several of them, points elsewhere, or more than one value expected."""
    text = clean(text)
    if ";" in text:
        parts = text.split(";")
    elif re.search(r"\s", text):
        parts = re.split(r"\s*,\s+|\s+", text)
    elif "," in text and ("." in text or text.count(",") > 1 or (expected or 1) > 1):
        parts = text.split(",")
    elif _SEQUENCE.match(text):
        parts = text.split("-")
    else:
        parts = [text]
    return [p.strip() for p in parts if p.strip()]


def numbers(text: str, expected: int | None = None) -> list[dict[str, Any]] | None:
    parts = [number(p) for p in split_values(text, expected)]
    if len(parts) < 2 or any(p is None for p in parts):
        return None
    return [p for p in parts if p is not None]


def range_ends(text: str) -> tuple[str, str] | None:
    m = _RANGE.match(clean(text).replace(" ", ""))
    return (m.group(1), m.group(2)) if m else None


def value_range(text: str) -> dict[str, float] | None:
    ends = range_ends(text)
    if not ends:
        return None
    lo, hi = (float(x.replace(",", ".")) for x in ends)
    return {"lo": min(lo, hi), "hi": max(lo, hi)}


def alternatives(text: str) -> list[str]:
    """'118 or 122' -> ['118', '122']: answers any of which is right."""
    return [t.strip() for t in _OR.split(text or "")]


def normal_text(text: str) -> str:
    return re.sub(r"\s+", "", clean(text).casefold())


def _alternative(qtype: str, text: str) -> tuple[str, Any] | None:
    if qtype == "input-range" or (
        value_range(text) and not number(text) and not _SEQUENCE.match(clean(text))
    ):
        r = value_range(text)
        return ("range", r) if r else None
    if n := number(text):
        return "number", n
    if ns := numbers(text):
        # Three or more ascending whole numbers read as a "which of these" set, where order doesn't matter. A pair
        # answers two things in the order the question asks ("1, 7": days for one deadline, then the other).
        whole = all(x["d"] == 0 for x in ns)
        ascending = all(a["v"] < b["v"] for a, b in zip(ns, ns[1:], strict=False))
        return "numbers", {"values": ns, "ordered": not (whole and ascending and len(ns) >= 3)}
    short = clean(text)
    # A number with a unit isn't a code: players typing the number would be marked wrong.
    if 0 < len(short) <= MAX_TEXT and "," not in short and not _UNIT.match(short):
        return "text", normal_text(short)
    return None


def build_key(qtype: str, answers: list[dict[str, Any]], option_ids: list[int] | None = None) -> Key | None:
    """The key for one question, or None when FS-Quiz has no correct answer for it.

    `answers` are normalised FS-Quiz answers ({"text", "is_correct"}); `option_ids` are our IDs for them,
    in the same order (only needed for choice questions)."""
    correct = [i for i, a in enumerate(answers) if a["is_correct"]]
    if not correct:
        return None
    if qtype in ("single-choice", "multi-choice"):
        if len(answers) < 2:
            return {"kind": "self"}
        ids = option_ids if option_ids is not None else list(range(len(answers)))
        return {
            "kind": "choice",
            "mode": "one" if qtype == "single-choice" else "all",
            "options": [ids[i] for i in correct],
        }
    if qtype in ("input", "input-range"):
        texts = [t for i in correct for t in alternatives(answers[i]["text"])]
        read = [_alternative(qtype, t) for t in texts]
        kinds = {a[0] for a in read if a}
        if None not in read and len(kinds) == 1:
            return {"kind": kinds.pop(), "accept": [a[1] for a in read if a]}
    return {"kind": "self"}


def answer_kind(qtype: str, key: Key | None) -> str:
    """How the answer is entered, shown to players before they answer (so it must not reveal the key)."""
    if qtype == "single-choice":
        return "choice-one"
    if qtype == "multi-choice":
        return "choice-many"
    if key is None or key["kind"] == "self":
        return "self"
    return str(key["kind"])


def display(qtype: str, answers: list[dict[str, Any]]) -> str | None:
    """The official answer as people should read it."""
    correct = [clean(a["text"] or "") for a in answers if a["is_correct"]]
    if not correct:
        return None
    return "\n".join(correct) if qtype in ("single-choice", "multi-choice") else " or ".join(correct)
