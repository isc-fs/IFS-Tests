from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from functools import cache
from importlib.resources import files

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 10
MAX_LENGTH = 128
WAIT_SECONDS = 10

# OWASP's Argon2id profile (19 MiB, 2 passes). All hashing runs on two dedicated threads: glibc keeps
# a memory arena per thread that ever hashed, so hashing on the web server's 40-thread pool would pin
# 19 MiB per thread. Callers must not hold database locks or connections while they wait.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="argon2")


class HashingBusy(Exception):
    """Too many password checks queued: the caller should answer 503 instead of piling up."""


def _run[T](call: Callable[[], T]) -> T:
    future = _pool.submit(call)
    try:
        return future.result(timeout=WAIT_SECONDS)
    except FutureTimeout:
        future.cancel()
        raise HashingBusy from None


def hash_password(password: str) -> str:
    return _run(lambda: _hasher.hash(password))


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_password(password_hash: str, password: str) -> bool:
    return _run(lambda: _verify(password_hash, password))


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
