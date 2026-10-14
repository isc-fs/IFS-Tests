"""How much of the bank the daily's option shuffle leaves in bank order, and which shuffled questions a person
should look at. Read-only; question text is public bank data and nothing here is about a player."""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from ..db.models import AnswerOption, Question, Solution
from ..domain import shuffle
from ..domain.daily import AREAS

# Letters are case-sensitive (a lowercase "a" is the article); a digit counts only next to a noun that names one.
SUSPECT = re.compile(
    r"\b[A-E]\b|(?<!\w)\([a-e]\)|(?i:\b(?:options?|answers?|choices?|statements?)\s+[1-5]\b)|"
    r"(?i:\b(?:above|below|previous|following|first|second|third|last|both|neither|none|all|only|correct|"
    r"incorrect|true|false)\b)"
)
STEM = 70
MIN_SHARE = 0.70
MIN_AREA_SHARE = 0.60


def _line(q: Question, reason: str | None, opts: list[AnswerOption], solutions: Sequence[str] = ()) -> str:
    stem = " ".join(q.text.split())
    head = (
        f"  #{q.id}"
        + (f" [{reason}]" if reason else "")
        + f" {stem[:STEM]}"
        + ("..." if len(stem) > STEM else "")
    )
    return "\n".join(
        [
            head,
            *(f"      - {' '.join(o.text.split())}" for o in opts),
            *(f"      solution: {_clip(' '.join(t.split()))}" for t in solutions),
        ]
    )


def _clip(text: str) -> str:
    return text if len(text) <= 2 * STEM else text[: 2 * STEM] + "..."


def _share(n: int, total: int) -> str:
    return f"{n} ({100 * n / total:.0f} %)" if total else "0"


def _bucket(n: int) -> str:
    return "0-1" if n < 2 else str(n) if n < 4 else "4+"


def _cap(n: int, limit: int) -> str:
    return f"  {n} in total" + (f", the first {limit} shown" if n > limit else "")


