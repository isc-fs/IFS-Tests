from __future__ import annotations

from datetime import date

import pytest

from ifs_tests.domain.mock import bar_to_beat, points, season


@pytest.mark.parametrize(
    ("day", "expected"), [(date(2026, 8, 31), 2025), (date(2026, 9, 1), 2026), (date(2027, 2, 1), 2026)]
)
def test_seasons_start_in_september(day: date, expected: int) -> None:
    assert season(day) == expected


def test_only_the_counted_session_scores() -> None:
    assert points(7, True) == 14
    assert points(7, False) == 0


@pytest.mark.parametrize(
    ("lq", "text"),
    [
        (None, None),
        ({"method": "score", "score": 5, "correct_answers": None, "time_s": None}, "a score of 5."),
        (
            {"method": "time", "score": None, "correct_answers": 9, "time_s": 1325},
            "9 correct answers in 22 min 05 s.",
        ),
        ({"method": "time", "score": None, "correct_answers": None, "time_s": None}, None),
    ],
)
def test_bar_to_beat(lq: dict[str, object] | None, text: str | None) -> None:
    result = bar_to_beat(lq)
    assert result == (None if text is None else "The last team to get a slot had " + text)
