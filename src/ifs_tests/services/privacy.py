"""Personal data (ADR 0006): what a member can download about themselves, deleting an account, alumni."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session as DB

from ..auth.passwords import verify_password
from ..auth.sessions import end_all_sessions
from ..db.models import (
    Attempt,
    AuditLog,
    Invite,
    LiveAnswer,
    LivePlayer,
    LiveProposal,
    LiveSession,
    LiveTable,
    MockSession,
    PasswordReset,
    PracticeHint,
    Question,
    Report,
    Session,
    StreakFreeze,
    User,
)
from ..domain import accounts as rules
from ..domain import rank as rank_rules
from . import live
from .accounts import AccountError, _active_admin_ids, _record_failure, audit, check_still_admin

NOT_CONFIRMED = "Your password is wrong."
EXPORTS_AT_ONCE = 2  # per api process
_exporting = threading.BoundedSemaphore(EXPORTS_AT_ONCE)


@contextmanager
def export_slot() -> Iterator[None]:
    """Hold one of the process's export slots while an export is prepared and written out: each holds a
    member's whole history in memory, and a burst of downloads would take the api past its memory limit."""
    if not _exporting.acquire(blocking=False):
        raise AccountError("Another download is being prepared. Try again in a minute.", 429)
    try:
        yield
    finally:
        _exporting.release()


