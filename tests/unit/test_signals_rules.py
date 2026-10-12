from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from ifs_tests.domain import signals as rules
from ifs_tests.domain.daily import GRACE
from ifs_tests.domain.signals import OFF, Policy, Signals

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
MADRID = ZoneInfo("Europe/Madrid")


def madrid(day: date, hour: int = 0, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), MADRID).astimezone(UTC)


def test_the_constants_are_the_ones_the_notice_and_the_docs_state() -> None:
    assert timedelta(days=90) == rules.KEEP
    assert timedelta(seconds=10) == rules.RESUME_GRACE
    assert rules.MAX_COUNT == 1_000
    assert rules.MIN_DECOY_OPTIONS == 3
    assert frozenset({"text"}) == rules.PASTE_KINDS
    assert rules.COLUMNS == (
        "away_declared_s",
        "away_undeclared_s",
        "pasted",
        "long_copies",
        "resumes",
        "decoy_option_id",
    )


def test_nothing_is_collected_by_default() -> None:
    assert (OFF.collect, OFF.canary) == (False, False)
    assert Policy() == OFF
    with pytest.raises(dataclasses.FrozenInstanceError):
        OFF.collect = True  # type: ignore[misc]


def test_a_policy_is_a_value() -> None:
    assert Policy(collect=True, canary=True) == Policy(True, True)
    assert Policy(collect=True) != Policy(collect=True, canary=True)


def sig(declared: float = 0, undeclared: float = 0, pasted: bool = False, copies: int = 0) -> Signals:
    return Signals(away_declared_s=declared, away_undeclared_s=undeclared, pasted=pasted, long_copies=copies)


def kept(declared: Any, undeclared: Any, pasted: Any, copies: Any) -> dict[str, Any]:
    return {
        "away_declared_s": declared,
        "away_undeclared_s": undeclared,
        "pasted": pasted,
        "long_copies": copies,
    }


def test_an_older_page_sends_nothing_and_nothing_is_stored() -> None:
    assert rules.stored(None, 100, "text") == {}
    assert rules.stored(None, 0, "choice-one") == {}


@pytest.mark.parametrize(
    ("signals", "elapsed", "expected"),
    [
        (sig(10, 20), 100, kept(10, 20, None, 0)),
        (sig(150, 80), 100, kept(100, 0, None, 0)),  # declared first: it takes the whole attempt
        (sig(30, 90), 100, kept(30, 70, None, 0)),  # undeclared gets what declared left
        (sig(0, 500), 100, kept(0, 100, None, 0)),
        (sig(100, 100), 100, kept(100, 0, None, 0)),
        (sig(60, 40), 100, kept(60, 40, None, 0)),  # exactly the attempt: no clamp
        (sig(60, 41), 100, kept(60, 40, None, 0)),  # one second over
        (sig(10_000_000, 10_000_000), 183, kept(183, 0, None, 0)),  # a tab left open for months
        (sig(5, 5), 0, kept(0, 0, None, 0)),  # answered the instant it was shown
        (sig(12.4, 0), 100, kept(12, 0, None, 0)),
        (sig(12.6, 0), 100, kept(13, 0, None, 0)),
        (sig(12.5, 0), 100, kept(12, 0, None, 0)),  # rounded, then clamped
        (sig(0, 12.6), 100, kept(0, 13, None, 0)),
        (sig(99.6, 5), 100, kept(100, 0, None, 0)),  # rounds up past the attempt, clamps back
        (sig(-3, -7), 100, kept(0, 0, None, 0)),  # a negative is never kept, whatever sent it
        (sig(0, 0, False, -4), 100, kept(0, 0, None, 0)),
        (sig(0, 0, False, 5), 100, kept(0, 0, None, 5)),
        (sig(0, 0, False, 1_000), 100, kept(0, 0, None, 1_000)),
        (sig(0, 0, False, 1_001), 100, kept(0, 0, None, 1_000)),
        (sig(0, 0, False, 5_000), 100, kept(0, 0, None, 1_000)),
        (sig(0, 0, False, 100_000), 0, kept(0, 0, None, 1_000)),
    ],
)
def test_stored_clamps_what_the_page_reports_to_what_the_attempt_allows(
    signals: Signals, elapsed: int, expected: dict[str, Any]
) -> None:
    assert rules.stored(signals, elapsed, "choice-one") == expected


def test_stored_values_are_whole_seconds() -> None:
    out = rules.stored(sig(12.4, 33.3, True, 2), 100, "text")
    assert type(out["away_declared_s"]) is int and type(out["away_undeclared_s"]) is int
    assert (out["away_declared_s"], out["away_undeclared_s"]) == (12, 33)


@pytest.mark.parametrize(
    ("kind", "pasted", "expected"),
    [
        ("text", True, True),
        ("text", False, False),  # "did not paste" is a fact about a text answer
        ("number", True, None),
        ("numbers", True, None),
        ("range", True, None),
        ("choice-one", True, None),
        ("choice-many", True, None),
        ("number", False, None),  # and not recorded elsewhere: null is "not recorded", never "no"
        ("choice-one", False, None),
        ("self", True, None),
    ],
)
def test_a_paste_is_kept_only_for_free_text_answers(kind: str, pasted: bool, expected: bool | None) -> None:
    assert rules.stored(sig(pasted=pasted), 100, kind)["pasted"] is expected


