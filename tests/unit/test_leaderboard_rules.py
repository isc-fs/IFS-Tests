from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from ifs_tests.domain.daily import GRACE, MADRID, MAX_BUDGET, madrid_day
from ifs_tests.domain.integrity import wilson
from ifs_tests.domain.leaderboard import (
    MIN_ANSWERED,
    Accuracy,
    Member,
    VerticalScore,
    accuracy,
    accuracy_cutoff,
    first_day,
    madrid_midnight,
    rank_among,
    ranks,
    vertical_board,
)


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        ([], []),
        ([5], [1]),
        ([30, 20, 10], [1, 2, 3]),
        ([30, 20, 20, 10], [1, 2, 2, 4]),
        ([7, 7, 7], [1, 1, 1]),
        ([9, 8, 8, 8, 2, 2], [1, 2, 2, 2, 5, 5]),
    ],
)
def test_competition_ranking_shares_ranks_and_skips_after_ties(
    points: list[int], expected: list[int]
) -> None:
    assert ranks(points) == expected


@pytest.mark.parametrize(
    ("points", "others", "expected"),
    [(10, [], 1), (10, [30, 20, 10, 5], 3), (20, [30, 20, 20], 2), (1, [30, 20], 3), (40, [30], 1)],
)
def test_rank_among_others(points: int, others: list[int], expected: int) -> None:
    assert rank_among(points, others) == expected


@pytest.mark.parametrize(
    ("period", "today", "first"),
    [
        ("season", date(2026, 10, 1), date(2026, 9, 1)),
        ("season", date(2026, 9, 1), date(2026, 9, 1)),
        ("season", date(2026, 8, 31), date(2025, 9, 1)),
        ("season", date(2027, 2, 14), date(2026, 9, 1)),
        ("week", date(2026, 10, 1), date(2026, 9, 25)),
        ("week", date(2026, 9, 3), date(2026, 8, 28)),  # a week can straddle two seasons
        ("week", date(2027, 1, 2), date(2026, 12, 27)),
    ],
)
def test_first_day_of_a_period(period: str, today: date, first: date) -> None:
    assert first_day(period, today) == first


@pytest.mark.parametrize(
    ("now", "period", "since"),
    [
        # 23:30 on 31 August in Madrid is still last season; 00:30 on 1 September is the new one.
        (datetime(2026, 8, 31, 21, 30, tzinfo=UTC), "season", datetime(2025, 8, 31, 22, 0, tzinfo=UTC)),
        (datetime(2026, 8, 31, 22, 30, tzinfo=UTC), "season", datetime(2026, 8, 31, 22, 0, tzinfo=UTC)),
        # Summer time (UTC+2) and winter time (UTC+1) midnights, either side of the clocks changing.
        (datetime(2026, 10, 25, 12, 0, tzinfo=UTC), "week", datetime(2026, 10, 18, 22, 0, tzinfo=UTC)),
        (datetime(2026, 10, 31, 12, 0, tzinfo=UTC), "week", datetime(2026, 10, 24, 22, 0, tzinfo=UTC)),
        (datetime(2026, 11, 1, 12, 0, tzinfo=UTC), "week", datetime(2026, 10, 25, 23, 0, tzinfo=UTC)),
        (datetime(2027, 3, 29, 12, 0, tzinfo=UTC), "week", datetime(2027, 3, 22, 23, 0, tzinfo=UTC)),
        (datetime(2027, 4, 3, 12, 0, tzinfo=UTC), "week", datetime(2027, 3, 27, 23, 0, tzinfo=UTC)),
        (datetime(2027, 4, 4, 12, 0, tzinfo=UTC), "week", datetime(2027, 3, 28, 22, 0, tzinfo=UTC)),
    ],
)
def test_periods_start_at_midnight_in_madrid(now: datetime, period: str, since: datetime) -> None:
    assert madrid_midnight(first_day(period, madrid_day(now))) == since


def m(vertical: str | None, points: float, played: bool = False) -> Member:
    return Member(vertical, points, played)


def test_vertical_board_averages_over_every_active_member() -> None:
    members = [
        m("Driverless", 30, True),
        m("Driverless", 0),
        m("Driverless", 10, True),
        m("Mechanical", 20, True),
        m("Mechanical", 20),
        m("Mechanical", 22, True),
        m("Mechanical", 0),
        m("Business", 100, True),  # only two members: too few to show
        m("Business", 100, True),
        m(None, 500, True),  # no vertical: counts for nobody
    ]
    assert vertical_board(members) == [
        VerticalScore("Mechanical", 4, 15.5, 0.5),
        VerticalScore("Driverless", 3, 13.3, 0.667),
    ]


