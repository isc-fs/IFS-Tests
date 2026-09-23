from datetime import UTC, datetime
from datetime import time as clock_time

from ifs_tests.scheduler import Job, due

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
