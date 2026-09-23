from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as DB

from ..auth.sessions import resolve_session
from ..db.models import User
from ..db.session import get_session
from ..settings import Settings


def get_db() -> Iterator[DB]:
    yield from get_session()


def get_now() -> datetime:
    return datetime.now(UTC)


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


Db = Annotated[DB, Depends(get_db)]
Now = Annotated[datetime, Depends(get_now)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]


def current_user(request: Request, db: Db, now: Now) -> User | None:
    token = request.cookies.get(get_app_settings(request).session_cookie)
    return resolve_session(db, token, now) if token else None


def current_member(user: Annotated[User | None, Depends(current_user)]) -> User:
    if user is None:
        raise HTTPException(401, "Sign in first.")
    return user


def require_reviewer(user: Annotated[User, Depends(current_member)]) -> User:
    if user.role not in ("reviewer", "admin"):
        raise HTTPException(403, "Reviewers only.")
    return user


def require_admin(user: Annotated[User, Depends(current_member)]) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admins only.")
    return user


Member = Annotated[User, Depends(current_member)]
Reviewer = Annotated[User, Depends(require_reviewer)]
Admin = Annotated[User, Depends(require_admin)]
