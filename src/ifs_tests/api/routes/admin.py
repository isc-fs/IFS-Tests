from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ...db.models import AuditLog, Invite, User
from ...services import accounts
from ...settings import get_settings
from ..deps import Admin, Db, Now
from ..schemas import AdminUser, AuditEntry, InviteCreated, InviteIn, OpenInvite, ResetLink, UserPatch

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _link(path: str, token: str) -> str:
    return f"{get_settings().public_origin.rstrip('/')}/{path}/{token}"


def _fail(e: accounts.AccountError) -> HTTPException:
    return HTTPException(e.status, e.message)


@router.get("/users")
def users(_: Admin, db: Db) -> list[AdminUser]:
    rows = db.scalars(select(User).order_by(User.display_name))
    return [AdminUser.model_validate(u) for u in rows]


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, admin: Admin, db: Db) -> AdminUser:
    try:
        return AdminUser.model_validate(
            accounts.update_user(db, admin, user_id, role=body.role, status=body.status)
        )
    except accounts.AccountError as e:
        raise _fail(e) from None


@router.post("/users/{user_id}/reset-link", status_code=201)
def reset_link(user_id: int, admin: Admin, db: Db, now: Now) -> ResetLink:
    try:
        token = accounts.create_reset(db, admin, user_id, now)
    except accounts.AccountError as e:
        raise _fail(e) from None
    return ResetLink(url=_link("reset", token), expires_at=now + accounts.RESET_TTL)


@router.post("/users/{user_id}/revoke-sessions", status_code=204)
def revoke_sessions(user_id: int, admin: Admin, db: Db) -> None:
    try:
        accounts.revoke_sessions(db, admin, user_id)
    except accounts.AccountError as e:
        raise _fail(e) from None


@router.get("/invites")
def open_invites(_: Admin, db: Db, now: Now) -> list[OpenInvite]:
    rows = db.scalars(
        select(Invite)
        .where(Invite.used_at.is_(None), Invite.expires_at > now)
        .order_by(Invite.created_at.desc())
    )
    return [OpenInvite.model_validate(i) for i in rows]


@router.post("/invites", status_code=201)
def create_invite(body: InviteIn, admin: Admin, db: Db, now: Now) -> InviteCreated:
    try:
        token, invite = accounts.create_invite(
            db, admin, now, role=body.role, vertical=body.vertical, note=body.note
        )
    except accounts.AccountError as e:
        raise _fail(e) from None
    return InviteCreated(url=_link("invite", token), expires_at=invite.expires_at)


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: int, admin: Admin, db: Db, now: Now) -> None:
    try:
        accounts.revoke_invite(db, admin, invite_id, now)
    except accounts.AccountError as e:
        raise _fail(e) from None


@router.get("/audit")
def audit_log(_: Admin, db: Db, limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[AuditEntry]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    return [AuditEntry.model_validate(a) for a in rows]