def export(db: DB, user: User, now: datetime) -> dict[str, Any]:
    """Everything stored about `user`, as they could read it back. Nothing that reveals an answer early:
    right and wrong stay hidden for a mock run still going and a live quiz not finished."""
    open_runs = set(
        db.scalars(
            select(MockSession.id).where(MockSession.user_id == user.id, MockSession.finished_at.is_(None))
        )
    )
    running = set(db.scalars(select(LiveSession.id).where(LiveSession.state != "finished")))

    # Only the columns the file shows, in batches, and each question's text once: a member's whole history
    # as ORM rows took tens of MiB per download (PERF-04).
    texts = {
        qid: text
        for qid, text in db.execute(
            select(Question.id, Question.text).where(
                Question.id.in_(select(Attempt.question_id).where(Attempt.user_id == user.id))
            )
        )
    }
    rows = db.execute(
        select(
            Attempt.question_id,
            Attempt.mode,
            Attempt.area,
            Attempt.answer,
            Attempt.correct,
            Attempt.passed,
            Attempt.hint_used,
            Attempt.xp,
            Attempt.lp,
            Attempt.late,
            Attempt.day,
            Attempt.created_at,
            Attempt.submitted_at,
            Attempt.session_id,
            Attempt.live_session_id,
        )
        .where(Attempt.user_id == user.id)
        .order_by(Attempt.created_at, Attempt.id)
        .execution_options(yield_per=1000)
    )
    attempts = []
    for a in rows:
        hidden = a.session_id in open_runs or a.live_session_id in running
        attempts.append(
            {
                "question_id": a.question_id,
                "question": texts[a.question_id],
                "mode": a.mode,
                "area": a.area,
                "answer": a.answer,
                "correct": None if hidden else a.correct,
                "passed": a.passed,
                "hint_used": a.hint_used,
                "xp": 0 if hidden else a.xp,
                "lp": 0.0 if hidden else a.lp,
                "late": a.late,
                "day": a.day,
                "started_at": a.created_at,
                "submitted_at": a.submitted_at,
            }
        )
    mock_runs = [
        {
            "quiz_id": m.quiz_id,
            "season": m.season,
            "counted": m.counted,
            "started_at": m.started_at,
            "finished_at": m.finished_at,
            "unreached": m.unreached,
            "unreached_graded": m.unreached_graded,
        }
        for m in db.scalars(
            select(MockSession).where(MockSession.user_id == user.id).order_by(MockSession.id)
        )
    ]
    sessions = db.execute(
        select(
            LiveSession.code,
            LiveSession.created_at,
            LivePlayer.joined_at,
            LivePlayer.removed,
            LiveTable.name,
            LiveTable.captain_id == user.id,
        )
        .join(LivePlayer, LivePlayer.session_id == LiveSession.id)
        .outerjoin(LiveTable, LiveTable.id == LivePlayer.table_id)
        .where(LivePlayer.user_id == user.id)
        .order_by(LiveSession.id)
    ).all()
    hosted = db.scalars(select(LiveSession).where(LiveSession.host_id == user.id).order_by(LiveSession.id))
    invite = db.scalar(select(Invite).where(Invite.used_by == user.id))
    sent = [
        {
            "code": code,
            "question": a.position + 1,
            "answer": a.answer,
            "correct": None if a.session_id in running else a.correct,
            "submitted_at": a.submitted_at,
        }
        for a, code in db.execute(
            select(LiveAnswer, LiveSession.code)
            .join(LiveSession, LiveSession.id == LiveAnswer.session_id)
            .where(LiveAnswer.by_user_id == user.id)
            .order_by(LiveAnswer.submitted_at)
        ).tuples()
    ]
    proposals = [
        {"code": code, "question": p.position + 1, "answer": p.answer, "at": p.updated_at}
        for p, code in db.execute(
            select(LiveProposal, LiveSession.code)
            .join(LiveSession, LiveSession.id == LiveProposal.session_id)
            .where(LiveProposal.user_id == user.id)
        ).tuples()
    ]
    return {
        "exported_at": now,
        "account": {
            "email": user.email,
            "display_name": user.display_name,
            "vertical": user.vertical,
            "subdepartments": list(user.subdepartments),
            "position": user.position,
            "role": user.role,
            "status": user.status,
            "xp": user.xp,
            "xp_before_ranked": user.legacy_xp,
            "rank_points": user.rank_points,
            "rank_season": user.rank_season,
            "best_division": rank_rules.title(user.rank_best, user.vertical),
            "position_lifts": user.position_lifts,
            "right_in_a_row": user.combo,
            "wrong_in_a_row": user.miss_streak,
            "rested_xp": user.rested_xp,
            "rested_on": user.rested_on,
            "streak_freezes": user.streak_freezes,
            "streak_freeze_earned_on": user.freeze_earned_on,
            "hidden_from_leaderboard": user.leaderboard_opt_out,
            "joined_at": user.created_at,
            "last_seen": user.last_seen,
            "failed_sign_ins": user.failed_logins,
            "locked_until": user.locked_until,
            "inactive_since": user.left_at,
            "deleted_on": user.left_at + rules.ALUMNI_KEEP if user.left_at else None,
        },
        # Kept 30 days after it was used.
        "invite": invite
        and {
            "role": invite.role,
            "vertical": invite.vertical,
            "note": invite.note,
            "used_at": invite.used_at,
        },
        "pending_hints": list(
            db.scalars(select(PracticeHint.question_id).where(PracticeHint.user_id == user.id))
        ),
        "answers": attempts,
        "mock_runs": mock_runs,
        "live": {
            "joined": [
                {
                    "code": code,
                    "created_at": created,
                    "joined_at": joined,
                    "removed_by_host": removed,
                    "table": table,
                    "captain": bool(captain),
                }
                for code, created, joined, removed, table, captain in sessions
            ],
            "hosted": [
                {"code": s.code, "created_at": s.created_at, "finished_at": s.finished_at} for s in hosted
            ],
            "answers_sent_as_captain": sent,
            "proposals": proposals,
        },
        "reports": [
            {
                "question_id": r.question_id,
                "message": r.message,
                "at": r.created_at,
                "handled_at": r.resolved_at,
            }
            for r in db.scalars(select(Report).where(Report.user_id == user.id).order_by(Report.id))
        ],
        "streak_freezes_used": list(
            db.scalars(
                select(StreakFreeze.day).where(StreakFreeze.user_id == user.id).order_by(StreakFreeze.day)
            )
        ),
        # Reset links an admin made for them, without the token hash.
        "password_resets": [
            {"created_at": r.created_at, "expires_at": r.expires_at, "used_at": r.used_at}
            for r in db.scalars(
                select(PasswordReset).where(PasswordReset.user_id == user.id).order_by(PasswordReset.id)
            )
        ],
        "sign_ins": [
            {"started_at": s.created_at, "last_seen": s.last_seen, "expires_at": s.expires_at}
            for s in db.scalars(
                select(Session).where(Session.user_id == user.id).order_by(Session.created_at)
            )
        ],
        "account_history": [
            {"at": e.at, "action": e.action, "details": e.details}
            for e in db.scalars(
                select(AuditLog).where(AuditLog.target == f"user:{user.id}").order_by(AuditLog.id)
            )
        ],
        # What they did as an admin or reviewer; other people's accounts show as "user" only.
        "actions": [
            {
                "at": e.at,
                "action": e.action,
                "on": e.target
                if e.target and e.target.startswith("question:")
                else (e.target or "").split(":")[0],
            }
            for e in db.scalars(select(AuditLog).where(AuditLog.actor_id == user.id).order_by(AuditLog.id))
        ],
    }


def export_for(db: DB, actor: User, user_id: int, now: datetime) -> dict[str, Any]:
    """An admin fetching the export for someone who can't sign in (alumni, disabled)."""
    user = db.get(User, user_id)
    if user is None:
        raise AccountError("No such user.", 404)
    data = export(db, user, now)
    audit(db, actor, "user.export", f"user:{user.id}")
    db.commit()
    return data


