from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request

from ...db.models import User
from ...domain import xp as rules
from ...services import accounts, xp
from ..deps import AppSettings, Db, Member, Now
from ..schemas import Aids, Me, PasswordChangeIn, ProfileIn, Progress

router = APIRouter(prefix="/api/me", tags=["me"])


def _me(db: Db, user: User, now: datetime) -> Me:
    level = rules.level_for(user.xp)
    t = rules.tier(level)
    streak = xp.streak_days(db, user.id, now)
    out = Me.model_validate(user)
    out.progress = Progress(
        level=level,
        title=t.name,
        level_xp=rules.xp_for_level(level),
        next_level_xp=rules.xp_for_level(level + 1),
        penalty=round(t.penalty * 100),
        streak=streak,
        streak_bonus=round((rules.streak_multiplier(streak) - 1) * 100),
        aids=Aids(formulas=t.formulas, learn_more=t.learn_more, hint=t.hint),
    )
    return out


@router.get("")
def me(user: Member, db: Db, now: Now) -> Me:
    return _me(db, user, now)


@router.patch("")
def update_me(body: ProfileIn, user: Member, db: Db, now: Now) -> Me:
    return _me(db, accounts.update_profile(db, user, body.model_dump(exclude_unset=True)), now)


@router.post("/password", status_code=204)
def change_password(
    body: PasswordChangeIn, request: Request, user: Member, db: Db, now: Now, settings: AppSettings
) -> None:
    keep = request.cookies[settings.session_cookie]
    accounts.change_password(db, user, body.current_password, body.new_password, keep, now)
