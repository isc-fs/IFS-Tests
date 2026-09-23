from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DB

from ..auth.passwords import dummy_hash, hash_password, needs_rehash, password_problem, verify_password
from ..auth.sessions import create_session, end_all_sessions, end_session
from ..auth.tokens import new_token, token_hash
from ..db.models import ROLES, STATUSES, VERTICALS, AuditLog, Invite, PasswordReset, User
from ..domain import accounts as rules

INVITE_TTL = timedelta(days=7)
RESET_TTL = timedelta(hours=24)
LOGIN_FAILED = (
    f"Wrong email or password. After {rules.LOCK_AFTER} failed attempts the account is locked for "
    f"{rules.LOCK_FOR.seconds // 60} minutes; an admin can send you a reset link."
)
NAME_RULE = "Use 2–24 Latin letters, numbers, spaces, dots, dashes or apostrophes."


class AccountError(Exception):
    """A user-facing error. `fields` maps form fields to messages when the form can show them inline."""

    def __init__(self, message: str, status: int = 400, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.fields = fields or {}


def audit(db: DB, actor: User | None, action: str, target: str | None = None, **details: Any) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, target=target, details=details))


def _name_taken(db: DB, name: str, exclude_user: int | None = None) -> bool:
    clash = db.scalar(select(User.id).where(func.lower(User.display_name) == func.lower(name)))
    return clash is not None and clash != exclude_user


def _check_new_user(db: DB, email: str, display_name: str, password: str) -> tuple[str, str]:
    """Validate a whole registration at once, so the form can show every problem together."""
    errors: dict[str, str] = {}
    clean_email = rules.clean_email(email)
    name = rules.clean_display_name(display_name)
    if clean_email is None:
        errors["email"] = "Enter a valid email address."
    elif db.scalar(select(User.id).where(User.email == clean_email)) is not None:
        errors["email"] = "An account with this email already exists. Sign in instead."
    if name is None:
        errors["display_name"] = NAME_RULE
    elif _name_taken(db, name):
        errors["display_name"] = "That display name is taken."
    if problem := password_problem(password, email=clean_email or "", display_name=name or ""):
        errors["password"] = problem
    if errors or clean_email is None or name is None:
        raise AccountError(next(iter(errors.values())), 400, errors)
    return clean_email, name


@contextmanager
def _unique(db: DB) -> Iterator[None]:
    """Uniqueness is checked first for friendly messages; the constraint still wins a race."""
    try:
        yield
    except IntegrityError:
        db.rollback()
        raise AccountError("That email or display name was just taken. Try another.", 409) from None


def _close_resets(db: DB, user_id: int, now: datetime) -> None:
    db.execute(
        update(PasswordReset)
        .where(PasswordReset.user_id == user_id, PasswordReset.used_at.is_(None))
        .values(used_at=now)
    )


def _check_vertical(vertical: str | None) -> str | None:
    if vertical is not None and vertical not in VERTICALS:
        raise AccountError("Unknown vertical.", fields={"vertical": "Unknown vertical."})
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
        vertical=_check_vertical(vertical),
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
    if invite is None or not rules.link_open(invite.used_at, invite.expires_at, now):
        raise AccountError("This invite link is invalid, used or expired. Ask an admin for a new one.", 404)
    return invite


def register(
    db: DB,
    token: str,
    email: str,
    display_name: str,
    password: str,
    now: datetime,
    vertical: str | None = None,
) -> tuple[User, str]:
    invite = open_invite(db, token, now, lock=True)
    email, name = _check_new_user(db, email, display_name, password)
    with _unique(db):
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=name,
            vertical=invite.vertical or _check_vertical(vertical),
            role=invite.role,
            created_at=now,
        )
        db.add(user)
        db.flush()
        invite.used_at, invite.used_by = now, user.id
        audit(db, user, "user.register", f"user:{user.id}", invite=invite.id, role=user.role)
        session = create_session(db, user, now)
        db.commit()
    return user, session


def create_first_admin(db: DB, email: str, display_name: str, password: str, now: datetime) -> User:
    """Bootstrap from the CLI on the server. Refuses once any active admin exists."""
    if _active_admin_ids(db, lock=False):
        raise AccountError("An admin already exists. Use an invite with role 'admin' instead.", 409)
    email, name = _check_new_user(db, email, display_name, password)
    with _unique(db):
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=name,
            role="admin",
            created_at=now,
        )
        db.add(user)
        db.flush()
        audit(db, user, "user.bootstrap_admin", f"user:{user.id}")
        db.commit()
    return user


# Sign-in


def login(db: DB, email: str, password: str, now: datetime, old_session: str | None) -> tuple[User, str]:
    """Check the credentials and start a new session; the old one, if any, is ended (no fixation)."""
    user = db.scalar(select(User).where(User.email == email.strip().lower()).with_for_update())
    if user is None or rules.is_locked(user.locked_until, now):
        verify_password(dummy_hash(), password)
        raise AccountError(LOGIN_FAILED, 401)
    if not verify_password(user.password_hash, password):
        _record_failure(db, user, now)
        raise AccountError(LOGIN_FAILED, 401)
    if user.status != "active":
        raise AccountError(LOGIN_FAILED, 401)
    user.failed_logins, user.locked_until = 0, None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    if old_session:
        end_session(db, old_session)
    session = create_session(db, user, now)
    db.commit()
    return user, session


