from __future__ import annotations

from fastapi import APIRouter, Request

from ...services import accounts
from ..deps import AppSettings, Db, Member, Now
from ..schemas import Me, PasswordChangeIn, ProfileIn

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("")
def me(user: Member) -> Me:
    return Me.model_validate(user)


@router.patch("")
def update_me(body: ProfileIn, user: Member, db: Db) -> Me:
    return Me.model_validate(accounts.update_profile(db, user, body.model_dump(exclude_unset=True)))


@router.post("/password", status_code=204)
def change_password(
    body: PasswordChangeIn, request: Request, user: Member, db: Db, now: Now, settings: AppSettings
) -> None:
    keep = request.cookies[settings.session_cookie]
    accounts.change_password(db, user, body.current_password, body.new_password, keep, now)
