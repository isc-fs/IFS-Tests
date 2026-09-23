from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DB

from ..auth.passwords import dummy_hash, hash_password, needs_rehash, password_problem, verify_password
from ..auth.sessions import end_all_sessions
from ..auth.tokens import new_token, token_hash
from ..db.models import ROLES, STATUSES, VERTICALS, AuditLog, Invite, PasswordReset, User

INVITE_TTL = timedelta(days=7)
RESET_TTL = timedelta(hours=24)
LOCK_AFTER = 5
LOCK_FOR = timedelta(minutes=15)

LOGIN_FAILED = "Wrong email or password. After 5 failed attempts the account is locked for 15 minutes."

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DISPLAY_NAME = re.compile(r"^[\w][\w .'-]*$")


class AccountError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def audit(db: DB, actor: User | None, action: str, target: str | None = None, **details: Any) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, target=target, details=details))


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise AccountError("Enter a valid email address.")
    return email


def clean_display_name(db: DB, name: str, exclude_user: int | None = None) -> str:
    name = " ".join(name.split())
    if not 2 <= len(name) <= 24 or not _DISPLAY_NAME.match(name):
        raise AccountError("Display names are 2–24 letters, numbers, spaces, dots, dashes or apostrophes.")
    clash = db.scalar(select(User.id).where(func.lower(User.display_name) == name.lower()))
    if clash is not None and clash != exclude_user:
        raise AccountError("That display name is taken.", 409)
    return name


def check_vertical(vertical: str | None) -> str | None:
    if vertical is not None and vertical not in VERTICALS:
        raise AccountError("Unknown vertical.")
    return vertical


# Invites and registration


def create_invite(
    db: DB,
    actor: User,
    now: datetime,
    role: str = "member",
    vertical: str | None = None,
    note: str | None = None,
) -> tuple[str, Invite]:
    if role not in ROLES:
        raise AccountError("Unknown role.")
    token = new_token()
    invite = Invite(
        token_hash=token_hash(token),
        role=role,
        vertical=check_vertical(vertical),
        note=(note or "").strip()[:80] or None,
        created_by=actor.id,
        created_at=now,
        expires_at=now + INVITE_TTL,
    )
    db.add(invite)
    db.flush()
    audit(db, actor, "invite.create", f"invite:{invite.id}", role=role, vertical=vertical, note=invite.note)
    db.commit()
    return token, invite


def open_invite(db: DB, token: str, now: datetime, lock: bool = False) -> Invite:
    stmt = select(Invite).where(Invite.token_hash == token_hash(token))
    invite = db.scalar(stmt.with_for_update() if lock else stmt)
    if invite is None or invite.used_at is not None or invite.expires_at <= now:
        raise AccountError("This invite link is invalid, used or expired. Ask an admin for a new one.", 404)
    return invite


def register(db: DB, token: str, email: str, display_name: str, password: str, now: datetime) -> User:
    invite = open_invite(db, token, now, lock=True)
    email = normalize_email(email)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise AccountError("An account with this email already exists. Sign in instead.", 409)
    name = clean_display_name(db, display_name)
    problem = password_problem(password, email=email, display_name=name)
    if problem:
        raise AccountError(problem)
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=name,
        vertical=invite.vertical,
        role=invite.role,
        created_at=now,
    )
    db.add(user)
    db.flush()
    invite.used_at, invite.used_by = now, user.id
    audit(db, user, "user.register", f"user:{user.id}", invite=invite.id, role=user.role)
    db.commit()
    return user


# Sign-in


def authenticate(db: DB, email: str, password: str, now: datetime) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower()).with_for_update())
    if user is None:
        verify_password(dummy_hash(), password)
        raise AccountError(LOGIN_FAILED, 401)
    if user.locked_until and user.locked_until > now:
        raise AccountError(LOGIN_FAILED, 401)
    if not verify_password(user.password_hash, password):
        user.failed_logins += 1
        if user.failed_logins >= LOCK_AFTER:
            user.failed_logins, user.locked_until = 0, now + LOCK_FOR
            audit(db, None, "user.locked", f"user:{user.id}")
        db.commit()
        raise AccountError(LOGIN_FAILED, 401)
    if user.status != "active":
        raise AccountError(LOGIN_FAILED, 401)
    user.failed_logins, user.locked_until = 0, None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


# Passwords


def create_reset(db: DB, actor: User, user_id: int, now: datetime) -> str:
    user = db.get(User, user_id)
    if user is None:
        raise AccountError("No such user.", 404)
    token = new_token()
    db.add(
        PasswordReset(
            token_hash=token_hash(token),
            user_id=user.id,
            created_by=actor.id,
            created_at=now,
            expires_at=now + RESET_TTL,
        )
    )
    audit(db, actor, "reset.create", f"user:{user.id}")
    db.commit()
    return token


