from __future__ import annotations

import threading
from collections.abc import Iterator
from functools import lru_cache
from typing import Any, cast

from sqlalchemy import CursorResult, Engine, Result, create_engine
from sqlalchemy.orm import Session, sessionmaker

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


def rowcount(result: Result[Any]) -> int:
    return cast(CursorResult[Any], result).rowcount
