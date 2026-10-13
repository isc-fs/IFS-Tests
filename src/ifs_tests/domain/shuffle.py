"""Option order for the daily: a per-attempt shuffle that leaves alone every question whose options refer to
each other or to an order. Pure: the key comes from the caller."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

SHUFFLED = ("choice-one", "choice-many")
_NOUN = r"(?:answers?|options?|choices?|statements?|alternatives?)"
_AFTER = r"(?=\s*(?:$|[).,;:&–—-]|(?:and|or|is|are|only|because|since)\b))"
_ITEM = r"\(?(?:[A-E]|[1-5]|I{1,3}|IV|VI{0,3}|IX)\)?|\((?:[a-e]|i{1,3}|iv)\)"
_LEAD = r"(?:(?i:only|both|neither|either|statements?|options?|answers?|choices?)\s+)"
_ROMAN = r"(?:i{1,3}|iv|vi{0,3}|ix)"
_SEP = r"(?:,|and|&|or|nor|\+)"
# A lowercase enumerator is only a reference with a bracket: a lone "a" is the article.
_BRACKETED = r"(?<!\w)\((?:[a-e]|i{1,3}|iv)\)|(?<![\w(])[a-e]\)"

_ORD = r"(?:first|second|third|fourth|fifth|last|middle|previous|next|\d(?:st|nd|rd|th))"
_COUNT = r"(?:\s+(?:one|two|three|four))?"
# Bounded, so a long run of ordinals stays linear instead of quadratic.
_ORDS = rf"(?:the\s+)?{_ORD}{_COUNT}(?:\s*(?:,|and|or|&)\s*(?:the\s+)?{_ORD}{_COUNT}){{0,8}}"

_QUANTITY = r"(?i:exactly|at\s+(?:least|most)|up\s+to|about|approximately|around|roughly|nearly|(?:more|less|fewer|greater)\s+than)\b"
_TOKEN = re.compile(r"\(?(?:[A-Za-z]|(?i:ii|iii|iv|vi|vii|viii|ix))\)?")
_NUMBER = re.compile(r"\(?\d{1,2}\)?")
# With a picture, an option that is only a label ("B", "3", "iii", "Fig. 2") may match a label printed in the image.
_FIGURE_LABEL = re.compile(
    rf"^\(?(?:[A-Za-z]|\d|{_ROMAN})\)?$|^(?:fig(?:ure)?\.?|diagram|graph|curve|option|case)\s+\(?(?:[A-Za-z]|\d{{1,2}}|{_ROMAN})\)?$",
    re.I,
)
# A stem that talks about labels on the picture, or points at a part of it by label.
_FIGURE_STEM = re.compile(
    r"\b(?i:label(?:l)?ed|marked|lettered|numbered|shown\s+as)\b|\b(?i:point|curve)s?\s+\(?[A-Z\d]\)?(?!\w)"
)

# Each list says which text it is applied to.
_RELATIVE = [  # the casefolded, trimmed option text
    re.compile(p)
    for p in (
        r"\b(?:all|none|any|both|neither|either)\s+(?:of\s+)?(?:the\s+)?(?:above|below|these|those|them|following|listed|mentioned|previous|preceding|answers?|options?|choices?|statements?|others?|two|three|four)\b",
        r"^(?:none|all|both|neither)\s+of\s+(?:the\s+)?[a-z-]+$",
        r"\bno\s+(?:correct\s+)?(?:answers?|options?)\b",
        r"^(?:all|none|both|neither|either|other|others|nothing|n/?a|not applicable|it depends|(?:can't|cannot) be determined|not enough information|insufficient information|no correct answers?|no answer is correct|no change|the former|the latter|same as above|the (?:first|second|third|fourth|last)(?: one)?)$",
        r"^(?:all|none|neither|both|either)\s+(?:are|is)\b",
        r"^(?:all|none|neither|both)\s+(?:correct|incorrect|true|false|right|wrong|valid)\b",
        r"^(?:all|everything)\s+(?:except|but)\b",
        r"\b(?:first|second|third|fourth|fifth|last)\s+(?:(?:two|three|four)\s+|and\s+(?:the\s+)?(?:second|third|fourth|last)\s+)?(?:answers?|options?|choices?|statements?|ones?)\b",
        r"\b(?:answers?|options?|choices?|statements?)\s+(?:above|below)\b",
        r"\b(?:same as|as)\s+(?:above|before|the previous(?: one)?|the (?:first|second|last))\b",
        r"^only\s+(?:the\s+)?(?:first|second|third|fourth|last)\b",
        r"\b(?:previous|preceding|prior|next|above|below)\s+(?:statements?|answers?|options?|choices?)\b",
        r"^(?:the\s+)?following\s+(?:(?:two|three|four)\s+)?(?:statements?|answers?|options?|choices?)\b",
        r"^(?:the\s+)?(?:previous|preceding|prior|above)\s+(?:two|three|four)\s+(?:statements?|answers?|options?|choices?)\b",
        rf"^(?!{_ORD}$)(?:(?:both|only|either|neither)\s+)?{_ORDS}$",
        r"^the\s+one\s+(?:above|below|before|after)$",
    )
]
_LABELLED = [  # the whitespace-collapsed option text: the letters are case-sensitive on purpose
    re.compile(p)
    for p in (
        rf"\b(?i:{_NOUN})\s*:?\s*\(?[A-E1-5]\)?{_AFTER}",
        r"^\(?[A-Ea-e1-5]\)\s|^[A-E1-5][.:]\s|^(?:[A-E]\s*[.):–—-]|[a-e]\s*[.)]|(?:i{1,3}|iv|I{1,3}|IV)\s*[.)])\s",
        rf"^(?:[A-Za-z]+\s+){{0,2}}\(?[A-E]\)?$|^(?!{_QUANTITY})(?:[A-Za-z]+\s+){{1,2}}\(?[1-5]\)?$|^\([1-5]\)$|^I{{1,3}}$|^IV$",
        rf"^{_LEAD}*(?:{_ITEM})(?:\s*{_SEP}\s*(?:{_ITEM}))+(?:\s+(?i:only|are\s+(?:correct|true|false|right|wrong|valid)|is\s+(?:correct|true)))?$",
        rf"^{_LEAD}(?:{_ITEM})(?:\s+(?i:only))?$|^(?:{_ITEM})\s+(?i:only)$",
        rf"^(?:(?i:both|neither|either|only)\s+)?[a-e](?:\s*{_SEP}\s*[a-e])+$",
        rf"^(?:(?i:both|neither|either|only)\s+)?{_ROMAN}(?:\s*{_SEP}\s*{_ROMAN})+$|^{_ROMAN}\s+only$",
        r"\b[A-E]\b(?:\s*(?:,|and|&|\+|/|or|nor)\s*\(?[A-E]\b\)?)+",
        r"\b[A-E]\s+(?:is|are)\s+(?i:correct|true|right|wrong|false|valid|the)\b",
        _BRACKETED,
        r"\b(?i:same as|equal to|identical to|except|but not|other than)\s+(?:\(?[A-E]\)?(?![\w])|\(?[1-5]\)?(?=\s*(?:$|[).,;:&]|(?:and|or)\b)))",
    )
]
_TEXTUAL = [  # the stem and each solution
    re.compile(p, re.M)
    for p in (
        rf"\b(?i:{_NOUN})\s*:?\s*\(?[A-E1-5]\)?{_AFTER}",
        r"\b(?i:options?|answers?|choices?|statements?)\s+[A-E]\s*[-–—]\s*[A-E]\b|\([A-E]\s*[-–—]\s*[A-E]\)",
        r"\([A-E]\)\s*(?:to|[-–—])\s*\([A-E]\)",
        r"\b(?i:first|second|third|fourth|last)\s+(?i:option|answer|choice|statement)\b",
        r"\b(?i:options?|answers?|choices?|statements?)\s+(?i:above)\b",
        r"\b(?i:stated|mentioned|listed|given|described)\s+(?i:above)\b",
        r"^\(?[A-E][.):]\s|^\([A-E]\)",
        r"\b[A-E]\s+(?:is|are)\s+(?i:correct|right|the)\b",
        rf"\b(?i:{_NOUN})\s+(?i:is|are)\s*:?\s*\(?[A-E1-5]\)?{_AFTER}",
        rf"\b(?i:{_NOUN})\s*:?\s*\(?[a-e]\)?(?=\s+(?:is|are)\b|\))",
        rf"\b(?i:correct)\s*:\s*\(?[A-E]\)?{_AFTER}",
        _BRACKETED,
        rf"\b(?i:correct|right|wrong|incorrect|true|false)\s+(?i:choices?|answers?|options?|ones?|statements?)\s+(?i:is|are)\s+(?i:(?:the\s+)?{_ORD})\b",
        rf"\b(?i:{_ORDS}\s+(?:is|are)\s+(?:correct|right|wrong|incorrect|true|false|valid))\b",
        r"\b(?i:choose|select|pick)\s+[a-e]\s*,\s*[a-e](?:\s*,\s*[a-e])*,?\s*(?i:or|and)\s+[a-e]\b",
    )
]
_BOUND = re.compile(
    r"^(?:[<>≤≥~≈±]\s*|(?:less than|more than|greater than|fewer than|under|over|above|below|at least|at most|up to|between|from|approximately|approx\.?|about|around)\s+)+"
)
_VALUE = re.compile(
    r"^(?:(?P<label>[a-z]+(?:\s[a-z]+)?)\s+)?[€$£]?(?P<n>[-−–+]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+){2,}|\d+(?:[.,]\d+)?(?:/\d+)?)|[½¼¾])"
)
_FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75}
_LADDERS = (
    ("low", ("medium", "moderate"), "high"),
    ("small", "medium", "large"),
    ("never", "rarely", ("sometimes", "occasionally"), "often", "always"),
    ("first", "second", "third", "fourth", "fifth"),
    (
        ("less", "lower", "decrease", "decreases"),
        ("same", "equal", "unchanged", "stays the same"),
        ("more", "higher", "increase", "increases"),
    ),
)


@dataclass(frozen=True)
class Choice:
    """One answer option as the shuffle sees it."""

    id: int
    text: str
    retired: bool = False


def _number(n: str) -> tuple[float, ...] | None:
    n = n.replace("−", "-").replace("–", "-")
    if n in _FRACTIONS:
        return (_FRACTIONS[n],)
    if re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", n):
        return (float(n.replace(",", "")),)
    try:
        if re.fullmatch(r"[-+]?\d+(?:\.\d+){2,}", n):
            return tuple(float(p) for p in n.split("."))
        if "/" in n:
            a, b = (float(p.replace(",", ".")) for p in n.split("/"))
            return (a / b,) if b else None
        return (float(n.replace(",", ".")),)
    except ValueError:
        return None


def _monotone(seq: Sequence[Any]) -> bool:
    return len(set(seq)) >= 2 and (list(seq) == sorted(seq) or list(seq) == sorted(seq, reverse=True))


def _numeric_ladder(texts: Sequence[str]) -> str | None:
    """'ladder-range' or 'ladder-sorted' when the options lead with monotone numbers, else None."""
    values, labels, bounded = [], set(), False
    for t in texts:
        stripped = _BOUND.sub("", t)
        bounded |= stripped != t
        m = _VALUE.match(stripped)
        v = _number(m["n"]) if m else None
        if m is None or v is None:
            return None
        values.append(v)
        labels.add(m["label"])
    if len(labels) != 1 or not _monotone(values):
        return None
    return "ladder-range" if bounded or labels != {None} else "ladder-sorted"


def _word_ladder(texts: Sequence[str]) -> bool:
    for ladder in _LADDERS:
        slots = {w: i for i, s in enumerate(ladder) for w in ((s,) if isinstance(s, str) else s)}
        if all(t in slots for t in texts) and _monotone([slots[t] for t in texts]):
            return True
    return False


def _bare_labels(texts: Sequence[str]) -> bool:
    """At least two options are a single letter, numeral or roman token once a leading word that two or more
    options share ("Fig.", "Graph", "Use") is dropped. A bare number alone is a value, not a label."""
    parts = [t.split() for t in texts]
    lead = Counter(p[0].casefold() for p in parts if len(p) == 2).most_common(1)
    word = lead[0][0] if lead and lead[0][1] >= 2 else None
    if word is not None and re.match(_QUANTITY, word):
        return False
    hits = 0
    for p in parts:
        if len(p) == 1:
            hits += _TOKEN.fullmatch(p[0]) is not None
        elif len(p) == 2 and p[0].casefold() == word:
            hits += (_TOKEN.fullmatch(p[1]) or _NUMBER.fullmatch(p[1])) is not None
    return hits >= 2


def _lettered(texts: Sequence[str]) -> bool:
    """At least two options start with different capital letters A-E and a space ("A Front wing", "B Rear wing").
    One letter alone is the article."""
    return len({m[1] for t in texts if (m := re.match(r"([A-E])\s+\S", t))}) >= 2


def keep_reason(
    choices: Sequence[Choice],
    answer_kind: str,
    stem: str = "",
    solutions: Sequence[str] = (),
    *,
    has_images: bool = False,
) -> str | None:
    """Why this question stays in bank order (a short code), or None when it is shuffled. Judged over every
    option, retired ones included, so retiring one can't flip the verdict. When unsure, keep: the cost is a lost
    shuffle, never a misleading question."""
    if answer_kind not in SHUFFLED or sum(not c.retired for c in choices) < 2:
        return "kind"
    if any(not c.text.strip() for c in choices):
        return "blank"
    raw = [" ".join(c.text.split()) for c in choices]
    norm = [t.casefold().strip(" .;:") for t in raw]
    if has_images and (
        sum(_FIGURE_LABEL.match(n) is not None for n in norm) >= 2 or _FIGURE_STEM.search(stem)
    ):
        return "figure"
    if any(p.search(n) for n in norm for p in _RELATIVE):
        return "relative"
    if any(p.search(t) for t in raw for p in _LABELLED) or _bare_labels(raw) or _lettered(raw):
        return "label"
    if set(norm) <= {"yes", "no", "true", "false"}:
        return "yes-no"
    if len(choices) >= 3:
        if (ladder := _numeric_ladder(norm)) is not None:
            return ladder
        if _word_ladder(norm):
            return "ladder-word"
    if any(p.search(stem) for p in _TEXTUAL):
        return "stem"
    if any(p.search(s) for s in solutions for p in _TEXTUAL):
        return "solution"
    return None


def order(
    choices: Sequence[Choice],
    key: bytes,
    answer_kind: str,
    stem: str = "",
    solutions: Sequence[str] = (),
    *,
    has_images: bool = False,
) -> list[int]:
    """Option ids in display order: as given (bank order) when kept, else sorted by HMAC(key, id). Each option
    sorts on its own hash, so dropping one leaves the others where they were."""
    if keep_reason(choices, answer_kind, stem, solutions, has_images=has_images):
        return [c.id for c in choices]
    return [
        c.id
        for c in sorted(choices, key=lambda c: hmac.new(key, str(c.id).encode(), hashlib.sha256).digest())
    ]
