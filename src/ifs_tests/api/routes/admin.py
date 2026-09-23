from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from ...services import accounts, bank
from ..deps import Admin, AppSettings, Db, Now
from ..schemas import AdminUser, AuditEntry, BankSummary, InviteIn, Link, OpenInvite, UserPatch

router = APIRouter(prefix="/api/admin", tags=["admin"])
Id = Annotated[int, Path(ge=1, le=2**31 - 1)]


@router.get("/users")
def users(_: Admin, db: Db) -> list[AdminUser]:
    return [AdminUser.model_validate(u) for u in accounts.list_users(db)]


@router.patch("/users/{user_id}")
def update_user(user_id: Id, body: UserPatch, admin: Admin, db: Db) -> AdminUser:
    return AdminUser.model_validate(
        accounts.update_user(db, admin, user_id, role=body.role, status=body.status)
    )


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
