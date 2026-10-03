from __future__ import annotations

import hashlib
import secrets


def new_token() -> str:
    """256 bits, URL-safe. Used for session cookies, invite and reset links."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """Only this hash is stored, so a database leak doesn't expose usable tokens."""
    return hashlib.sha256(token.encode()).hexdigest()
