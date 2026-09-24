"""Personal data (ADR 0006): what a member can download about themselves, deleting an account, alumni."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
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
    PracticeHint,
    Question,
    Report,
    Session,
    User,
)
from ..db.session import rowcount
from ..domain import accounts as rules
from . import live
from .accounts import AccountError, _active_admin_ids, _record_failure, audit

NOT_CONFIRMED = "Your password is wrong."


def export(db: DB, user: User, now: datetime) -> dict[str, Any]:
    """Everything stored about `user`, as they could read it back. Nothing that reveals an answer early:
    right and wrong stay hidden for a mock run still going and a live quiz not finished."""
    open_runs = set(
        db.scalars(
            select(MockSession.id).where(MockSession.user_id == user.id, MockSession.finished_at.is_(None))
        )
    )
    running = set(db.scalars(select(LiveSession.id).where(LiveSession.state != "finished")))

    def hidden(a: Attempt) -> bool:
        return a.session_id in open_runs or a.live_session_id in running

    attempts = [
        {
            "question_id": q.id,
            "question": q.text,
            "mode": a.mode,
            "area": a.area,
            "answer": a.answer,
            "correct": None if hidden(a) else a.correct,
            "passed": a.passed,
            "hint_used": a.hint_used,
            "xp": 0 if hidden(a) else a.xp,
            "late": a.late,
            "day": a.day,
            "started_at": a.created_at,
            "submitted_at": a.submitted_at,
        }
        for a, q in db.execute(
            select(Attempt, Question)
            .join(Question, Question.id == Attempt.question_id)
            .where(Attempt.user_id == user.id)
            .order_by(Attempt.created_at, Attempt.id)
        ).tuples()
    ]
    mock_runs = [
        {
            "quiz_id": m.quiz_id,
            "season": m.season,
            "counted": m.counted,
            "started_at": m.started_at,
            "finished_at": m.finished_at,
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


def delete_user(db: DB, actor: User, user_id: int, now: datetime) -> None:
    if user_id == actor.id:
        raise AccountError("Delete your own account from your profile.", 403)
    locked = _lock(db, user_id)
    if locked.user is None:
        raise AccountError("No such user.", 404)
    _guard_last_admin(locked.admins, locked.user)
    audit(db, actor, "user.delete", f"user:{user_id}", by="admin")
    _delete(db, locked.user, locked.sessions, now)
    db.commit()


def mark_alumni(db: DB, actor: User, user_ids: list[int], now: datetime) -> int:
    """Season rollover: people who left the team. Signed out, off the boards, deleted in a year."""
    # Admin rows first, as every admin change: the acting admin must still be one, and stays one.
    if actor.id not in _active_admin_ids(db):
        raise AccountError("Only an active admin can do this.", 403)
    ids = set(user_ids) - {actor.id}
    users = db.scalars(select(User).where(User.id.in_(ids), User.status != "alumni").with_for_update()).all()
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
    old = rowcount(db.execute(delete(AuditLog).where(AuditLog.at < now - rules.AUDIT_KEEP)))
    return {"alumni_deleted": deleted, "audit_purged": old}
