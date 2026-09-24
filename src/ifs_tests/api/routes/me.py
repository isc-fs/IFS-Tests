from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response

from ...db.models import User
from ...domain import xp as rules
from ...services import accounts, live, privacy, xp
from ..deps import AppSettings, Db, Member, Now
from ..schemas import Aids, DeleteAccountIn, Export, Me, PasswordChangeIn, ProfileIn, Progress, Step
from .auth import clear_cookie

router = APIRouter(prefix="/api/me", tags=["me"])


def _step(lv: rules.Level, title: str | None) -> Step:
    return Step(
        level=lv.number,
        tier=lv.tier,
        title=title,
        xp=rules.xp_for_level(lv.number),
        aids=Aids.model_validate(lv),
        penalty=round(lv.penalty * 100),
    )


def _me(db: Db, user: User, now: datetime) -> Me:
    level = rules.level_for(user.xp)
    lv = rules.at(level)
    streak = xp.streak_days(db, user.id, now)
    seen_top = level >= rules.TOP - 1
    out = Me.model_validate(user)
    out.can_host = live.can_host(user)
    out.progress = Progress(
        level=level,
        title=rules.title(level, user.vertical),
        tier=lv.tier,
        level_xp=rules.xp_for_level(level),
        next_level_xp=rules.xp_for_level(level + 1) if level < rules.TOP else None,
        penalty=round(lv.penalty * 100),
        streak=streak,
        streak_bonus=round((rules.streak_multiplier(streak) - 1) * 100),
        aids=Aids.model_validate(lv),
        ladder=[
            _step(s, rules.title(s.number, user.vertical) if s.number < rules.TOP or seen_top else None)
            for s in rules.LEVELS
        ],
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


@router.get("/export")
def export_my_data(user: Member, db: Db, now: Now, response: Response) -> Export:
    # Names can hold any Latin letter; headers only Latin-1, so the file name carries the date alone.
    response.headers["Content-Disposition"] = f'attachment; filename="mingoquiz-export-{now.date()}.json"'
    return Export.model_validate(privacy.export(db, user, now))


@router.post("/delete", status_code=204)
def delete_account(
    body: DeleteAccountIn, response: Response, user: Member, db: Db, now: Now, settings: AppSettings
) -> None:
    privacy.delete_self(db, user, body.password, now)
    clear_cookie(response, settings)