@pytest.mark.parametrize(
    ("members", "expected"),
    [
        ([], []),
        ([m("Board", 5)] * 2, []),
        ([m("Board", 5)] * 3, [VerticalScore("Board", 3, 5.0, 0.0)]),
        ([m("Board", 0, True)] * 3, [VerticalScore("Board", 3, 0.0, 1.0)]),
    ],
)
def test_vertical_board_needs_three_members(members: list[Member], expected: list[VerticalScore]) -> None:
    assert vertical_board(members) == expected


def test_vertical_ties_go_to_participation_then_name() -> None:
    members = [m("Mechanical", 10)] * 3 + [m("Business", 10)] * 3 + [m("Board", 10, True)] * 3
    assert [r.vertical for r in vertical_board(members)] == ["Board", "Business", "Mechanical"]


def test_a_share_needs_five_answers() -> None:
    assert MIN_ANSWERED == 5


@pytest.mark.parametrize(
    ("right", "answered", "expected"),
    [
        (0, 0, Accuracy(0, None, None, None)),
        (4, 4, Accuracy(4, None, None, None)),  # one under the minimum, even a clean sheet
        (1, 3, Accuracy(3, None, None, None)),
        (0, 5, Accuracy(5, 0.0, 0.0, 0.435)),
        (3, 5, Accuracy(5, 0.6, 0.23, 0.883)),
        (5, 5, Accuracy(5, 1.0, 0.565, 1.0)),
        (5, 10, Accuracy(10, 0.5, 0.236, 0.764)),
        (7, 12, Accuracy(12, 0.583, 0.319, 0.807)),
        (25, 40, Accuracy(40, 0.625, 0.47, 0.758)),
        (62, 100, Accuracy(100, 0.62, 0.522, 0.71)),
    ],
)
def test_accuracy_shows_the_share_and_its_wilson_range_from_five_answers(
    right: int, answered: int, expected: Accuracy
) -> None:
    assert accuracy(right, answered, wilson(right, answered)) == expected


def test_the_range_is_widened_outwards_to_the_thousandth_and_brackets_the_share() -> None:

    def thousandth(x: float) -> bool:
        return abs(x * 1000 - round(x * 1000)) < 1e-9

    for n in range(MIN_ANSWERED, 61):
        for right in range(n + 1):
            low_exact, high_exact = wilson(right, n)
            got = accuracy(right, n, (low_exact, high_exact))
            assert (
                got.answered == n and got.share is not None and got.low is not None and got.high is not None
            )
            assert 0 <= got.low <= got.share <= got.high <= 1, (right, n)
            assert got.low <= low_exact + 1e-9 and got.high >= high_exact - 1e-9, (right, n)
            assert thousandth(got.low) and thousandth(got.high) and thousandth(got.share), (right, n)
            assert got.low > low_exact - 0.001 - 1e-9 and got.high < high_exact + 0.001 + 1e-9, (right, n)


@pytest.mark.parametrize(
    ("right", "answered", "share", "low", "high"),
    [
        (1999, 2000, 0.999, 0.997, 1.0),  # 0.9995 rounds to 1.0: only exact when every answer was right
        (1, 2000, 0.001, 0.0, 0.003),  # 0.0005 rounds to 0.0: only exact when none was
        (9996, 10000, 0.999, 0.998, 1.0),
        (4, 10000, 0.001, 0.0, 0.002),
        (199, 200, 0.995, 0.972, 1.0),
        (1, 200, 0.005, 0.0, 0.028),
        (0, 2000, 0.0, 0.0, 0.002),
        (2000, 2000, 1.0, 0.998, 1.0),
    ],
)
def test_the_share_is_100_or_0_percent_only_when_it_is_exact(
    right: int, answered: int, share: float, low: float, high: float
) -> None:
    got = accuracy(right, answered, wilson(right, answered))
    assert got == Accuracy(answered, share, low, high)
    assert (got.share == 1.0) == (right == answered) and (got.share == 0.0) == (right == 0)


