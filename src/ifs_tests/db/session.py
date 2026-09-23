from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any, cast

from sqlalchemy import CursorResult, Engine, Result, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..settings import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@lru_cache
def session_factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with session_factory()() as session:
        yield session


def rowcount(result: Result[Any]) -> int:
    return cast(CursorResult[Any], result).rowcount
