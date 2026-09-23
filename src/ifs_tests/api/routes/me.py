from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ...auth.sessions import COOKIE
from ...services import accounts
from ..deps import Db, Member
from ..schemas import Me, PasswordChangeIn, ProfileIn

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("")
def me(user: Member) -> Me:
    return Me.model_validate(user)


@router.patch("")
def update_me(body: ProfileIn, user: Member, db: Db) -> Me:
    try:
        accounts.update_profile(
            db,
            user,
            display_name=body.display_name,
            vertical=body.vertical,
            clear_vertical=body.clear_vertical,
            leaderboard_opt_out=body.leaderboard_opt_out,
        )
    except accounts.AccountError as e:
        raise HTTPException(e.status, e.message) from None
    return Me.model_validate(user)


@router.post("/password", status_code=204)
def change_password(body: PasswordChangeIn, request: Request, user: Member, db: Db) -> None:
    try:
        accounts.change_password(db, user, body.current_password, body.new_password, request.cookies[COOKIE])
    except accounts.AccountError as e:
        raise HTTPException(e.status, e.message) from None
