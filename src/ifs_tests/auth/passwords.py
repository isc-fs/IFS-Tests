from __future__ import annotations

import threading
from functools import cache
from importlib.resources import files

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 10
MAX_LENGTH = 128

# OWASP's Argon2id profile (19 MiB, 2 passes). Hashing releases the GIL, so without a cap a burst of
# logins would allocate 19 MiB each in parallel; two at a time per worker keeps memory flat.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
_slots = threading.BoundedSemaphore(2)


def hash_password(password: str) -> str:
    with _slots:
        return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        with _slots:
            return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@cache
def dummy_hash() -> str:
    """Verified against when no real check happens, so response time doesn't reveal accounts."""
    return _hasher.hash("not-a-real-password-just-timing")


@cache
def _common() -> frozenset[str]:
    # NCSC 100k most-used passwords (SecLists, MIT), filtered to 10+ characters and lowercased.
    text = files("ifs_tests.auth").joinpath("common_passwords.txt").read_text(encoding="utf-8")
    return frozenset(text.splitlines())


def password_problem(password: str, *, email: str = "", display_name: str = "") -> str | None:
    """Why a new password is not acceptable, or None."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    lowered = password.lower()
    if lowered in _common():
        return "That password is too common. Pick something less predictable."
    for part in (email.split("@")[0], display_name):
        if len(part) >= 4 and part.lower() in lowered:
            return "Don't include your email or display name in the password."
    return None
