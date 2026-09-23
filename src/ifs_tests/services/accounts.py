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
from ..db.models import POSITIONS, ROLES, STATUSES, VERTICALS, AuditLog, Invite, PasswordReset, User
from ..domain import accounts as rules
from ..domain import xp as xp_rules
from .errors import UserError

INVITE_TTL = timedelta(days=7)
RESET_TTL = timedelta(hours=24)
LOGIN_FAILED = (
    f"Wrong email or password. After {rules.LOCK_AFTER} failed attempts the account is locked for "
    f"{rules.LOCK_FOR.seconds // 60} minutes; an admin can send you a reset link."
)
NAME_RULE = "Use 2–24 Latin letters, numbers, spaces, dots, dashes or apostrophes."


class AccountError(UserError):
    pass


def audit(db: DB, actor: User | None, action: str, target: str | None = None, **details: Any) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, target=target, details=details))


def _name_taken(db: DB, name: str, exclude_user: int | None = None) -> bool:
    """Compares skeletons, so look-alikes of an existing name count as taken. A team has at most a few
    hundred members; the unique index on lower(display_name) still guards exact duplicates in a race."""
    skeleton = rules.name_skeleton(name)
    return any(
        uid != exclude_user and rules.name_skeleton(other) == skeleton
        for uid, other in db.execute(select(User.id, User.display_name)).tuples()
    )


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
    position: str = "mingo",
) -> tuple[User, str]:
    if position not in POSITIONS:
        raise AccountError(UNKNOWN_POSITION, fields={"position": "Pick where you are on the team."})
    open_invite(db, token, now)
    email, name = _check_new_user(db, email, display_name, password)
    vertical = _check_vertical(vertical)
    db.rollback()  # no transaction or connection held while hashing
    hashed = hash_password(password)
    with _unique(db):
        invite = open_invite(db, token, now, lock=True)
        user = User(
            email=email,
            password_hash=hashed,
            display_name=name,
            vertical=invite.vertical or vertical,
            role=invite.role,
            position=position,
            xp=xp_rules.floor_for(position),
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
    db.rollback()
    hashed = hash_password(password)
    with _unique(db):
        user = User(email=email, password_hash=hashed, display_name=name, role="admin", created_at=now)
        db.add(user)
        db.flush()
        audit(db, user, "user.bootstrap_admin", f"user:{user.id}")
        db.commit()
    return user


# Sign-in


def login(db: DB, email: str, password: str, now: datetime, old_session: str | None) -> tuple[User, str]:
    """Check the credentials and start a new session; the old one, if any, is ended (no fixation).
    The hash is checked with no transaction open; the row is locked only to record the outcome."""
    found = db.execute(select(User.id, User.password_hash).where(User.email == email.strip().lower())).first()
    db.rollback()
    matches = verify_password(found.password_hash if found else dummy_hash(), password)
    if found is None:
        raise AccountError(LOGIN_FAILED, 401)
    user = db.get_one(User, found.id, with_for_update=True, populate_existing=True)
    if rules.is_locked(user.locked_until, now) or user.status != "active":
        db.rollback()
        raise AccountError(LOGIN_FAILED, 401)
    if not matches:
        _record_failure(db, user, now)
        raise AccountError(LOGIN_FAILED, 401)
    user.failed_logins, user.locked_until = 0, None
    if old_session:
        end_session(db, old_session)
    session = create_session(db, user, now)
    db.commit()
    if needs_rehash(user.password_hash):
        rehashed = hash_password(password)
        db.execute(update(User).where(User.id == user.id).values(password_hash=rehashed))
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


def _check_password(user: User, password: str, field: str = "password") -> None:
    if problem := password_problem(password, email=user.email, display_name=user.display_name):
        raise AccountError(problem, fields={field: problem})


def reset_password(db: DB, token: str, password: str, now: datetime) -> User:
    _check_password(db.get_one(User, open_reset(db, token, now).user_id), password)
    db.rollback()
    hashed = hash_password(password)
    reset = open_reset(db, token, now, lock=True)
    user = db.get_one(User, reset.user_id, with_for_update=True)
    user.password_hash = hashed
    user.failed_logins, user.locked_until = 0, None
    _close_resets(db, user.id, now)
    end_all_sessions(db, user.id)
    audit(db, user, "password.reset", f"user:{user.id}", reset=reset.id)
    db.commit()
    return user


def change_password(db: DB, user: User, current: str, new: str, keep_token: str, now: datetime) -> None:
    if rules.is_locked(user.locked_until, now):
        raise AccountError("Too many wrong attempts. Try again in 15 minutes.", 429)
    _check_password(user, new, field="new_password")
    stored = user.password_hash
    db.rollback()
    matches = verify_password(stored, current)
    hashed = hash_password(new) if matches else None
    # Re-read under a row lock: parallel wrong guesses must each count, and none may slip past a lock.
    user = db.get_one(User, user.id, with_for_update=True, populate_existing=True)
    if rules.is_locked(user.locked_until, now):
        db.rollback()
        raise AccountError("Too many wrong attempts. Try again in 15 minutes.", 429)
    if hashed is None:
        _record_failure(db, user, now)
        raise AccountError("Your current password is wrong.", 403, {"current_password": "Wrong password."})
    user.password_hash = hashed
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


UNKNOWN_POSITION = "Unknown position on the team."


def _set_position(db: DB, user: User, position: str) -> None:
    """A new position moves the starting level; XP only ever goes up to meet it. Done in SQL so XP granted
    by an answer at the same moment isn't overwritten."""
    if position not in POSITIONS:
        raise AccountError(UNKNOWN_POSITION, fields={"position": "Pick where they are on the team."})
    user.position = position
    user.xp = db.execute(
        update(User)
        .where(User.id == user.id)
        .values(position=position, xp=func.greatest(User.xp, xp_rules.floor_for(position)))
        .returning(User.xp)
    ).scalar_one()


def update_user(
    db: DB,
    actor: User,
    user_id: int,
    role: str | None = None,
    status: str | None = None,
    position: str | None = None,
) -> User:
    if user_id == actor.id and (role is not None or status is not None):
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
    if position is not None and position != user.position:
        changes["position"] = [user.position, position]
        _set_position(db, user, position)
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


def list_users(db: DB) -> list[User]:
    return sorted(db.scalars(select(User)), key=lambda u: (rules.sort_key(u.display_name), u.id))


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
