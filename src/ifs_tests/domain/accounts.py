"""Account rules as pure functions: no database, the current time is always passed in."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

SESSION_IDLE = timedelta(hours=12)
SESSION_ABSOLUTE = timedelta(days=30)
SESSION_TOUCH_EVERY = timedelta(minutes=5)
LOCK_AFTER = 5
LOCK_FOR = timedelta(minutes=15)

_DIGITS = set("0123456789")
_EMAIL = re.compile(r"^[^@\s\x00-\x1f]+@[^@\s\x00-\x1f]+\.[^@\s\x00-\x1f]+$")
_NAME_PUNCTUATION = set(" .'-")


class SessionState(Enum):
    EXPIRED = "expired"
    FRESH = "fresh"
    NEEDS_TOUCH = "needs_touch"


def session_state(expires_at: datetime, last_seen: datetime, now: datetime) -> SessionState:
    if now >= expires_at or now - last_seen >= SESSION_IDLE:
        return SessionState.EXPIRED
    return SessionState.NEEDS_TOUCH if now - last_seen >= SESSION_TOUCH_EVERY else SessionState.FRESH


def link_open(used_at: datetime | None, expires_at: datetime, now: datetime) -> bool:
    return used_at is None and now < expires_at


@dataclass(frozen=True)
class Lockout:
    failed: int
    locked_until: datetime | None


def after_failed_login(failed: int, now: datetime) -> Lockout:
    """The 5th consecutive failure locks the account and resets the counter."""
    failed += 1
    return Lockout(0, now + LOCK_FOR) if failed >= LOCK_AFTER else Lockout(failed, None)


def is_locked(locked_until: datetime | None, now: datetime) -> bool:
    return locked_until is not None and now < locked_until


def loses_admin(role: str, status: str, new_role: str | None, new_status: str | None) -> bool:
    """Would this change remove one of the active admins?"""
    if role != "admin" or status != "active":
        return False
    return (new_role is not None and new_role != "admin") or (
        new_status is not None and new_status != "active"
    )


def clean_email(email: str) -> str | None:
    email = email.strip().lower()
    return email if len(email) <= 254 and _EMAIL.match(email) else None


def clean_display_name(name: str) -> str | None:
    """NFKC-normalised, single-spaced, 2–24 characters of Latin letters, ASCII digits and . ' -.
    Latin-only blocks look-alike names built from Cyrillic or Greek letters or foreign digits."""
    name = " ".join(unicodedata.normalize("NFKC", name).split())
    if not 2 <= len(name) <= 24 or not name[0].isalnum():
        return None
    for ch in name:
        if ch in _NAME_PUNCTUATION or ch in _DIGITS:
            continue
        if not ch.isalpha() or not unicodedata.name(ch, "").startswith("LATIN"):
            return None
    return name


def sort_key(name: str) -> str:
    """Alphabetical order that ignores accents and case, so "Álvaro" sorts with the A's."""
    decomposed = unicodedata.normalize("NFKD", name).casefold()
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def name_skeleton(name: str) -> str:
    """What a name looks like, for uniqueness: accents, dotless i, case and punctuation are ignored,
    so "E2E Admın" and "e2e-admin" collide with "E2E Admin"."""
    decomposed = unicodedata.normalize("NFKD", name.replace("ı", "i")).casefold()
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))
