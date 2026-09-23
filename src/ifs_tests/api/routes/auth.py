"""Public endpoints. Invite and reset tokens travel in POST bodies (the SPA reads them from the URL
fragment), so they never appear in access logs."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ...auth.sessions import end_session
from ...domain.accounts import SESSION_ABSOLUTE
from ...services import accounts
from ...settings import Settings
from ..deps import AppSettings, Db, Now
from ..schemas import InviteInfo, LoginIn, Me, RegisterIn, ResetIn, ResetInfo, TokenIn

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(
    response: Response, settings: Settings, token: str, max_age: int = int(SESSION_ABSOLUTE.total_seconds())
) -> None:
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=max_age,
        path="/",
        secure=settings.https,
        httponly=True,
        samesite="lax",
    )


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Db, now: Now, settings: AppSettings) -> Me:
    old = request.cookies.get(settings.session_cookie)
    user, token = accounts.login(db, body.email, body.password, now, old)
    _set_cookie(response, settings, token)
    return Me.model_validate(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Db, settings: AppSettings) -> None:
    if token := request.cookies.get(settings.session_cookie):
        end_session(db, token)
        db.commit()
    _set_cookie(response, settings, "", max_age=0)


@router.post("/invites/lookup")
def invite_info(body: TokenIn, db: Db, now: Now) -> InviteInfo:
    return InviteInfo.model_validate(accounts.open_invite(db, body.token, now))


@router.post("/register", status_code=201)
def register(body: RegisterIn, response: Response, db: Db, now: Now, settings: AppSettings) -> Me:
    user, token = accounts.register(
        db, body.token, body.email, body.display_name, body.password, now, body.vertical
    )
    _set_cookie(response, settings, token)
    return Me.model_validate(user)


@router.post("/resets/lookup")
def reset_info(body: TokenIn, db: Db, now: Now) -> ResetInfo:
    return ResetInfo.model_validate(accounts.open_reset(db, body.token, now))


@router.post("/reset", status_code=204)
def reset(body: ResetIn, db: Db, now: Now) -> None:
    accounts.reset_password(db, body.token, body.password, now)
