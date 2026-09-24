from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path

import pytest

from ifs_tests import scheduler
from ifs_tests.scheduler import Job, beat, due, tick

JOB = Job("maintenance", clock_time(3, 0), lambda now: None)


def test_job_runs_once_per_madrid_day_after_its_time() -> None:
    before = datetime(2026, 10, 1, 0, 30, tzinfo=UTC)  # 02:30 in Madrid (CEST)
    after = datetime(2026, 10, 1, 1, 30, tzinfo=UTC)  # 03:30 in Madrid
    assert due([JOB], {}, before) == []
    assert due([JOB], {}, after) == [JOB]
    assert due([JOB], {"maintenance": after.date()}, after) == []


def test_madrid_day_boundary_not_utc() -> None:
    daily = Job("ensure-daily", clock_time(0, 1), lambda now: None)
    # 22:30 UTC on 1 Oct is already 00:30 on 2 Oct in Madrid: a new day, so the job is due again.
    late = datetime(2026, 10, 1, 22, 30, tzinfo=UTC)
    assert due([daily], {"ensure-daily": datetime(2026, 10, 1).date()}, late) == [daily]
    assert due([daily], {"ensure-daily": datetime(2026, 10, 2).date()}, late) == []


def test_a_failing_job_is_logged_and_not_retried_the_same_day(caplog: pytest.LogCaptureFixture) -> None:
    calls: list[datetime] = []

    def boom(now: datetime) -> None:
        calls.append(now)
        raise RuntimeError("database down")

    job = Job("maintenance", clock_time(3, 0), boom)
    last_run: dict[str, date] = {}
    at = datetime(2026, 10, 1, 2, 0, tzinfo=UTC)  # 04:00 Madrid
    tick([job], last_run, at)
    tick([job], last_run, at)
    assert len(calls) == 1 and "maintenance failed" in caplog.text


@pytest.mark.parametrize("day", [datetime(2026, 3, 29), datetime(2026, 10, 25)])
def test_runs_exactly_once_on_daylight_saving_days(day: datetime) -> None:
    calls: list[datetime] = []
    job = Job("maintenance", clock_time(3, 0), calls.append)
    last_run: dict[str, date] = {}
    for minute in range(0, 24 * 60, 10):
        tick([job], last_run, day.replace(tzinfo=UTC) + timedelta(minutes=minute))
    assert len(calls) == 1


def test_heartbeat_only_while_the_database_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    heartbeat = tmp_path / "heartbeat"
    monkeypatch.setattr(scheduler, "HEARTBEAT", heartbeat)

    def down() -> None:
        raise ConnectionError("password authentication failed")

    assert not beat(down) and not heartbeat.exists()
    assert "password authentication failed" in caplog.text
    assert beat(lambda: None) and heartbeat.exists()