@dataclass
class Locked:
    """What deleting an account locks, in this order: sessions it hosts (as answering does), admin rows (as
    every admin change does), then the account. Two admins leaving at once queue up; the second finds it
    would leave no admin."""

    sessions: list[LiveSession]
    admins: list[int]
    user: User | None


def _lock(db: DB, user_id: int) -> Locked:
    sessions = live.lock_hosted(db, user_id)
    admins = _active_admin_ids(db)
    return Locked(sessions, admins, db.get(User, user_id, with_for_update=True, populate_existing=True))


def _guard_last_admin(admins: list[int], user: User) -> None:
    if user.id in admins and len(admins) <= 1:
        raise AccountError("You're the only admin. Make someone else an admin first.", 409)


def _delete(db: DB, user: User, sessions: list[LiveSession], now: datetime) -> None:
    """Remove the account and everything that points to it. Other people's results stay: live sessions
    lose their host, tables their captain, and the account leaves the lists of who shared a table's XP."""
    live.finish(db, sessions, now)
    db.execute(
        update(LiveAnswer)
        .where(LiveAnswer.member_ids.contains([user.id]))
        .values(member_ids=func.array_remove(LiveAnswer.member_ids, user.id))
    )
    db.execute(update(Invite).where(Invite.used_by == user.id).values(note=None))  # it named them
    db.delete(user)


def delete_self(db: DB, user: User, password: str, now: datetime) -> None:
    if rules.is_locked(user.locked_until, now):
        raise AccountError("Too many wrong attempts. Try again in 15 minutes.", 429)
    stored = user.password_hash
    db.rollback()  # no transaction held while hashing
    matches = verify_password(stored, password)
    locked = _lock(db, user.id)
    if locked.user is None:
        raise AccountError("This account no longer exists.", 404)
    if rules.is_locked(locked.user.locked_until, now):  # locked by guesses made meanwhile
        db.rollback()
        raise AccountError("Too many wrong attempts. Try again in 15 minutes.", 429)
    if not matches:
        _record_failure(db, locked.user, now)
        raise AccountError(NOT_CONFIRMED, 403, {"password": NOT_CONFIRMED})
    _guard_last_admin(locked.admins, locked.user)
    audit(db, None, "user.delete", f"user:{user.id}", by="self")
    _delete(db, locked.user, locked.sessions, now)
    db.commit()
    for s in locked.sessions:  # the sessions they hosted are over: their players' XP goes out
        live.share(db, s.id, now)


def delete_user(db: DB, actor: User, user_id: int, now: datetime) -> None:
    if user_id == actor.id:
        raise AccountError("Delete your own account from your profile.", 403)
    locked = _lock(db, user_id)
    check_still_admin(actor, locked.admins)
    if locked.user is None:
        raise AccountError("No such user.", 404)
    _guard_last_admin(locked.admins, locked.user)
    audit(db, actor, "user.delete", f"user:{user_id}", by="admin")
    _delete(db, locked.user, locked.sessions, now)
    db.commit()
    for s in locked.sessions:
        live.share(db, s.id, now)


def mark_alumni(db: DB, actor: User, user_ids: list[int], now: datetime) -> int:
    """Season rollover: people who left the team. Signed out, off the boards, deleted in a year."""
    # Admin rows first, as every admin change: the acting admin must still be one, and stays one.
    check_still_admin(actor, _active_admin_ids(db))
    ids = set(user_ids) - {actor.id}
    users = db.scalars(
        select(User).where(User.id.in_(ids), User.status != "alumni").order_by(User.id).with_for_update()
    ).all()
    for u in users:
        audit(db, actor, "user.update", f"user:{u.id}", status=[u.status, "alumni"])
        u.status, u.left_at = "alumni", u.left_at or now
        end_all_sessions(db, u.id)
    db.commit()
    return len(users)


def purge(db: DB, now: datetime) -> dict[str, int]:
    """Nightly: accounts a year after they stopped being active, and audit entries past their keep."""
    # An account made inactive by an older release, mid-deploy, has no date yet: its year starts now.
    db.execute(update(User).where(User.status != "active", User.left_at.is_(None)).values(left_at=now))
    due = db.scalars(
        select(User.id).where(User.status != "active", User.left_at <= now - rules.ALUMNI_KEEP)
    ).all()
    deleted = 0
    for uid in due:
        locked = _lock(db, uid)
        if locked.user is None or locked.user.status == "active":  # reactivated meanwhile
            continue
        audit(db, None, "user.delete", f"user:{uid}", by="retention")
        _delete(db, locked.user, locked.sessions, now)
        deleted += 1
    # The app can't delete from the audit log; this function removes only entries past the keep.
    old = db.scalar(text("SELECT purge_audit_log(:before)"), {"before": now - rules.AUDIT_KEEP}) or 0
    return {"alumni_deleted": deleted, "audit_purged": old}