@pytest.mark.parametrize("answered", [1_000, 10_000, 100_000, 1_000_000])
def test_the_clamped_share_stays_inside_its_range_at_the_extremes(answered: int) -> None:
    for right in (1, 2, answered // 2, answered - 2, answered - 1):
        got = accuracy(right, answered, wilson(right, answered))
        assert got.share is not None and got.low is not None and got.high is not None
        assert 0.001 <= got.share <= 0.999, (right, answered)
        assert 0 <= got.low <= got.share <= got.high <= 1, (right, answered)


def at(day: date, h: int, m: int, s: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=MADRID)


def test_the_cutoff_is_the_deadline_cap_and_the_grace_after_midnight() -> None:
    assert (600, timedelta(seconds=3)) == (MAX_BUDGET, GRACE)  # "about 00:10:03", as the spec and docs say
    d = date(2026, 10, 2)
    flip = at(d, 0, 0) + timedelta(seconds=MAX_BUDGET) + GRACE
    assert accuracy_cutoff(flip) == d
    assert accuracy_cutoff(flip - timedelta(microseconds=1)) == d - timedelta(days=1)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            at(date(2026, 10, 2), 0, 0),
            date(2026, 10, 1),
        ),  # yesterday's daily is still open to the late arrivals
        (at(date(2026, 10, 2), 0, 5), date(2026, 10, 1)),
        (at(date(2026, 10, 2), 0, 10, 2), date(2026, 10, 1)),
        (at(date(2026, 10, 2), 0, 10, 3), date(2026, 10, 2)),
        (at(date(2026, 10, 2), 0, 10, 4), date(2026, 10, 2)),
        (at(date(2026, 10, 2), 12, 0), date(2026, 10, 2)),
        (at(date(2026, 10, 1), 23, 59, 59), date(2026, 10, 1)),
        (at(date(2026, 9, 1), 0, 5), date(2026, 8, 31)),  # across a season turn
        (at(date(2026, 9, 1), 0, 11), date(2026, 9, 1)),
        (at(date(2027, 1, 1), 0, 9), date(2026, 12, 31)),  # and a year
        (at(date(2027, 1, 1), 0, 11), date(2027, 1, 1)),
        # The summer-time midnights are 22:00 UTC, the winter-time ones 23:00 UTC; the day of the change has 25 hours.
        (datetime(2026, 10, 24, 22, 10, 2, tzinfo=UTC), date(2026, 10, 24)),
        (datetime(2026, 10, 24, 22, 10, 4, tzinfo=UTC), date(2026, 10, 25)),
        (datetime(2026, 10, 25, 0, 30, tzinfo=UTC), date(2026, 10, 25)),  # 02:30 summer time
        (datetime(2026, 10, 25, 1, 30, tzinfo=UTC), date(2026, 10, 25)),  # 02:30 again, winter time
        (datetime(2026, 10, 25, 23, 10, 2, tzinfo=UTC), date(2026, 10, 25)),
        (datetime(2026, 10, 25, 23, 10, 4, tzinfo=UTC), date(2026, 10, 26)),
        # The short day, 28 March 2027 (23 hours).
        (datetime(2027, 3, 27, 23, 10, 2, tzinfo=UTC), date(2027, 3, 27)),
        (datetime(2027, 3, 27, 23, 10, 4, tzinfo=UTC), date(2027, 3, 28)),
        (datetime(2027, 3, 28, 1, 5, tzinfo=UTC), date(2027, 3, 28)),  # 03:05 summer time
        (datetime(2027, 3, 28, 22, 10, 2, tzinfo=UTC), date(2027, 3, 28)),
        (datetime(2027, 3, 28, 22, 10, 4, tzinfo=UTC), date(2027, 3, 29)),
    ],
)
def test_the_accuracy_cutoff_is_the_first_day_whose_dailies_have_not_yet_been_closed_to_everyone(
    now: datetime, expected: date
) -> None:
    assert accuracy_cutoff(now) == expected
    assert accuracy_cutoff(now.astimezone(UTC)) == expected  # whatever zone the clock speaks


def test_the_cutoff_only_moves_forward_and_trails_today_by_at_most_one_day() -> None:
    start = datetime(2026, 10, 24, 20, 0, tzinfo=UTC)
    seen = None
    for minute in range(0, 3 * 24 * 60, 7):
        now = start + timedelta(minutes=minute)
        got = accuracy_cutoff(now)
        assert got in (madrid_day(now), madrid_day(now) - timedelta(days=1))
        assert seen is None or got >= seen
        seen = got
