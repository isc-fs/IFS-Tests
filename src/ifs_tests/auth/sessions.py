from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, or_
from sqlalchemy.orm import Session as DB

from ..db.models import Session, User
from .tokens import new_token, token_hash

COOKIE = "__Host-sid"
IDLE = timedelta(hours=12)
ABSOLUTE = timedelta(days=30)
TOUCH_EVERY = timedelta(minutes=5)


def create_session(db: DB, user: User, now: datetime) -> str:
    token = new_token()
    db.add(
        Session(
            id_hash=token_hash(token),
            user_id=user.id,
            created_at=now,
            last_seen=now,
            expires_at=now + ABSOLUTE,
        )
    )
    user.last_seen = now
    return token


def resolve_session(db: DB, token: str, now: datetime) -> User | None:
    """The active user behind a session cookie, or None. Expired sessions are removed on sight."""
    row = db.get(Session, token_hash(token))
    if row is None:
        return None
    if now >= row.expires_at or now - row.last_seen >= IDLE:
        db.delete(row)
        db.commit()
        return None
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    if now - row.last_seen >= TOUCH_EVERY:
        row.last_seen = now
        user.last_seen = now
        db.commit()
    return user


def end_session(db: DB, token: str) -> None:
    db.execute(delete(Session).where(Session.id_hash == token_hash(token)))


def end_all_sessions(db: DB, user_id: int, keep_token: str | None = None) -> None:
    stmt = delete(Session).where(Session.user_id == user_id)
    if keep_token:
        stmt = stmt.where(Session.id_hash != token_hash(keep_token))
    db.execute(stmt)


def purge_expired(db: DB, now: datetime) -> int:
    stmt = delete(Session).where(or_(Session.expires_at <= now, Session.last_seen <= now - IDLE))
    return cast(CursorResult[Any], db.execute(stmt)).rowcount