def report(db: DB, sample: int = 30, seed: int = 0) -> str:
    """The graded, playable choice questions of the daily's areas (the only ones it draws; a reviewer's pin counts
    as kept): counts per reason and per area, a seeded sample of kept and of
    shuffled ones, the shuffled ones with a letter-like token or a word that refers to other options, and the
    shuffled ones with images (a figure can print its own labels, which no text rule sees). Each list is capped
    at `sample` and says how many there are."""
    questions = db.scalars(
        select(Question)
        .where(
            Question.graded,
            Question.playable,
            Question.area.in_(AREAS),
            Question.answer_kind.in_(shuffle.SHUFFLED),
        )
        .order_by(Question.id)
    ).all()
    undrawn = db.scalar(
        select(func.count()).where(
            Question.graded,
            Question.playable,
            Question.area.notin_(AREAS),
            Question.answer_kind.in_(shuffle.SHUFFLED),
        )
    )
    ids = [q.id for q in questions]
    options: dict[int, list[AnswerOption]] = defaultdict(list)
    for o in db.scalars(
        select(AnswerOption)
        .where(AnswerOption.question_id.in_(ids))
        .order_by(AnswerOption.position, AnswerOption.id)
    ):
        options[o.question_id].append(o)
    solutions: dict[int, list[str]] = defaultdict(list)
    for qid, text in db.execute(
        select(Solution.question_id, Solution.text).where(Solution.question_id.in_(ids)).order_by(Solution.id)
    ):
        if text:
            solutions[qid].append(text)

    verdicts = {
        q.id: shuffle.keep_reason(
            [shuffle.Choice(o.id, o.text, o.retired) for o in options[q.id]],
            q.answer_kind,
            q.text,
            solutions[q.id],
            has_images=bool(q.images),
        )
        or ("pinned" if q.keep_order else None)
        for q in questions
    }
    total = len(questions)
    kept = [q for q in questions if verdicts[q.id]]
    shuffled = [q for q in questions if not verdicts[q.id]]
    counts = Counter(v for v in verdicts.values() if v)
    out = [
        f"Graded, playable choice questions the daily can draw (areas {', '.join(AREAS)}): {total}",
        f"  shuffled: {_share(len(shuffled), total)}",
    ]
    out.append(f"  kept in bank order: {_share(len(kept), total)}")
    out += [f"      {reason}: {n}" for reason, n in counts.most_common()]
    if undrawn:
        out.append(f"  not counted, outside the daily's areas: {undrawn}")
    out.append(f"  kept by ladder-sorted alone: {_share(counts['ladder-sorted'], total)}")
    out.append("  by area (shuffled of all):")
    shares = {}
    for area in sorted({q.area for q in questions}):
        of_area = [q for q in questions if q.area == area]
        n = sum(not verdicts[q.id] for q in of_area)
        shares[area] = n / len(of_area)
        out.append(f"      {area}: {n} of {len(of_area)} ({100 * shares[area]:.0f} %)")
    below = [a for a, share in shares.items() if share < MIN_AREA_SHARE]
    passed = total > 0 and len(shuffled) / total >= MIN_SHARE and not below
    out.append(
        f"  go/no-go (at least {MIN_SHARE:.0%} overall, no area under {MIN_AREA_SHARE:.0%}): "
        + ("pass" if passed else "FAIL" + (f", under: {', '.join(below)}" if below else ""))
    )

    other = db.scalar(
        select(func.count()).where(
            Question.graded,
            Question.playable,
            Question.area.in_(AREAS),
            Question.answer_kind.notin_(shuffle.SHUFFLED),
        )
    )
    every = total + (other or 0)
    out += [
        "",
        f"Coverage of all graded, playable questions the daily can draw (areas {', '.join(AREAS)}): {every}",
        f"  choice, shuffled: {_share(len(shuffled), every)}",
        f"  choice, kept in bank order: {_share(len(kept), every)}",
        f"  typed or other (never shuffled): {_share(other or 0, every)}",
    ]
    live = {q.id: sum(not o.retired for o in options[q.id]) for q in questions}
    out += ["", "By option count (shuffled of all choice questions):"]
    for label in ("0-1", "2", "3", "4+"):
        of_size = [q for q in questions if _bucket(live[q.id]) == label]
        if of_size or label != "0-1":
            n = sum(not verdicts[q.id] for q in of_size)
            out.append(
                f"  {label} options: {n} of {len(of_size)}"
                + (f" ({100 * n / len(of_size):.0f} %)" if of_size else "")
            )
    wide = [q for q in questions if live[q.id] >= 4]
    out.append(
        "  share of candidates with 4 or more options that are shuffled: "
        + _share(sum(not verdicts[q.id] for q in wide), len(wide))
        + " (information only)"
    )

    rng = random.Random(seed)
    for title, group in (("kept", kept), ("shuffled", shuffled)):
        picked = sorted(rng.sample(group, min(sample, len(group))), key=lambda q: q.id)
        out += ["", f"Sample of {len(picked)} {title} (seed {seed}):"]
        out += [_line(q, verdicts[q.id], options[q.id]) for q in picked]

    to_read = []
    for q in shuffled:
        texts = [q.text, *(o.text for o in options[q.id]), *solutions[q.id]]
        if any(SUSPECT.search(t) for t in texts):
            to_read.append(_line(q, None, options[q.id], [t for t in solutions[q.id] if SUSPECT.search(t)]))
    out += ["", "Shuffled, with a letter-like token or a word that may refer to other options:"]
    out += [_cap(len(to_read), sample), *to_read[:sample]]
    imaged = [q for q in shuffled if q.images]
    out += ["", "Shuffled, with images (check the figure for printed labels; pin with keep_order):"]
    out += [_cap(len(imaged), sample), *(f"  #{q.id}" for q in imaged[:sample])]
    return "\n".join(out) + "\n"
