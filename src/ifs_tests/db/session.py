from __future__ import annotations

import threading
from collections.abc import Iterator
from functools import lru_cache
from typing import Any, cast

from sqlalchemy import CursorResult, Engine, Result, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from ..settings import get_settings

# The first requests after a start arrive together: without the lock each thread built its own engine, so its
# own pool, and a burst ran Postgres out of connections.
_lock = threading.RLock()


@lru_cache
def _engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=10,
    )


@lru_cache
def _factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_engine() -> Engine:
    with _lock:
        return _engine()


def session_factory() -> sessionmaker[Session]:
    with _lock:
        return _factory()


def reset() -> None:
    """Forget the engine (tests that change the settings)."""
    with _lock:
        _factory.cache_clear()
        _engine.cache_clear()


def get_session() -> Iterator[Session]:
    with session_factory()() as session:
        yield session


READ_ONLY_OPTIONS = (
    "-c default_transaction_read_only=on -c statement_timeout=120000 -c lock_timeout=5000"
    " -c idle_in_transaction_session_timeout=60000"
)


def read_only_engine(dsn: str) -> Engine:
    """An engine for ad hoc read-only tooling (the integrity report), never the app's: no pool, every
    transaction READ ONLY and REPEATABLE READ so a whole fetch reads one snapshot, and server-side timeouts so it
    can never hold a lock a deploy's migration would queue behind."""
    return create_engine(
        dsn, poolclass=NullPool, connect_args={"options": READ_ONLY_OPTIONS}
    ).execution_options(postgresql_readonly=True, isolation_level="REPEATABLE READ")


def rowcount(result: Result[Any]) -> int:
    return cast(CursorResult[Any], result).rowcount