def open_reset(db: DB, token: str, now: datetime, lock: bool = False) -> PasswordReset:
    stmt = select(PasswordReset).where(PasswordReset.token_hash == token_hash(token))
    reset = db.scalar(stmt.with_for_update() if lock else stmt)
    if reset is None or reset.used_at is not None or reset.expires_at <= now:
        raise AccountError("This reset link is invalid, used or expired. Ask an admin for a new one.", 404)
    return reset


def reset_password(db: DB, token: str, password: str, now: datetime) -> User:
    reset = open_reset(db, token, now, lock=True)
    user = db.get_one(User, reset.user_id)
    problem = password_problem(password, email=user.email, display_name=user.display_name)
    if problem:
        raise AccountError(problem)
    user.password_hash = hash_password(password)
    user.failed_logins, user.locked_until = 0, None
    reset.used_at = now
    end_all_sessions(db, user.id)
    audit(db, user, "password.reset", f"user:{user.id}", reset=reset.id)
    db.commit()
    return user


def change_password(db: DB, user: User, current: str, new: str, keep_token: str) -> None:
    if not verify_password(user.password_hash, current):
        raise AccountError("Your current password is wrong.", 403)
    problem = password_problem(new, email=user.email, display_name=user.display_name)
    if problem:
        raise AccountError(problem)
    user.password_hash = hash_password(new)
    end_all_sessions(db, user.id, keep_token=keep_token)
    audit(db, user, "password.change", f"user:{user.id}")
    db.commit()


# Profile and administration


def update_profile(
    db: DB,
    user: User,
    display_name: str | None = None,
    vertical: str | None = None,
    leaderboard_opt_out: bool | None = None,
    clear_vertical: bool = False,
) -> User:
    if display_name is not None:
        user.display_name = clean_display_name(db, display_name, exclude_user=user.id)
    if vertical is not None or clear_vertical:
        user.vertical = check_vertical(vertical)
    if leaderboard_opt_out is not None:
        user.leaderboard_opt_out = leaderboard_opt_out
    db.commit()
    return user


def _active_admins(db: DB) -> int:
    return db.scalar(select(func.count()).where(User.role == "admin", User.status == "active")) or 0


def update_user(
    db: DB, actor: User, user_id: int, role: str | None = None, status: str | None = None
) -> User:
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        raise AccountError("No such user.", 404)
    if user.id == actor.id:
        raise AccountError("You can't change your own role or status.", 403)
    if role is not None and role not in ROLES:
        raise AccountError("Unknown role.")
    if status is not None and status not in STATUSES:
        raise AccountError("Unknown status.")
    loses_admin = (
        user.role == "admin"
        and user.status == "active"
        and ((role is not None and role != "admin") or (status is not None and status != "active"))
    )
    if loses_admin and _active_admins(db) <= 1:
        raise AccountError("There must always be at least one active admin.", 409)
    changes: dict[str, Any] = {}
    if role is not None and role != user.role:
        changes["role"] = [user.role, role]
        user.role = role
    if status is not None and status != user.status:
        changes["status"] = [user.status, status]
        user.status = status
        if status != "active":
            end_all_sessions(db, user.id)
    if changes:
        audit(db, actor, "user.update", f"user:{user.id}", **changes)
    db.commit()
    return user


def revoke_sessions(db: DB, actor: User, user_id: int) -> None:
    if db.get(User, user_id) is None:
        raise AccountError("No such user.", 404)
    end_all_sessions(db, user_id)
    audit(db, actor, "user.revoke_sessions", f"user:{user_id}")
    db.commit()


def revoke_invite(db: DB, actor: User, invite_id: int, now: datetime) -> None:
    invite = db.get(Invite, invite_id)
    if invite is None or invite.used_at is not None:
        raise AccountError("No such open invite.", 404)
    invite.expires_at = now
    audit(db, actor, "invite.revoke", f"invite:{invite.id}")
    db.commit()


def create_first_admin(db: DB, email: str, display_name: str, password: str, now: datetime) -> User:
    """Bootstrap from the CLI on the server. Refuses once any admin exists."""
    if _active_admins(db) > 0:
        raise AccountError("An admin already exists. Use an invite with role 'admin' instead.", 409)
    email = normalize_email(email)
    name = clean_display_name(db, display_name)
    problem = password_problem(password, email=email, display_name=name)
    if problem:
        raise AccountError(problem)
    user = User(
        email=email, password_hash=hash_password(password), display_name=name, role="admin", created_at=now
    )
    db.add(user)
    db.flush()
    audit(db, user, "user.bootstrap_admin", f"user:{user.id}")
    db.commit()
    return user
