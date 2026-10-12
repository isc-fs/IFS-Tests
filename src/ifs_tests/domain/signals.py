"""Ranked-play signals (ADR 0010): what the page reports while a clock runs, clamped to what the attempt itself
allows, and the AI canary's decoy. Advisory and forgeable: nothing here decides anything."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .daily import GRACE, madrid_day
from .mock import season

KEEP = timedelta(days=90)  # after the season the attempt belongs to has ended (31 August)
RESUME_GRACE = timedelta(seconds=10)  # a page load this soon after the question was shown is the same visit
MAX_COUNT = 1_000  # long copies and reopenings are capped here (SmallInteger columns)
PASTE_KINDS = frozenset({"text"})  # a number pasted from a calculator is honest: not recorded
MIN_DECOY_OPTIONS = 3
COLUMNS = ("away_declared_s", "away_undeclared_s", "pasted", "long_copies", "resumes", "decoy_option_id")


@dataclass(frozen=True)
class Policy:
    collect: bool = False  # season 1b has started (IFS_RULES_1B_FROM set and reached, Madrid day)
    canary: bool = False  # IFS_CANARY on, and collect


OFF = Policy()


@dataclass(frozen=True)
class Signals:
    away_declared_s: float = 0
    away_undeclared_s: float = 0
    pasted: bool = False
    long_copies: int = 0


def elapsed_s(created_at: datetime, deadline_at: datetime, now: datetime) -> int:
    """Seconds the attempt could have been open: until the answer, or until the clock plus grace had run out."""
    return max(0, int((min(now, deadline_at + GRACE) - created_at).total_seconds()))


def stored(signals: Signals | None, elapsed: int, answer_kind: str) -> dict[str, Any]:
    """Column values to record with the answer; nothing when the client sent none (an older page)."""
    if signals is None:
        return {}
    declared = min(max(round(signals.away_declared_s), 0), elapsed)
    undeclared = min(max(round(signals.away_undeclared_s), 0), elapsed - declared)
    return {
        "away_declared_s": declared,
        "away_undeclared_s": undeclared,
        "pasted": signals.pasted if answer_kind in PASTE_KINDS else None,
        "long_copies": min(max(signals.long_copies, 0), MAX_COUNT),
    }


def is_resume(created_at: datetime, now: datetime) -> bool:
    return now - created_at >= RESUME_GRACE


def decoy(answer_kind: str, option_ids: Sequence[int], choice: Callable[[Sequence[int]], int]) -> int | None:
    """One of ALL the options offered, uniformly: the decoy says nothing about the answer. `choice` is injected
    so this module stays pure; the service passes secrets.choice."""
    if answer_kind != "choice-one" or len(option_ids) < MIN_DECOY_OPTIONS:
        return None
    return choice(list(option_ids))


def kept_from(now: datetime) -> int:
    """The first season whose signals are still kept: a season's go 90 days after it ends."""
    return season(madrid_day(now) - KEEP)
