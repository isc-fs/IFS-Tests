from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from ...auth.sessions import ABSOLUTE, COOKIE, create_session, end_session
from ...services import accounts
from ..deps import Db, Now
from ..schemas import InviteInfo, LoginIn, Me, RegisterIn, ResetIn, ResetInfo

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(ABSOLUTE.total_seconds()),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _fail(e: accounts.AccountError) -> HTTPException:
    return HTTPException(e.status, e.message)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Db, now: Now) -> Me:
    try:
        user = accounts.authenticate(db, body.email, body.password, now)
    except accounts.AccountError as e:
        raise _fail(e) from None
    if old := request.cookies.get(COOKIE):
        end_session(db, old)
    token = create_session(db, user, now)
    db.commit()
    _set_cookie(response, token)
    return Me.model_validate(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Db) -> None:
    if token := request.cookies.get(COOKIE):
        end_session(db, token)
        db.commit()
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")


@router.get("/invites/{token}")
def invite_info(token: str, db: Db, now: Now) -> InviteInfo:
    try:
        return InviteInfo.model_validate(accounts.open_invite(db, token, now))
    except accounts.AccountError as e:
        raise _fail(e) from None


@router.post("/register", status_code=201)
def register(body: RegisterIn, response: Response, db: Db, now: Now) -> Me:
    try:
        user = accounts.register(db, body.token, body.email, body.display_name, body.password, now)
    except accounts.AccountError as e:
        raise _fail(e) from None
    _set_cookie(response, create_session(db, user, now))
    db.commit()
    return Me.model_validate(user)


@router.get("/resets/{token}")
def reset_info(token: str, db: Db, now: Now) -> ResetInfo:
    try:
        return ResetInfo.model_validate(accounts.open_reset(db, token, now))
    except accounts.AccountError as e:
        raise _fail(e) from None


@router.post("/reset", status_code=204)
def reset(body: ResetIn, db: Db, now: Now) -> None:
    try:
        accounts.reset_password(db, body.token, body.password, now)
    except accounts.AccountError as e:
        raise _fail(e) from None
