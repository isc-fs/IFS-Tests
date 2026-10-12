"""The second person's step of the integrity review (docs/guides/integrity-report.md): who is behind the
pseudonyms the report flagged. The only integrity module that reads a name, and only for the pseudonyms named."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from ..db.models import User
from ..domain import integrity as rules


def reveal(
    db: DB, salt: bytes, pseudonyms: Sequence[str], *, include_alumni: bool
) -> list[tuple[str, int, str]]:
    """(pseudonym, user id, display name) for the pseudonyms named, active members first, then alumni when
    asked; nothing else."""
    wanted = {p.strip().lower() for p in pseudonyms}
    statuses = ("active", "alumni") if include_alumni else ("active",)
    found = [
        (rules.pseudonym(salt, uid), uid, name, status)
        for uid, name, status in db.execute(
            select(User.id, User.display_name, User.status).where(User.status.in_(statuses)).order_by(User.id)
        )
    ]
    hits = [f for f in found if f[0] in wanted]
    hits.sort(key=lambda f: (f[3] != "active", f[1]))
    return [(p, uid, name) for p, uid, name, _ in hits]
