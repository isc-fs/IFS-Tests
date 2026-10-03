from __future__ import annotations

from datetime import date

import pytest

from ifs_tests.domain.mock import bar_to_beat, budget, season


@pytest.mark.parametrize(
    ("day", "expected"), [(date(2026, 8, 31), 2025), (date(2026, 9, 1), 2026), (date(2027, 2, 1), 2026)]
)
def test_seasons_start_in_september(day: date, expected: int) -> None:
    assert season(day) == expected


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
        (
            {"method": "time", "score": None, "correct_answers": None, "time_s": 1118},
            "finished in 18 min 38 s.",
        ),
    ],
)
def test_bar_to_beat(lq: dict[str, object] | None, text: str | None) -> None:
    result = bar_to_beat(lq)
    if text and text.startswith("finished"):
        assert result == "The last team to get a slot " + text
    else:
        assert result == (None if text is None else "The last team to get a slot had " + text)


@pytest.mark.parametrize(
    ("time_s", "kind", "seconds"),
    [
        (1200, "choice-one", 1200),  # the real quiz's time, past the daily question's 10 minutes
        (40, "number", 40),  # and under its minute
        (10, "choice-one", 10),
        (None, "choice-one", 120),  # unknown: the daily defaults
        (None, "choice-many", 150),
        (None, "number", 240),
        (0, "text", 240),
        (-5, "choice-one", 120),  # bad data
        (3, "choice-one", 10),
        (86400, "number", 3600),
    ],
)
def test_a_mock_question_runs_on_its_real_time(time_s: int | None, kind: str, seconds: int) -> None:
    assert budget(time_s, kind) == seconds
