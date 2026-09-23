from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, or_, update
from sqlalchemy.orm import Session as DB

from ..db.models import Session, User
from ..db.session import rowcount
from ..domain.accounts import SESSION_ABSOLUTE, SESSION_IDLE, SessionState, session_state
from .tokens import new_token, token_hash


def create_session(db: DB, user: User, now: datetime) -> str:
    token = new_token()
    db.add(
        Session(
            id_hash=token_hash(token),
            user_id=user.id,
            created_at=now,
            last_seen=now,
            expires_at=now + SESSION_ABSOLUTE,
        )
    )
    user.last_seen = now
    return token


def resolve_session(db: DB, token: str, now: datetime) -> User | None:
    """The active user behind a session cookie, or None. Expired sessions are removed on sight."""
    row = db.get(Session, token_hash(token))
    if row is None:
        return None
    state = session_state(row.expires_at, row.last_seen, now)
    if state is SessionState.EXPIRED:
        db.execute(delete(Session).where(Session.id_hash == row.id_hash))
        db.commit()
        return None
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    if state is SessionState.NEEDS_TOUCH:
        # Core UPDATE: if the session was revoked meanwhile (other tab, admin), nothing breaks.
        touched = db.execute(update(Session).where(Session.id_hash == row.id_hash).values(last_seen=now))
        if rowcount(touched) == 0:
            db.rollback()
            return None
        db.execute(update(User).where(User.id == user.id).values(last_seen=now))
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
    stmt = delete(Session).where(or_(Session.expires_at <= now, Session.last_seen <= now - SESSION_IDLE))
    return rowcount(db.execute(stmt))
