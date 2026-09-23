"""A minimal daily scheduler for the `scheduler` service. Jobs are idempotent, so a job whose time
has passed runs once when the process starts (e.g. after the server's 04:00 reboot)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as clock_time
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
log = logging.getLogger("ifs_tests.scheduler")


@dataclass(frozen=True)
class Job:
    name: str
    at: clock_time  # Madrid local time
    run: Callable[[datetime], object]


def due(jobs: list[Job], last_run: dict[str, date], now: datetime) -> list[Job]:
    local = now.astimezone(MADRID)
    return [j for j in jobs if local.time() >= j.at and last_run.get(j.name) != local.date()]


def run_forever(jobs: list[Job], poll_seconds: float = 30) -> None:
    last_run: dict[str, date] = {}
    log.info("scheduler: %s", ", ".join(f"{j.name}@{j.at:%H:%M}" for j in jobs))
    while True:
        now = datetime.now(UTC)
        for job in due(jobs, last_run, now):
            try:
                log.info("%s: %s", job.name, job.run(now))
            except Exception:
                log.exception("%s failed", job.name)
            last_run[job.name] = now.astimezone(MADRID).date()
        time.sleep(poll_seconds)
