from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ifs_tests.api.app import create_app
from ifs_tests.api.deps import get_db, get_now
from ifs_tests.settings import Settings


def _docker_available() -> bool:
    return shutil.which("docker") is not None and os.system("docker info >/dev/null 2>&1") == 0


def migrate(url: str, revision: str = "head") -> Config:
    cfg = Config("alembic.ini")
    cfg.cmd_opts = argparse.Namespace(x=[f"url={url}"])
    command.upgrade(cfg, revision)
    return cfg


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    if not _docker_available():
        if os.environ.get("CI"):
            pytest.fail("Docker is required in CI: database tests must not be skipped silently")
        pytest.skip("Docker is not available")
    if sys.platform == "darwin":
        # Docker Desktop exposes the socket under ~/.docker/run, which the Ryuk reaper can't bind-mount.
        os.environ.setdefault("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", "/var/run/docker.sock")
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def app_engine(postgres_url: str) -> Engine:
    """A separate database migrated to head, shared by the API tests (tables are emptied per test)."""
    admin = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("CREATE DATABASE app_tests"))
    url = postgres_url.rsplit("/", 1)[0] + "/app_tests"
    migrate(url)
    return create_engine(url)


@dataclass
class Clock:
    now: datetime

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 10, 1, 10, 0, tzinfo=UTC))


@pytest.fixture
def db(app_engine: Engine) -> Iterator[Session]:
    with app_engine.begin() as c:
        tables = c.execute(
            text(
                "SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalar_one()
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with sessionmaker(app_engine, expire_on_commit=False)() as session:
        yield session


PUBLIC_ORIGIN = "https://testserver"


@pytest.fixture
def app_client(app_engine: Engine, clock: Clock, db: Session) -> Iterator[TestClient]:
    app = create_app(Settings(env="test", public_origin=PUBLIC_ORIGIN))
    make = sessionmaker(app_engine, expire_on_commit=False)

    def _db() -> Iterator[Session]:
        with make() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_now] = lambda: clock.now
    with TestClient(app, base_url="https://testserver", headers={"X-CSRF": "1"}) as c:
        yield c


@pytest.fixture
def new_client(app_client: TestClient) -> Callable[[], TestClient]:
    """Another browser: same app, separate cookie jar."""
    return lambda: TestClient(app_client.app, base_url=PUBLIC_ORIGIN, headers={"X-CSRF": "1"})


@pytest.fixture(autouse=True)
def no_crits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Critical answers are a 5 % draw from a random server secret: off everywhere, so XP can be asserted exactly.
    A test that wants one patches `services.xp._crit` back."""
    from ifs_tests.services import xp

    monkeypatch.setattr(xp, "_crit", lambda *_: False)
