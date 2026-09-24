from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from ...services import accounts, bank, privacy
from ..deps import Admin, AppSettings, Db, Now
from ..schemas import (
    AdminUser,
    AlumniIn,
    AlumniOut,
    AuditEntry,
    BankSummary,
    Export,
    InviteIn,
    Link,
    OpenInvite,
    UserPatch,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])
Id = Annotated[int, Path(ge=1, le=2**31 - 1)]


@router.get("/users")
def users(_: Admin, db: Db) -> list[AdminUser]:
    return [AdminUser.model_validate(u) for u in accounts.list_users(db)]


@router.patch("/users/{user_id}")
def update_user(user_id: Id, body: UserPatch, admin: Admin, db: Db, now: Now) -> AdminUser:
    return AdminUser.model_validate(
        accounts.update_user(
            db,
            admin,
            user_id,
            role=body.role,
            status=body.status,
            position=body.position,
            now=now,
            email=body.email,
        )
    )


@router.get("/users/{user_id}/export")
def export_user(user_id: Id, admin: Admin, db: Db, now: Now, response: Response) -> Export:
    """For someone who can't sign in (alumni, disabled) and asks for their data."""
    response.headers["Content-Disposition"] = (
        f'attachment; filename="mingoquiz-export-{user_id}-{now.date()}.json"'
    )
    return Export.model_validate(privacy.export_for(db, admin, user_id, now))


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: Id, admin: Admin, db: Db, now: Now) -> None:
    privacy.delete_user(db, admin, user_id, now)


@router.post("/alumni")
def mark_alumni(body: AlumniIn, admin: Admin, db: Db, now: Now) -> AlumniOut:
    return AlumniOut(marked=privacy.mark_alumni(db, admin, body.user_ids, now))


@router.post("/users/{user_id}/reset-link", status_code=201)
def reset_link(user_id: Id, admin: Admin, db: Db, now: Now, settings: AppSettings) -> Link:
    token = accounts.create_reset(db, admin, user_id, now)
    return Link(url=settings.link("reset", token), expires_at=now + accounts.RESET_TTL)


@router.post("/users/{user_id}/revoke-sessions", status_code=204)
def revoke_sessions(user_id: Id, admin: Admin, db: Db) -> None:
    accounts.revoke_sessions(db, admin, user_id)


@router.get("/invites")
def open_invites(_: Admin, db: Db, now: Now) -> list[OpenInvite]:
    return [OpenInvite.model_validate(i) for i in accounts.list_open_invites(db, now)]


@router.post("/invites", status_code=201)
def create_invite(body: InviteIn, admin: Admin, db: Db, now: Now, settings: AppSettings) -> Link:
    token, invite = accounts.create_invite(
        db, admin, now, role=body.role, vertical=body.vertical, note=body.note
    )
    return Link(url=settings.link("invite", token), expires_at=invite.expires_at)


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: Id, admin: Admin, db: Db, now: Now) -> None:
    accounts.revoke_invite(db, admin, invite_id, now)


@router.get("/audit")
def audit_log(_: Admin, db: Db, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[AuditEntry]:
    return [AuditEntry.model_validate(e) for e in accounts.recent_audit(db, limit)]


@router.get("/bank")
def bank_summary(_: Admin, db: Db) -> BankSummary:
    return BankSummary.model_validate(bank.summary(db))
