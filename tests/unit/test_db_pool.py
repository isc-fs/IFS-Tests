from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.pool import QueuePool

from ifs_tests.db import session
from ifs_tests.db.session import get_engine
from ifs_tests.settings import Settings, get_settings


@pytest.fixture
def fresh() -> Iterator[None]:
    get_settings.cache_clear()
    session.reset()
    yield
    get_settings.cache_clear()
    session.reset()


def test_pool_defaults_fit_the_compose_budget() -> None:
    s = Settings()
    assert (s.db_pool_size, s.db_max_overflow) == (5, 5)


def test_engine_pool_follows_the_environment(fresh: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IFS_DB_POOL_SIZE", "2")
    monkeypatch.setenv("IFS_DB_MAX_OVERFLOW", "0")
    pool = get_engine().pool
    assert isinstance(pool, QueuePool)
    assert pool.size() == 2 and pool._max_overflow == 0


def test_pool_settings_must_be_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IFS_DB_POOL_SIZE", "lots")
    with pytest.raises(ValueError, match="db_pool_size"):
        Settings()


def test_threads_asking_at_once_share_one_engine(fresh: None) -> None:
    """The first requests after a start: one pool per process, or a burst runs Postgres out of connections."""
    barrier = threading.Barrier(16)
    engines: list[Engine] = []

    def ask() -> None:
        barrier.wait()
        engines.append(get_engine())

    threads = [threading.Thread(target=ask) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({id(e) for e in engines}) == 1
