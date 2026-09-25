from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response

from ...db.models import User
from ...domain import rank as rank_rules
from ...domain import xp as xp_rules
from ...services import accounts, live, privacy, streaks, xp
from ..deps import AppSettings, Db, Member, Now
from ..schemas import (
    AccountOut,
    Aids,
    DeleteAccountIn,
    Export,
    Me,
    PasswordChangeIn,
    ProfileIn,
    Progress,
    RankOut,
    Step,
)
from .auth import clear_cookie

router = APIRouter(prefix="/api/me", tags=["me"])


def _step(d: rank_rules.Division, title: str | None) -> Step:
    return Step(
        division=d.number,
        tier=d.tier,
        title=title,
        points=d.number * rank_rules.DIVISION,
        aids=Aids.model_validate(d),
        stakes=round(d.stakes * 100),
    )


def _me(db: Db, user: User, now: datetime) -> Me:
    r = rank_rules.standing(user.rank_points, user.rank_season, user.position, user.vertical, now)
    d = r.division
    seen_top = d.number >= rank_rules.TOP - 1
    level, into, needed = xp_rules.account_level(user.xp)
    streak = xp.streak_days(db, user.id, now)
    out = Me.model_validate(user)
    out.can_host = live.can_host(user)
    out.progress = Progress(
        rank=RankOut(
            points=r.points,
            division=d.number,
            title=r.title,
            tier=d.tier,
            lp=r.lp,
            stakes=round(d.stakes * 100),
            swing=rank_rules.swing(r.points),
            miss_streak=user.miss_streak,
            aids=Aids.model_validate(d),
            ladder=[
                _step(
                    s,
                    rank_rules.title(s.number, user.vertical)
                    if s.number < rank_rules.TOP or seen_top
                    else None,
                )
                for s in rank_rules.DIVISION_TABLE
            ],
        ),
        account=AccountOut(
            level=level,
            xp=user.xp,
            into=into,
            needed=needed,
            next_milestone=next((m for m in xp_rules.MILESTONES if m > level), None),
            combo=user.combo,
            first_wins_left=max(0, xp_rules.FIRST_WINS - xp.first_wins(db, user.id, now)),
            streak=streak,
            streak_bonus=round(xp_rules.streak_bonus(streak) * 100),
            streak_freezes=streaks.held(db, user.id, now),
            rested_xp=xp.rested(db, user.rested_xp, user.rested_on, user.id, now),
        ),
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