def test_stored_knows_only_the_four_things_the_page_reports() -> None:
    out = rules.stored(sig(1, 2, True, 3), 100, "text")
    assert set(out) == {"away_declared_s", "away_undeclared_s", "pasted", "long_copies"}
    assert out == kept(1, 2, True, 3)


@pytest.mark.parametrize(
    ("now_offset", "expected"),
    [
        (0, 0),
        (1, 1),
        (30, 30),
        (60, 60),  # right on the deadline
        (62, 62),
        (63, 63),  # the end of the grace period
        (64, 63),
        (3 * 3600, 63),  # a stale tab answering hours late can't report hours away
        (-5, 0),  # a clock that ran backwards
    ],
)
def test_elapsed_is_until_the_answer_or_until_the_clock_and_its_grace_ran_out(
    now_offset: int, expected: int
) -> None:
    deadline = T0 + timedelta(seconds=60)
    assert rules.elapsed_s(T0, deadline, T0 + timedelta(seconds=now_offset)) == expected
    assert timedelta(seconds=3) == GRACE  # the same grace the daily and the mock clocks give


def test_elapsed_never_goes_negative() -> None:
    assert rules.elapsed_s(T0, T0 + timedelta(seconds=60), T0 - timedelta(hours=1)) == 0


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(0), False),
        (timedelta(milliseconds=200), False),  # the SPA's refetch right after the start
        (timedelta(seconds=9, milliseconds=999), False),
        (timedelta(seconds=10), True),
        (timedelta(seconds=10, microseconds=1), True),
        (timedelta(minutes=5), True),
        (timedelta(seconds=-5), False),
    ],
)
def test_a_page_load_ten_seconds_after_the_question_was_shown_is_a_reopening(
    age: timedelta, expected: bool
) -> None:
    assert rules.is_resume(T0, T0 + age) is expected


class Spy:
    def __init__(self, pick: int = 0) -> None:
        self.seen: list[list[int]] = []
        self.pick = pick

    def __call__(self, ids: Sequence[int]) -> int:
        self.seen.append(list(ids))
        return ids[self.pick]


@pytest.mark.parametrize("kind", ["choice-many", "number", "numbers", "range", "text", "self"])
def test_only_single_answer_choices_get_a_decoy(kind: str) -> None:
    spy = Spy()
    assert rules.decoy(kind, [11, 12, 13, 14], spy) is None
    assert spy.seen == []


@pytest.mark.parametrize("ids", [[], [5], [5, 6]])
def test_a_choice_needs_three_options_for_a_decoy(ids: list[int]) -> None:
    spy = Spy()
    assert rules.decoy("choice-one", ids, spy) is None
    assert spy.seen == []


@pytest.mark.parametrize("pick", [0, 1, 2, 3])
def test_the_decoy_is_whatever_the_draw_picks_from_all_the_options_in_order(pick: int) -> None:
    spy = Spy(pick)
    ids = [41, 7, 99, 3]  # not sorted: the order is the question's, not ours
    assert rules.decoy("choice-one", ids, spy) == ids[pick]
    assert spy.seen == [ids]


def test_three_options_are_enough() -> None:
    spy = Spy(2)
    assert rules.decoy("choice-one", (8, 9, 10), spy) == 10
    assert spy.seen == [[8, 9, 10]]


def test_the_decoy_takes_only_options_and_a_draw() -> None:
    """Nothing about the answer can reach the decoy: its signature has no place for a key."""
    import inspect

    assert list(inspect.signature(rules.decoy).parameters) == ["answer_kind", "option_ids", "choice"]


@pytest.mark.parametrize(
    ("now", "season"),
    [
        (madrid(date(2026, 11, 29), 23, 59), 2025),  # still inside the 90 days after 31 August 2026
        (madrid(date(2026, 11, 30)), 2026),  # 1 September + 90 days: the 2025 season goes
        (madrid(date(2026, 11, 30), 0, 1), 2026),
        (madrid(date(2027, 11, 29), 23, 59), 2026),
        (madrid(date(2027, 11, 30)), 2027),
        (madrid(date(2028, 11, 29), 23, 59), 2027),  # a leap year changes nothing: 30 + 31 + 29 days
        (madrid(date(2028, 11, 30)), 2028),
        (madrid(date(2026, 12, 25), 12), 2026),
        (madrid(date(2027, 3, 1), 12), 2026),
        (madrid(date(2027, 8, 31), 12), 2026),  # the next season has not even started
    ],
)
def test_the_first_season_whose_signals_are_still_kept(now: datetime, season: int) -> None:
    assert rules.kept_from(now) == season


def test_the_keep_runs_on_madrid_days_not_utc_ones() -> None:
    # 23:30 UTC on 29 November is already 00:30 on the 30th in Madrid (winter time).
    assert rules.kept_from(datetime(2026, 11, 29, 23, 30, tzinfo=UTC)) == 2026
    assert rules.kept_from(datetime(2026, 11, 29, 22, 59, tzinfo=UTC)) == 2025
    # And in the other direction, a UTC clock still on the 30th is the same Madrid day.
    assert rules.kept_from(datetime(2026, 11, 30, 22, 59, tzinfo=UTC)) == 2026
