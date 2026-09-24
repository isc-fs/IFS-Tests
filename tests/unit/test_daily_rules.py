from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from ifs_tests.domain.daily import Candidate, budget, is_late, madrid_day, pick, streak

D = date(2026, 10, 1)


@pytest.mark.parametrize(
    ("utc", "day"),
    [
        (datetime(2026, 9, 30, 21, 59, tzinfo=UTC), date(2026, 9, 30)),  # 23:59 in Madrid (CEST)
        (datetime(2026, 9, 30, 22, 0, tzinfo=UTC), date(2026, 10, 1)),  # midnight in Madrid
        (datetime(2026, 12, 31, 22, 59, tzinfo=UTC), date(2026, 12, 31)),  # CET: UTC+1
        (datetime(2026, 12, 31, 23, 0, tzinfo=UTC), date(2027, 1, 1)),
        (datetime(2026, 10, 25, 0, 30, tzinfo=UTC), date(2026, 10, 25)),  # the night clocks go back
    ],
)
def test_the_day_turns_at_midnight_in_madrid(utc: datetime, day: date) -> None:
    assert madrid_day(utc) == day


def test_pick_prefers_never_used_then_oldest_then_least_practised() -> None:
    fresh = Candidate(1, None, 5)
    old = Candidate(2, D - timedelta(days=300), 0)
    recent = Candidate(3, D - timedelta(days=2), 0)
    assert pick([recent, old, fresh], D, "mech") == 1
    assert pick([recent, old], D, "mech") == 2
    assert pick([Candidate(4, None, 3), Candidate(5, None, 1)], D, "mech") == 5
    assert pick([], D, "mech") is None


def test_pick_is_stable_for_a_day_and_varies_between_days() -> None:
    same = [Candidate(i, None, 0) for i in range(1, 50)]
    assert pick(same, D, "elec") == pick(list(reversed(same)), D, "elec")
    picks = {pick(same, D + timedelta(days=n), "elec") for n in range(10)}
    assert len(picks) > 1


def test_pick_is_drawn_with_a_secret_from_the_least_recently_used() -> None:
    bank = [Candidate(i, D - timedelta(days=400 - i), 0) for i in range(1, 201)]  # 1 is the oldest
    drawn = {pick(bank, D + timedelta(days=n), "rules", b"server secret") for n in range(60)}
    assert drawn <= set(range(1, 21)) and len(drawn) > 5  # among the 20 oldest, not always the oldest
    secrets = {pick(bank, D, "rules", bytes([n])) for n in range(20)}
    assert len(secrets) > 1  # without the secret, nobody can work tomorrow's out from the public bank


@pytest.mark.parametrize(
    ("time_s", "kind", "seconds"),
    [
        (180, "choice-one", 180),
        (None, "choice-one", 120),
        (None, "number", 240),
        (20, "number", 60),
        (1800, "text", 600),
    ],
)
def test_budget(time_s: int | None, kind: str, seconds: int) -> None:
    assert budget(time_s, kind) == seconds


def test_three_seconds_of_grace() -> None:
    deadline = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    assert not is_late(deadline + timedelta(seconds=3), deadline)
    assert is_late(deadline + timedelta(seconds=3, milliseconds=1), deadline)


def test_streak_counts_back_from_today_or_yesterday() -> None:
    days = {D, D - timedelta(days=1), D - timedelta(days=2), D - timedelta(days=4)}
    assert streak(days, D) == 3
    assert streak(days - {D}, D) == 2  # today not answered yet: yesterday's streak still stands
    assert streak(days, D + timedelta(days=2)) == 0
    assert streak(set(), D) == 0


def test_streak_freezes_save_a_missed_day_and_come_every_seven_days() -> None:
    from ifs_tests.domain.daily import freeze_earned, freeze_needed

    d = date(2026, 10, 10)
    days = {d - timedelta(days=i) for i in range(2, 9)}  # played the 7 days before yesterday
    assert freeze_needed(days, d - timedelta(days=1))
    assert not freeze_needed(days | {d - timedelta(days=1)}, d - timedelta(days=1))  # played it
    assert not freeze_needed(set(), d - timedelta(days=1))  # no streak to save
    week = {d - timedelta(days=i) for i in range(1, 8)}
    assert freeze_earned(week, week, d - timedelta(days=1))
    assert not freeze_earned(
        week, week - {d - timedelta(days=1)}, d - timedelta(days=1)
    )  # a freeze earns none