def _record_failure(db: DB, user: User, now: datetime) -> None:
    lockout = rules.after_failed_login(user.failed_logins, now)
    user.failed_logins, user.locked_until = lockout.failed, lockout.locked_until
    if lockout.locked_until:
        audit(db, None, "user.locked", f"user:{user.id}")
    db.commit()


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
    if reset is None or not rules.link_open(reset.used_at, reset.expires_at, now):
        raise AccountError("This reset link is invalid, used or expired. Ask an admin for a new one.", 404)
    return reset


def _set_password(user: User, password: str, field: str = "password") -> None:
    if problem := password_problem(password, email=user.email, display_name=user.display_name):
        raise AccountError(problem, fields={field: problem})
    user.password_hash = hash_password(password)


def reset_password(db: DB, token: str, password: str, now: datetime) -> User:
    reset = open_reset(db, token, now, lock=True)
    user = db.get_one(User, reset.user_id)
    _set_password(user, password)
    user.failed_logins, user.locked_until = 0, None
    _close_resets(db, user.id, now)
    end_all_sessions(db, user.id)
    audit(db, user, "password.reset", f"user:{user.id}", reset=reset.id)
    db.commit()
    return user


def change_password(db: DB, user: User, current: str, new: str, keep_token: str, now: datetime) -> None:
    if rules.is_locked(user.locked_until, now):
        raise AccountError("Too many wrong attempts. Try again in 15 minutes.", 429)
    if not verify_password(user.password_hash, current):
        _record_failure(db, user, now)
        raise AccountError("Your current password is wrong.", 403, {"current_password": "Wrong password."})
    _set_password(user, new, field="new_password")
    user.failed_logins = 0
    _close_resets(db, user.id, now)
    end_all_sessions(db, user.id, keep_token=keep_token)
    audit(db, user, "password.change", f"user:{user.id}")
    db.commit()


# Profile


def update_profile(db: DB, user: User, changes: dict[str, Any]) -> User:
    """`changes` holds only the fields the client sent, so `vertical: null` clears it."""
    if "display_name" in changes:
        name = rules.clean_display_name(changes["display_name"] or "")
        if name is None:
            raise AccountError(NAME_RULE, fields={"display_name": NAME_RULE})
        if _name_taken(db, name, exclude_user=user.id):
            raise AccountError(
                "That display name is taken.", 409, {"display_name": "That display name is taken."}
            )
        user.display_name = name
    if "vertical" in changes:
        user.vertical = _check_vertical(changes["vertical"])
    if changes.get("leaderboard_opt_out") is not None:
        user.leaderboard_opt_out = changes["leaderboard_opt_out"]
    with _unique(db):
        db.commit()
    return user


# Administration


def _active_admin_ids(db: DB, lock: bool = True) -> list[int]:
    stmt = select(User.id).where(User.role == "admin", User.status == "active").order_by(User.id)
    return list(db.scalars(stmt.with_for_update() if lock else stmt))


def update_user(
    db: DB, actor: User, user_id: int, role: str | None = None, status: str | None = None
) -> User:
    if user_id == actor.id:
        raise AccountError("You can't change your own role or status.", 403)
    if role is not None and role not in ROLES:
        raise AccountError("Unknown role.")
    if status is not None and status not in STATUSES:
        raise AccountError("Unknown status.")
    # Lock every active admin row first, so two admins demoting each other can't both succeed.
    admins = _active_admin_ids(db)
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        raise AccountError("No such user.", 404)
    if rules.loses_admin(user.role, user.status, role, status) and len(admins) <= 1:
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
    if invite is None or not rules.link_open(invite.used_at, invite.expires_at, now):
        raise AccountError("No such open invite.", 404)
    invite.expires_at = now
    audit(db, actor, "invite.revoke", f"invite:{invite.id}")
    db.commit()


def list_users(db: DB) -> Sequence[User]:
    return db.scalars(select(User).order_by(func.lower(User.display_name))).all()


def list_open_invites(db: DB, now: datetime) -> Sequence[Invite]:
    stmt = (
        select(Invite)
        .where(Invite.used_at.is_(None), Invite.expires_at > now)
        .order_by(Invite.created_at.desc())
    )
    return db.scalars(stmt).all()


def recent_audit(db: DB, limit: int) -> list[dict[str, Any]]:
    """Audit entries with the people involved resolved to display names."""
    entries = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
    targets = {e.id: int(e.target[5:]) for e in entries if e.target and e.target.startswith("user:")}
    ids = {e.actor_id for e in entries if e.actor_id} | set(targets.values())
    names = dict(db.execute(select(User.id, User.display_name).where(User.id.in_(ids))).tuples().all())
    return [
        {
            "id": e.id,
            "at": e.at,
            "action": e.action,
            "actor": names.get(e.actor_id) if e.actor_id else None,
            "target": names.get(targets[e.id], e.target) if e.id in targets else e.target,
            "details": e.details,
        }
        for e in entries
    ]
