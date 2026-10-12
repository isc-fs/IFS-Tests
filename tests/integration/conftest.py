from __future__ import annotations

import contextlib
import io
import os
from collections.abc import Iterator
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from ifs_tests import cli
from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Question, User
from ifs_tests.services.bank import import_bank
from ifs_tests.settings import IntegritySettings

NOW = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
def daily_player(db: Session, tmp_path: Path) -> User:
    """A player, with the sample bank loaded at difficulty 3."""
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, NOW)
    db.execute(update(Question).values(difficulty=3))
    user = User(email="p@x.com", password_hash="x", display_name="Player")
    db.add(user)
    db.commit()
    return user


def run(args: list[str], stdin: str = "") -> str:
    """`ifs-tests <args>` in this process with `stdin` on standard input; returns what it printed."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.MonkeyPatch.context() as m:
        m.setattr("sys.stdin", io.StringIO(stdin))
        cli.main(args)
    return out.getvalue()


# The salt of a review and the thresholds the integrity report refuses to run without. Test values only.
INTEGRITY_SALT = "9f2c71ab05d4e8c3b6a1f07d52e9c48a13b7d6e0f58a4c29b1e7036d85fa4c1e"
INTEGRITY_THRESHOLDS = {
    "MIN_N": "10",
    "FOLLOW_WITHIN_MIN": "30",
    "FOLLOW_MIN": "5",
    "FOLLOW_Z": "2.5",
    "FOLLOW_RELAY_Z": "2.5",
    "READING_FLOOR_S": "12",
    "READING_CPS": "15",
    "BELOW_FLOOR_SHARE": "0.5",
    "NARROW_SD_LOG": "0.15",
    "FLAT_CORR": "0.1",
    "HARD_RESIDUAL_Z": "2.5",
    "AWAY_Z": "2.0",
    "UPSTREAM_MIN": "5",
    "UPSTREAM_Z": "2.5",
}


def freeze_today(monkeypatch: pytest.MonkeyPatch, at: datetime) -> None:
    """The command's idea of now (it refuses an --until in the future): fixed, so that the dates planted in 2026
    do not depend on the day the tests run."""

    class Frozen(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Frozen:
            return cls.fromtimestamp(at.timestamp(), tz)

    monkeypatch.setattr("ifs_tests.cli.datetime", Frozen, raising=False)


TODAY = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def set_integrity_env(monkeypatch: pytest.MonkeyPatch, dsn: str, salt: str | None = INTEGRITY_SALT) -> None:
    """Exactly the IFS_INTEGRITY_* variables the report reads, and no others the machine might have set, on
    12 October 2026."""
    freeze_today(monkeypatch, TODAY)
    for name in [n for n in os.environ if n.startswith("IFS_INTEGRITY_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("IFS_INTEGRITY_DSN", dsn)
    if salt is not None:
        monkeypatch.setenv("IFS_INTEGRITY_SALT", salt)
    for name, value in INTEGRITY_THRESHOLDS.items():
        monkeypatch.setenv(f"IFS_INTEGRITY_{name}", value)


@pytest.fixture
def integrity_env(monkeypatch: pytest.MonkeyPatch, app_engine: Engine) -> Iterator[str]:
    """The report pointed at the test database (as its superuser: the read-only transaction is what is tested
    here, the role in test_db_roles.py). Yields the DSN."""
    dsn = app_engine.url.render_as_string(hide_password=False)
    set_integrity_env(monkeypatch, dsn)
    yield dsn


def integrity_settings() -> IntegritySettings:
    """The report's settings with the test thresholds and nothing from the machine's environment or .env."""
    cls: Any = IntegritySettings
    return cast(
        IntegritySettings, cls(_env_file=None, **{k.lower(): v for k, v in INTEGRITY_THRESHOLDS.items()})
    )
