"""The account page is where a player first sees what a daily did to them after midnight (ADR 0010, season 1b):
reading it, or saving their profile, grants the results that are due and answers with the account as it is then."""

# ruff: noqa: F811 - the fixtures imported from test_daily_per_player are used as parameters
from __future__ import annotations

from typing import Any

import pytest
from pytest import approx
from sqlalchemy.orm import Session

from ifs_tests.db.models import User

from .helpers import GATED
from .test_daily_per_player import TOMORROW, UNGATED, Crowd
from .test_daily_per_player import crowd as crowd
from .test_daily_per_player import rules_q as rules_q
from .test_daily_results_at_day_close import MORNING, RELEASE, column, play_daily, row_of, state_of

pytestmark = pytest.mark.integration


@pytest.fixture
def app_settings(request: pytest.FixtureRequest) -> dict[str, Any]:
    return {**GATED, "canary": False, **getattr(request, "param", {})}


def test_the_account_page_grants_the_results_that_are_due_and_shows_them(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules")
    before = ana.get("/api/me").json()
    assert before["xp"] == 0 and before["progress"]["rank"]["points"] == 50

    crowd.travel(MORNING)
    me = ana.get("/api/me").json()
    stored = row_of(db, started["attempt_id"])
    assert stored.settled_at == MORNING and stored.xp > 0 and stored.lp > 0
    assert me["xp"] == stored.xp  # in this very response: the grant, then the read
    assert me["progress"]["rank"]["points"] == approx(50 + stored.lp)
    assert ana.get("/api/me").json() == me  # and nothing is granted twice


def test_saving_the_profile_returns_the_account_after_the_due_results_are_granted(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules")
    crowd.travel(MORNING)
    r = ana.patch("/api/me", json={"leaderboard_opt_out": False})
    assert r.status_code == 200, r.text
    stored = row_of(db, started["attempt_id"])
    assert stored.settled_at == MORNING and stored.xp > 0
    body = r.json()
    assert body["xp"] == stored.xp
    assert body["progress"]["rank"]["points"] == approx(50 + stored.lp)
    assert column(db, ana.id, User.xp) == stored.xp


@pytest.mark.parametrize("verb", ["get", "patch"])
def test_neither_grants_anything_before_the_midnight(
    crowd: Crowd, db: Session, rules_q: int, verb: str
) -> None:
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules")
    before = state_of(db, ana.id)
    crowd.travel(RELEASE.replace(hour=21, minute=59, second=59))
    r = ana.get("/api/me") if verb == "get" else ana.patch("/api/me", json={"leaderboard_opt_out": False})
    assert r.status_code == 200 and r.json()["xp"] == 0
    assert row_of(db, started["attempt_id"]).settled_at is None
    assert state_of(db, ana.id) == before


@pytest.mark.parametrize(
    ("app_settings", "at_midnight"),
    [({}, True), (UNGATED, False), (TOMORROW, False)],
    indirect=["app_settings"],
)
def test_the_rank_card_is_told_whether_a_daily_lands_at_midnight_today(
    crowd: Crowd, rules_q: int, at_midnight: bool
) -> None:
    """Before the switch, and on a day kept shared, the card must not promise a delay that does not happen."""
    ana = crowd.player("Ana")
    assert ana.get("/api/me").json()["progress"]["rank"]["daily_at_midnight"] is at_midnight
