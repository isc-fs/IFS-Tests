from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, or_
from sqlalchemy.orm import Session as DB

from ..auth.sessions import purge_expired
from ..db.models import Invite, PasswordReset
from . import daily, live, mock, privacy, season, streaks, xp

KEEP_CLOSED_LINKS = timedelta(days=30)


def run(db: DB, now: datetime) -> dict[str, int]:
    """Nightly clean-up. Idempotent, safe to run at any time."""
    cutoff = now - KEEP_CLOSED_LINKS
    invites = db.execute(delete(Invite).where(or_(Invite.used_at < cutoff, Invite.expires_at < cutoff)))
    resets = db.execute(
        delete(PasswordReset).where(or_(PasswordReset.used_at < cutoff, PasswordReset.expires_at < cutoff))
    )
    counts = {
        "sessions": purge_expired(db, now),
        "invites": cast(CursorResult[Any], invites).rowcount,
        "resets": cast(CursorResult[Any], resets).rowcount,
        "dailies_closed": daily.close_expired(db, now),
        "mock_questions_closed": mock.close_expired(db, now),
        "mock_runs_ended": mock.end_stale(db, now),
        "live_sessions_finished": live.finish_abandoned(db, now),
        "live_answers_shared": live.share_pending(db, now),
        "difficulty_changed": xp.recalibrate(db),
        "ranks_reset": season.rollover(db, now),
        **streaks.nightly(db, now),
        **privacy.purge(db, now),
    }
    db.commit()
    return counts
