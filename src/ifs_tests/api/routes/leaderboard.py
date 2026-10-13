from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter

from ...domain import leaderboard as rules
from ...services import leaderboard, signals
from ..deps import AppSettings, Db, Member, Now
from ..schemas import Leaderboard, LeaderRow, MyRank, VerticalBoard, VerticalRow

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])
Board = Literal["everyone", "mech", "elec", "rules"]
Period = Literal["season", "week"]


@router.get("")
def get_leaderboard(
    user: Member,
    db: Db,
    now: Now,
    settings: AppSettings,
    board: Board = "everyone",
    period: Period = "season",
) -> Leaderboard:
    # season 1b's switch; must stay `rules_1b_from` reached, not signal collection
    since = settings.rules_1b_from if signals.policy(settings, now).collect else None
    b = leaderboard.board(db, user, None if board == "everyone" else board, period, now, since)
    return Leaderboard(
        period=period,
        board=board,
        rows=[LeaderRow.model_validate(asdict(r)) for r in b.rows],
        me=MyRank.model_validate(asdict(b.me)) if b.me else None,
        players=b.players,
        shows_accuracy=b.shows_accuracy,
        accuracy_from=b.accuracy_from,
        min_answered=rules.MIN_ANSWERED,
    )


@router.get("/verticals")
def vertical_leaderboard(user: Member, db: Db, now: Now, period: Period = "season") -> VerticalBoard:
    rows = leaderboard.verticals(db, period, now)
    return VerticalBoard(period=period, rows=[VerticalRow.model_validate(asdict(r)) for r in rows])
