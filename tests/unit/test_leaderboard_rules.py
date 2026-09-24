from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from ifs_tests.domain.daily import madrid_day
from ifs_tests.domain.leaderboard import (
    Member,
    VerticalScore,
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
