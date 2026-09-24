from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import approx
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Attempt, AuditLog, LiveQuestion, LiveSession, Question, User
from ifs_tests.domain import daily as daily_rules
from ifs_tests.domain import leaderboard as board_rules
from ifs_tests.domain import rank as rank_rules
from ifs_tests.domain import xp as xp_rules
from ifs_tests.domain.rank import TOP
from ifs_tests.services import live, maintenance, xp
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import PASSWORD, invite, login, options, register, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


def join(admin_client: TestClient, c: TestClient, name: str, position: str | None = None) -> dict[str, Any]:
    extra = {"position": position} if position else {}
    r = register(c, invite(admin_client), f"{name.lower()}@alu.comillas.edu", name, **extra)
    assert r.status_code == 201, r.text
    return dict(r.json())


def set_rank(db: Session, user_id: int, points: float, **values: Any) -> None:
    db.execute(update(User).where(User.id == user_id).values(rank_points=points, **values))
    db.commit()


def lp(db: Session, qid: int, correct: bool, points: float, mode: str = "practice", **kwargs: Any) -> float:
    """The LP an answer to this question moves at `points`, from its own area, kind and number of options."""
    q = db.get_one(Question, qid)
    n = len(options(db, qid)) if q.answer_kind == "choice-one" else 0
    return rank_rules.lp_award(
        correct, points, 3, mode, area=q.area, answer_kind=q.answer_kind, options=n, **kwargs
    ).amount


def earned(correct: bool | None, mode: str = "practice", **kwargs: Any) -> int:
    return xp_rules.xp_award(correct, 3, mode, **kwargs).amount


def wrong(db: Session, qid: int) -> dict[str, Any]:
    right = right_answer(db, qid)
    if "options" in right:
        return {"options": [o for o in options(db, qid) if o not in right["options"]][:1]}
    return {"value": "-1"}


def practise(c: TestClient, qid: int, body: dict[str, Any]) -> dict[str, Any]:
    r = c.post(f"/api/practice/questions/{qid}/answer", json=body)
    assert r.status_code == 200, r.text
    return dict(r.json())


def scored(db: Session, user_id: int, qid: int, correct: bool, now: datetime, **kw: Any) -> xp.Grant:
    """That question answered as a daily one, scored the way the daily route scores it."""
    granted = xp.grant(db, user_id, db.get_one(Question, qid), "daily", correct, now, **kw)
    db.commit()
    return granted


def progress(c: TestClient) -> dict[str, Any]:
    return dict(c.get("/api/me").json()["progress"])


def next_madrid_day(c: TestClient, clock: Clock) -> None:
    clock.advance(hours=11)
    c.get("/api/me")
    clock.advance(hours=2)  # past Madrid midnight; sessions go idle after 12 h


NO_AIDS = {"formulas": False, "learn_more": False, "hint": False}
ALL_AIDS = {"formulas": True, "learn_more": True, "hint": True}


@pytest.mark.parametrize(
    ("position", "division", "title", "aids", "stakes"),
    [
        (None, 0, "Mingo I", ALL_AIDS, 80),
        ("member", 3, "Mingo IV", ALL_AIDS, 89),
        ("department_head", 5, "Jefe I", {"formulas": False, "learn_more": False, "hint": True}, 95),
        ("technical_director", 10, "DT I", NO_AIDS, 110),
    ],
)
def test_the_position_you_join_with_places_your_rank(
    signed_in: TestClient,
    new_client: NewClient,
    position: str | None,
    division: int,
    title: str,
    aids: dict[str, bool],
    stakes: int,
) -> None:
    c = new_client()
    me = join(signed_in, c, "Ana", position)
    assert (me["position"], me["xp"]) == (position or "mingo", 0)
    p = progress(c)
    ladder = p["rank"].pop("ladder")
    points = division * 100 + 50
    assert p["rank"] == {
        "points": points,
        "division": division,
        "title": title,
        "tier": title.split()[0],
        "lp": 50,
        "stakes": stakes,
        "swing": list(rank_rules.swing(points)),
        "miss_streak": 0,
        "aids": aids,
    }
    assert p["account"] == {
        "level": 1,
        "xp": 0,
        "into": 0,
        "needed": 300,
        "next_milestone": 10,
        "combo": 0,
        "first_wins_left": 3,
        "streak": 0,
        "streak_bonus": 0,
        "streak_freezes": 0,
        "rested_xp": 0,
    }
    assert [s["title"] for s in ladder][:3] == ["Mingo I", "Mingo II", "Mingo III"]
    assert ladder[TOP] == {
        "division": TOP,
        "tier": "Top",
        "title": None,  # a surprise until DT V
        "points": 1500,
        "aids": NO_AIDS,
        "stakes": 125,
    }


@pytest.mark.parametrize(
    ("vertical", "top"), [("Mechanical", "Gigante Noble"), ("Electronics", "Villano"), (None, "Leyenda")]
)
def test_the_top_title_is_revealed_at_dt_v_and_depends_on_the_vertical(
    signed_in: TestClient, new_client: NewClient, db: Session, vertical: str | None, top: str
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    c.patch("/api/me", json={"vertical": vertical})
    set_rank(db, ana["id"], 1399.99)
    rank = progress(c)["rank"]
    assert (rank["title"], rank["ladder"][TOP]["title"]) == ("DT IV", None)
    set_rank(db, ana["id"], 1400)
    rank = progress(c)["rank"]
    assert (rank["title"], rank["ladder"][TOP]["title"]) == ("DT V", top)
    set_rank(db, ana["id"], 2345.5)
    rank = progress(c)["rank"]
    assert (rank["division"], rank["title"], rank["tier"], rank["lp"]) == (TOP, top, "Top", 845.5)


def test_an_unknown_position_is_refused(signed_in: TestClient, new_client: NewClient) -> None:
    r = register(new_client(), invite(signed_in), "ana@alu.comillas.edu", "Ana", position="team_principal")
    assert r.status_code == 422


def test_members_cannot_change_their_own_position(signed_in: TestClient, new_client: NewClient) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    assert (
        c.patch("/api/me", json={"position": "technical_director"}).status_code == 422
    )  # not a profile field
    assert c.get("/api/me").json()["position"] == "mingo"


def test_a_new_position_moves_the_rank_by_the_difference_in_placements(
    signed_in: TestClient, new_client: NewClient, db: Session
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    r = signed_in.patch(f"/api/admin/users/{ana['id']}", json={"position": "department_head"})
    assert r.status_code == 200, r.text
    assert (r.json()["position"], r.json()["rank_points"]) == ("department_head", 550)
    assert progress(c)["rank"]["title"] == "Jefe I"
    details = db.scalars(select(AuditLog.details).order_by(AuditLog.id.desc())).first()
    assert details == {"position": ["mingo", "department_head"]}
    lowered = signed_in.patch(f"/api/admin/users/{ana['id']}", json={"position": "mingo"}).json()
    assert (lowered["position"], lowered["rank_points"]) == ("mingo", 50)  # the head start goes with it
    set_rank(db, ana["id"], 1234.5)
    raised = signed_in.patch(f"/api/admin/users/{ana['id']}", json={"position": "technical_director"}).json()
    assert (raised["position"], raised["rank_points"]) == ("technical_director", 1234.5)  # already above


def test_a_new_position_applies_a_pending_season_reset_first(
    signed_in: TestClient, new_client: NewClient, db: Session
) -> None:
    ana = join(signed_in, new_client(), "Ana", "member")
    leo = join(signed_in, new_client(), "Leo")
    # Both last played in 2024: their 1200 and 600 stand at 900 and 300 this season (2026).
    set_rank(db, ana["id"], 1200, rank_season=2024)
    set_rank(db, leo["id"], 600, rank_season=2024)
    lowered = signed_in.patch(f"/api/admin/users/{ana['id']}", json={"position": "mingo"}).json()
    raised = signed_in.patch(f"/api/admin/users/{leo['id']}", json={"position": "department_head"}).json()
    assert (lowered["rank_points"], raised["rank_points"]) == (600, 550)
    db.expire_all()
    seasons = db.scalars(select(User.rank_season).where(User.id.in_([ana["id"], leo["id"]])))
    assert set(seasons) == {2026}


def test_a_promotion_by_position_is_no_fanfare_later(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    signed_in.patch(f"/api/admin/users/{ana['id']}", json={"position": "department_head"})
    slip = daily(c, db, "mech", "wrong")
    assert (slip["promoted"], slip["demoted"], slip["rank_points"] >= 500) == (False, False, True)
    set_rank(db, ana["id"], 499.5)  # dropped to Mingo V, then back into Jefe I: reached already this season
    back = daily(c, db, "rules", "right")
    assert (back["promoted"], back["rank_points"] >= 500) == (False, True)


def test_members_cannot_use_the_admin_route_to_change_positions(
    signed_in: TestClient, new_client: NewClient
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    assert (
        c.patch(f"/api/admin/users/{ana['id']}", json={"position": "technical_director"}).status_code == 403
    )


def test_a_right_daily_answer_wins_lp_and_xp_with_the_first_win_bonus(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    started = c.post("/api/daily/mech/start").json()
    qid = started["question"]["id"]
    r = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=right_answer(db, qid)).json()
    gain = lp(db, qid, True, 50, "daily")
    fb = r["feedback"]
    assert gain > 0 and (fb["lp"], r["lp"]) == (approx(gain), approx(gain))
    assert earned(True, "daily", first_win=True) == earned(True, "daily") + 25 == 75
    assert (fb["xp"], r["xp"], fb["bonuses"]) == (75, 75, {"first_win": 25})
    assert (fb["combo"], fb["level"], fb["level_up"], fb["rank_points"]) == (1, 1, False, approx(50 + gain))
    me = c.get("/api/me").json()
    assert (me["xp"], me["progress"]["rank"]["points"]) == (75, approx(50 + gain))
    assert (me["progress"]["account"]["first_wins_left"], me["progress"]["account"]["combo"]) == (2, 1)
    status = c.get("/api/daily").json()
    assert (status["xp_today"], status["lp_today"]) == (75, approx(gain))
    review = c.get("/api/daily/mech/review").json()["feedback"]  # a reload shows what was stored
    assert (review["xp"], review["lp"], review["bonuses"]) == (75, approx(gain), {})


def test_a_wrong_answer_loses_lp_but_still_earns_xp(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "technical_director")
    r = daily(c, db, "mech", "wrong")
    loss = lp(db, r["qid"], False, 1050, "daily")
    assert (r["correct"], r["lp"], r["xp"], r["bonuses"]) == (False, approx(loss), earned(False, "daily"), {})
    assert loss < 0 and earned(False, "daily") == 15
    r2 = daily(c, db, "rules", "wrong")
    loss2 = lp(db, r2["qid"], False, 1050 + loss, "daily", miss_streak=1)
    assert (r2["lp"], r2["xp"], r2["rank_points"]) == (approx(loss2), 15, approx(1050 + loss + loss2))
    assert c.get("/api/me").json()["xp"] == 30  # XP only goes up
    assert db.scalars(select(Attempt.lp).order_by(Attempt.id)).all() == approx([loss, loss2])


def test_the_rank_stops_at_zero(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    set_rank(db, ana["id"], 1)
    r = daily(c, db, "mech", "wrong")
    assert (r["lp"], r["rank_points"], r["xp"]) == (-1, 0, earned(False, "daily"))


def test_the_combo_grows_with_right_answers_and_a_wrong_one_resets_it(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    got = [
        practise(c, bank[f], right_answer(db, bank[f]) if ok else wrong(db, bank[f]))
        for f, ok in ((90001, True), (90003, True), (90008, True), (90002, False), (90011, True))
    ]
    assert [(r["combo"], r["xp"], r["bonuses"]) for r in got] == [
        (1, earned(True, first_win=True), {"first_win": 9}),
        (2, earned(True, first_win=True, combo=1), {"first_win": 9, "combo": 2}),
        (3, earned(True, first_win=True, combo=2), {"first_win": 9, "combo": 4}),
        (0, earned(False), {}),
        (1, earned(True), {}),  # the first wins of the day are spent
    ]
    account = progress(c)["account"]
    assert (account["combo"], account["first_wins_left"]) == (1, 0)
    next_madrid_day(c, clock)
    assert progress(c)["account"]["first_wins_left"] == 3


def daily(c: TestClient, db: Session, area: str, body: str) -> dict[str, Any]:
    started = c.post(f"/api/daily/{area}/start").json()
    qid = started["question"]["id"]
    answer = {"right": right_answer(db, qid), "wrong": _wrong(started), "unsure": {"unsure": True}}[body]
    r = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=answer)
    assert r.status_code == 200, r.text
    return {"qid": qid, **r.json()["feedback"]}


def test_three_wrong_in_a_row_cushion_the_losses_until_a_comeback(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    leo = join(signed_in, c, "Leo", "member")
    set_rank(db, leo["id"], 350.0, miss_streak=2)
    slip = practise(c, bank[90001], wrong(db, bank[90001]))
    assert (slip["cushioned"], progress(c)["rank"]["miss_streak"]) == (
        False,
        2,
    )  # practice misses don't count
    third = daily(c, db, "mech", "wrong")
    assert (third["cushioned"], progress(c)["rank"]["miss_streak"]) == (False, 3)
    points = third["rank_points"]
    fourth = daily(c, db, "elec", "wrong")
    halved = lp(db, fourth["qid"], False, points, "daily", miss_streak=3)
    assert halved == approx(lp(db, fourth["qid"], False, points, "daily") / 2, abs=0.02)
    assert (fourth["cushioned"], fourth["lp"]) == (True, approx(halved))
    points = fourth["rank_points"]
    back = daily(c, db, "rules", "right")
    boosted = lp(db, back["qid"], True, points, "daily", miss_streak=4)
    assert boosted == approx(lp(db, back["qid"], True, points, "daily") * 1.5, abs=0.02)
    assert (back["comeback"], back["cushioned"], back["lp"]) == (True, False, approx(boosted))
    assert progress(c)["rank"]["miss_streak"] == 0


def test_a_pass_leaves_the_bad_run_as_it_is(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    leo = join(signed_in, c, "Leo", "member")
    set_rank(db, leo["id"], 350.0, miss_streak=3)
    unsure = daily(c, db, "mech", "unsure")
    halved = lp(db, unsure["qid"], False, 350.0, "daily", passed=True, miss_streak=3)
    assert (unsure["cushioned"], unsure["lp"]) == (True, approx(halved))
    assert progress(c)["rank"]["miss_streak"] == 3


def test_the_bad_run_counter_is_capped(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    leo = join(signed_in, c, "Leo", "member")
    set_rank(db, leo["id"], 350.0, miss_streak=99, combo=99)
    daily(c, db, "mech", "wrong")
    daily(c, db, "elec", "right")
    daily(c, db, "rules", "wrong")
    rank = progress(c)
    assert (rank["rank"]["miss_streak"], rank["account"]["combo"]) == (1, 0)


def test_im_not_sure_costs_at_most_half_a_wrong_answer_and_shows_the_answer(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "technical_director")
    r = daily(c, db, "rules", "unsure")
    qid = r["qid"]
    cost = lp(db, qid, False, 1050, "daily", passed=True)
    assert lp(db, qid, False, 1050, "daily") / 2 - 0.01 <= cost < 0
    assert (r["correct"], r["passed"], r["lp"], r["xp"]) == (False, True, approx(cost), earned(None, "daily"))
    assert earned(None, "daily") == 5
    assert r["official"] and r["correct_options"]
    a = db.scalars(select(Attempt)).one()
    assert (a.passed, a.correct, a.answer["unsure"]) == (True, False, True) and a.lp == approx(cost)
    next_madrid_day(c, clock)
    again = practise(c, qid, right_answer(db, qid))  # seen already: a quarter of the XP
    assert (again["lp"], again["xp"]) == (0, earned(True, repeat=True, first_win=True))


def test_im_not_sure_does_nothing_to_the_rank_for_an_ungraded_question(
    signed_in: TestClient, new_client: NewClient, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    r = practise(c, bank[90009], {"unsure": True})
    assert (r["correct"], r["passed"], r["lp"], r["xp"]) == (None, False, 0, earned(None))


def test_practice_pays_nothing_again_the_same_day_and_no_lp_on_a_question_seen_before(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    qid = bank[90001]
    right = right_answer(db, qid)
    first = practise(c, qid, right)
    assert (first["lp"], first["xp"]) == (approx(lp(db, qid, True, 50)), earned(True, first_win=True))
    for _ in range(3):
        again = practise(c, qid, right)
        assert (again["lp"], again["xp"], again["combo"]) == (0, 0, 1)  # the combo neither grows nor breaks
    points = first["rank_points"]
    next_madrid_day(c, clock)
    later = practise(c, qid, right)
    assert (later["lp"], later["xp"], later["rank_points"]) == (
        0,  # grinding known questions doesn't climb
        earned(True, repeat=True, first_win=True, combo=1),
        points,
    )
    assert c.get("/api/me").json()["xp"] == first["xp"] + later["xp"]


def test_practice_wrong_then_right_the_same_day_earns_nothing_more(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    qid = bank[90001]
    assert practise(c, qid, wrong(db, qid))["xp"] == 6
    right = practise(c, qid, right_answer(db, qid))
    assert (right["correct"], right["lp"], right["xp"]) == (True, 0, 0)
    assert c.get("/api/me").json()["xp"] == 6


def test_crossing_into_a_division_is_a_promotion_once_and_a_drop_brings_the_aids_back(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    set_rank(db, ana["id"], 399.5)
    assert c.get("/api/learning/dynamics").json()["learn_more"]
    up = daily(c, db, "mech", "right")
    assert (up["promoted"], up["demoted"], up["rank_points"] >= 400) == (True, False, True)
    assert progress(c)["rank"]["title"] == "Mingo V"
    assert not c.get("/api/learning/dynamics").json()["learn_more"]  # reading is for Mingo I-IV
    set_rank(db, ana["id"], 400.5)
    down = daily(c, db, "rules", "wrong")
    assert (down["promoted"], down["demoted"], down["rank_points"] < 400) == (False, True, True)
    assert progress(c)["rank"]["title"] == "Mingo IV"
    assert c.get("/api/learning/dynamics").json()["learn_more"]  # back after the drop
    set_rank(db, ana["id"], 399.5)
    back = daily(c, db, "elec", "right")
    assert (back["promoted"], back["rank_points"] >= 400) == (False, True)  # reached before this season


def test_the_answer_that_crosses_an_account_level_says_so(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    db.execute(update(User).where(User.id == ana["id"]).values(xp=xp_rules.to_next(1) - 1))
    db.commit()
    first = practise(c, bank[90001], right_answer(db, bank[90001]))
    assert (first["level"], first["level_up"]) == (2, True)
    second = practise(c, bank[90002], right_answer(db, bank[90002]))
    assert (second["level"], second["level_up"]) == (2, False)
    account = progress(c)["account"]
    assert (account["level"], account["xp"], account["needed"]) == (2, 299 + first["xp"] + second["xp"], 350)


def test_the_streak_shows_on_the_profile_and_boosts_xp(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    qid = bank[90001]
    today = daily_rules.madrid_day(clock.now)
    for back in range(1, 4):
        db.add(
            Attempt(
                user_id=ana["id"],
                question_id=qid,
                mode="daily",
                answer={},
                correct=False,
                created_at=clock.now - timedelta(days=back),
                day=today - timedelta(days=back),
                area="mech",
                submitted_at=clock.now - timedelta(days=back),
                late=False,
            )
        )
    db.commit()
    account = progress(c)["account"]
    assert (account["streak"], account["streak_bonus"]) == (3, 10)
    other = bank[90002]
    r = practise(c, other, right_answer(db, other))
    assert (r["xp"], r["bonuses"]) == (
        earned(True, first_win=True, streak_days=3),
        {"first_win": 9, "streak": 2},
    )


def test_a_crit_doubles_the_xp_of_a_right_answer(
    signed_in: TestClient,
    new_client: NewClient,
    db: Session,
    bank: dict[int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xp, "_crit", lambda *_: True)
    c = new_client()
    join(signed_in, c, "Ana")
    r = practise(c, bank[90001], right_answer(db, bank[90001]))
    assert (r["xp"], r["bonuses"]) == (earned(True, first_win=True, crit=True), {"first_win": 9, "crit": 19})


def test_a_question_seen_before_pays_a_quarter_as_the_daily(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    started = c.post("/api/daily/mech/start").json()
    qid = started["question"]["id"]
    # practice can't reveal a question that is running elsewhere...
    assert c.post(f"/api/practice/questions/{qid}/answer", json=_wrong(started)).status_code == 409
    assert c.post(f"/api/practice/questions/{qid}/hint").status_code == 409
    # ...but one practised earlier in the season is a repeat when it comes back as the daily
    db.add(
        Attempt(
            user_id=ana["id"],
            question_id=qid,
            mode="practice",
            answer={},
            correct=False,
            created_at=clock.now - timedelta(days=3),
        )
    )
    db.commit()
    r = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=right_answer(db, qid)).json()
    assert (r["xp"], r["lp"]) == (
        earned(True, "daily", repeat=True, first_win=True, rested=300),  # two full days away banked 300
        approx(lp(db, qid, True, 50, "daily", repeat=True)),
    )


def test_a_question_seen_before_pays_a_quarter_in_a_mock_quiz(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    seen = bank[90001]  # the first question of quiz 9002
    points = practise(c, seen, right_answer(db, seen))["rank_points"]
    next_madrid_day(c, clock)  # seen earlier in the season, not today
    state = c.post("/api/mock/quizzes/9002/start").json()
    assert state["current"]["question"]["id"] == seen
    state = finish_mock(c, db, state)
    items = [i["feedback"] for i in state["summary"]["items"]]
    assert {(i["rank_points"], i["level"]) for i in items} == {(None, None)}  # each item, not where you stand
    assert (items[0]["xp"], items[0]["lp"]) == (
        earned(True, "mock", repeat=True, first_win=True, combo=1),
        approx(lp(db, seen, True, points, "mock", repeat=True)),
    )
    assert (items[1]["xp"], items[1]["lp"]) == (
        earned(True, "mock", first_win=True, combo=2),
        approx(lp(db, bank[90002], True, points + items[0]["lp"], "mock")),
    )


def finish_mock(
    c: TestClient, db: Session, state: dict[str, Any], first: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Answer the rest of a mock run right (the first one with `first`, if given)."""
    while state["current"]:
        body = first or right_answer(db, state["current"]["question"]["id"])
        first = None
        state = c.post(
            f"/api/mock/sessions/{state['session_id']}/answer",
            json={"attempt_id": state["current"]["attempt_id"], **body},
        ).json()
    return state


def _wrong(started: dict[str, Any]) -> dict[str, Any]:
    opts = [o["id"] for o in started["question"]["options"]]
    return {"options": opts} if opts else {"value": "-1"}


def test_a_daily_left_to_run_out_loses_lp_and_earns_nothing(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "technical_director")
    started = c.post("/api/daily/mech/start").json()
    clock.now = datetime.fromisoformat(started["deadline_at"]) + timedelta(seconds=4)
    area = c.get("/api/daily").json()["areas"][0]
    loss = lp(db, started["question"]["id"], False, 1050, "daily", late=True)
    assert loss < 0
    assert (area["state"], area["late"], area["correct"], area["xp"], area["lp"]) == (
        "done",
        True,
        False,
        0,
        approx(loss),
    )
    me = c.get("/api/me").json()
    assert (me["xp"], me["progress"]["rank"]["points"], me["progress"]["account"]["streak"]) == (
        0,
        approx(1050 + loss),
        0,
    )
    stored = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=_wrong(started)).json()
    assert (stored["xp"], stored["lp"]) == (0, approx(loss))  # already closed: nothing changes
    assert db.execute(select(Attempt.xp, Attempt.lp).where(Attempt.mode == "daily")).tuples().one() == approx(
        (0, loss)
    )


def test_the_nightly_job_closes_abandoned_dailies_once(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c, d = new_client(), new_client()
    toni = join(signed_in, c, "Toni", "department_head")
    ana = join(signed_in, d, "Ana")
    qid = c.post("/api/daily/mech/start").json()["question"]["id"]
    d.post("/api/daily/mech/start")
    fresh = c.post("/api/daily/elec/start").json()
    clock.advance(minutes=30)
    db.execute(update(Attempt).where(Attempt.id == fresh["attempt_id"]).values(deadline_at=clock.now))
    db.commit()
    assert maintenance.run(db, clock.now)["dailies_closed"] == 2  # the one still inside its grace stays open
    assert maintenance.run(db, clock.now)["dailies_closed"] == 0
    got = {
        uid: (x, loss)
        for uid, x, loss in db.execute(
            select(Attempt.user_id, Attempt.xp, Attempt.lp).where(Attempt.area == "mech")
        )
    }
    assert got == {
        toni["id"]: (0, approx(lp(db, qid, False, 550, "daily", late=True))),
        ana["id"]: (0, approx(lp(db, qid, False, 50, "daily", late=True))),  # no protection for mingos
    }


def test_a_mock_question_left_to_run_out_loses_lp_and_earns_nothing(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "department_head")
    state = c.post("/api/mock/quizzes/9002/start").json()
    first = state["current"]["question"]["id"]
    clock.now = datetime.fromisoformat(state["current"]["deadline_at"]) + timedelta(seconds=4)
    state = c.get(f"/api/mock/sessions/{state['session_id']}").json()
    c.get(f"/api/mock/sessions/{state['session_id']}")  # reloading doesn't charge twice
    loss = lp(db, first, False, 550, "mock", late=True)
    assert progress(c)["rank"]["points"] == approx(550 + loss)
    state = finish_mock(c, db, state)
    items = [i["feedback"] for i in state["summary"]["items"]]
    assert (items[0]["xp"], items[0]["lp"]) == (0, approx(loss))
    assert [i["xp"] for i in items[1:]] == [
        earned(True, "mock", first_win=True),
        earned(True, "mock", first_win=True, combo=1),
        earned(True, "mock", first_win=True, combo=2),
        earned(True, "mock", combo=3),
    ]
    assert (state["summary"]["xp"], state["summary"]["lp"]) == (
        sum(i["xp"] for i in items),
        approx(sum(i["lp"] for i in items), abs=0.02),
    )


def test_im_not_sure_in_the_daily_keeps_the_streak_but_not_after_the_clock(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "technical_director")
    started = c.post("/api/daily/mech/start").json()
    r = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json={"unsure": True}).json()
    cost = lp(db, started["question"]["id"], False, 1050, "daily", passed=True)
    assert (r["feedback"]["passed"], r["feedback"]["correct"], r["streak"]) == (True, False, 1)
    assert (r["xp"], r["lp"]) == (earned(None, "daily"), approx(cost))
    review = c.get("/api/daily/mech/review").json()
    assert (review["feedback"]["passed"], review["xp"], review["lp"]) == (True, 5, approx(cost))
    late = c.post("/api/daily/elec/start").json()
    clock.now = datetime.fromisoformat(late["deadline_at"]) + timedelta(seconds=10)
    r = c.post(f"/api/daily/attempts/{late['attempt_id']}/answer", json={"unsure": True}).json()
    full = lp(db, late["question"]["id"], False, 1050 + cost, "daily", late=True)
    assert (r["xp"], r["lp"]) == (
        earned(None, "daily"),
        approx(full),
    )  # a full wrong answer's LP, a pass's XP


def test_im_not_sure_in_a_mock_quiz_moves_on_at_half_a_wrong_answer(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "technical_director")
    state = c.post("/api/mock/quizzes/9002/start").json()
    first = state["current"]["question"]["id"]
    state = finish_mock(c, db, state, first={"unsure": True})
    items = state["summary"]["items"]
    fb = items[0]["feedback"]
    assert (fb["passed"], fb["correct"], fb["xp"], fb["lp"]) == (
        True,
        False,
        earned(None, "mock"),
        approx(lp(db, first, False, 1050, "mock", passed=True)),
    )
    assert state["summary"]["correct"] == len(items) - 1


def test_at_the_top_typed_answers_cost_the_least(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    c = new_client()
    toni = join(signed_in, c, "Toni", "technical_director")
    cases = {90008: ("rules", "choice-one"), 90001: ("mech", "choice-one"), 90003: ("elec", "choice-many")}
    cases[90002] = ("mech", "number")
    losses = {}
    for fsquiz_id, (area, kind) in cases.items():
        set_rank(db, toni["id"], 2000, miss_streak=0)
        q = db.get_one(Question, bank[fsquiz_id])
        assert (q.area, q.answer_kind) == (area, kind)
        r = scored(db, toni["id"], q.id, False, clock.now)
        assert r.lp == approx(lp(db, q.id, False, 2000, "daily")), fsquiz_id
        losses[fsquiz_id] = -r.lp
    assert min(losses, key=losses.__getitem__) == 90002
    assert losses[90003] < losses[90001]  # a multiple-choice slip is softer


def _live_quiz(db: Session, clock: Clock, player: User) -> LiveSession:
    host = User(email="td@x.com", password_hash="x", display_name="Host", position="technical_director")
    db.add(host)
    db.commit()
    config = {
        "questions": "areas",
        "areas": ["mech"],
        "count": 2,
        "timing": "fixed",
        "seconds": 60,
        "feedback": "each",
        "routing": "all",
        "speed_points": False,
    }
    s = live.create(db, host, config, clock.now)
    live.join(db, player, s.code, clock.now)
    live.seat(db, host, s.code, [{"name": "T", "member_ids": [player.id], "captain_id": player.id}])
    live.advance(db, host, s.code, clock.now)
    return s


def _open_question(db: Session, s: LiveSession) -> int:
    position = db.scalar(select(LiveSession.position).where(LiveSession.id == s.id))
    return db.get_one(LiveQuestion, (s.id, position)).question_id


def test_live_answers_earn_xp_but_never_move_the_rank_or_the_combo(
    db: Session, clock: Clock, admin: User, bank: dict[int, int]
) -> None:
    player = User(
        email="p@x.com",
        password_hash="x",
        display_name="Player",
        rank_points=500.0,
        rank_season=rank_rules.season_of(clock.now),
        combo=2,
        miss_streak=3,
    )
    db.add(player)
    db.commit()
    s = _live_quiz(db, clock, player)
    host = db.scalars(select(User).where(User.email == "td@x.com")).one()
    qid = _open_question(db, s)
    right = right_answer(db, qid)
    live.answer(db, player, s.code, right.get("options"), right.get("value"), False, clock.now)
    live.advance(db, host, s.code, clock.now)  # the table has answered: on to the next question
    other = _open_question(db, s)
    miss = wrong(db, other)
    live.answer(db, player, s.code, miss.get("options"), miss.get("value"), False, clock.now)
    live.share(db, s.id, clock.now)  # what the routes run after responding
    rows = db.execute(select(Attempt.correct, Attempt.xp, Attempt.lp).order_by(Attempt.id)).tuples().all()
    assert rows == [
        (True, earned(True, "live"), 0),
        (False, earned(False, "live"), 0),
    ]  # no first win or combo
    state = db.execute(
        select(User.rank_points, User.combo, User.miss_streak, User.xp).where(User.id == player.id)
    ).one()
    assert tuple(state) == (500, 2, 3, earned(True, "live") + earned(False, "live"))


def test_the_season_rolls_over_on_1_september_once(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    ana = join(signed_in, new_client(), "Ana")
    leo = join(signed_in, new_client(), "Leo", "member")
    toni = join(signed_in, new_client(), "Toni", "technical_director")
    old = join(signed_in, new_client(), "Old", "department_head")
    set_rank(db, leo["id"], 900, rank_best=9)
    set_rank(db, toni["id"], 1620.5, rank_best=TOP, combo=4)
    set_rank(db, old["id"], 1400, status="alumni")
    clock.now = datetime(2027, 8, 31, 21, 59, tzinfo=UTC)  # 23:59 in Madrid: still last season
    assert maintenance.run(db, clock.now)["ranks_reset"] == 0
    clock.now = datetime(2027, 8, 31, 22, 2, tzinfo=UTC)  # 00:02 on 1 September in Madrid
    assert maintenance.run(db, clock.now)["ranks_reset"] == 4  # three players and the admin
    assert maintenance.run(db, clock.now)["ranks_reset"] == 0
    rows = {
        uid: tuple(rest)
        for uid, *rest in db.execute(
            select(User.id, User.rank_points, User.rank_season, User.rank_best, User.combo, User.xp)
        )
    }
    assert rows[ana["id"]] == (50, 2027, 0, 0, 0)  # never below the placement
    assert rows[leo["id"]] == (600, 2027, 6, 0, 0)  # three divisions back
    assert rows[toni["id"]] == (1200, 2027, 12, 4, 0)  # the top counts as 1500; the combo stays
    assert rows[old["id"]] == (1400, 2026, 5, 0, 0)  # alumni wait for their next answer


def test_a_player_the_nightly_job_missed_resets_on_their_next_answer(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    toni = join(signed_in, c, "Toni", "technical_director")
    set_rank(db, toni["id"], 1620.5, rank_best=TOP)
    clock.now = datetime(2027, 9, 2, 10, tzinfo=UTC)
    login(c, "toni@alu.comillas.edu", PASSWORD)  # the session went idle long ago
    reset = rank_rules.season_reset(1620.5, "technical_director")
    assert reset == 1200
    qid = bank[90001]
    r = practise(c, qid, right_answer(db, qid))
    gain = lp(db, qid, True, reset)
    assert (r["lp"], r["rank_points"], r["promoted"], r["demoted"]) == (
        approx(gain),
        approx(reset + gain),
        False,  # the reset is neither a promotion
        False,  # nor a demotion
    )
    row = db.execute(select(User.rank_season, User.rank_best).where(User.id == toni["id"])).one()
    assert tuple(row) == (2027, 12)
    assert (
        maintenance.run(db, clock.now)["ranks_reset"] == 1
    )  # only the admin: Toni is already in this season


def _answers(
    db: Session, clock: Clock, user_id: int, qid: int, *results: bool, late: bool | None = None
) -> None:
    for i, correct in enumerate(results):
        db.add(
            Attempt(
                user_id=user_id,
                question_id=qid,
                mode="practice",
                answer={},
                correct=correct,
                late=late,
                created_at=clock.now + timedelta(minutes=i),
            )
        )


def test_recalibration_follows_how_people_actually_do(
    db: Session, clock: Clock, admin: User, bank: dict[int, int]
) -> None:
    easy, hard = bank[90001], bank[90002]
    people = [
        db.scalar(
            insert(User)
            .values(email=f"p{i}@x.com", password_hash="x", display_name=f"P{i}")
            .returning(User.id)
        )
        for i in range(20)
    ]
    for i, uid in enumerate(people):
        assert uid is not None
        _answers(db, clock, uid, easy, True, False, False)  # only the first answer counts
        _answers(db, clock, uid, hard, i == 0, True, True)
    db.commit()
    assert xp.recalibrate(db) >= 2
    assert db.get_one(Question, easy, populate_existing=True).difficulty < 3
    assert db.get_one(Question, hard, populate_existing=True).difficulty > 3
    assert xp.recalibrate(db) == 0


def test_one_player_answering_again_and_again_moves_nothing(
    db: Session, clock: Clock, admin: User, bank: dict[int, int]
) -> None:
    _answers(db, clock, admin.id, bank[90001], *[False] * 40)
    _answers(db, clock, admin.id, bank[90002], *[False] * 40, late=True)
    db.commit()
    xp.recalibrate(db)
    for qid in (bank[90001], bank[90002]):  # one person is too few: back to the prior, not "hard"
        q = db.get_one(Question, qid, populate_existing=True)
        assert q.difficulty == xp_rules.difficulty(q.answer_kind, q.time_s)


def test_imported_questions_get_a_difficulty(db: Session, clock: Clock, tmp_path: Path) -> None:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    for q in db.scalars(select(Question)):
        assert q.difficulty == xp_rules.difficulty(q.answer_kind, q.time_s), q.fsquiz_id


def test_an_ungraded_question_pays_its_small_xp_once_a_day(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    qid = bank[90009]
    assert db.get_one(Question, qid).graded is False
    first = practise(c, qid, {"value": "anything"})
    again = practise(c, qid, {"value": "anything"})
    assert (first["xp"], first["lp"]) == (earned(None), 0)
    assert (again["xp"], again["lp"]) == (0, 0)  # no farming the participation XP
    next_madrid_day(c, clock)
    assert practise(c, qid, {"value": "anything"})["xp"] == earned(None)


def test_rested_xp_builds_while_away_and_doubles_xp_until_spent(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    practise(c, bank[90001], right_answer(db, bank[90001]))
    assert progress(c)["account"]["rested_xp"] == 0
    clock.advance(days=3)
    login(c, "ana@alu.comillas.edu", PASSWORD)
    assert progress(c)["account"]["rested_xp"] == 300  # two full days away
    qid = bank[90002]
    r = practise(c, qid, right_answer(db, qid))
    assert r["bonuses"]["rested"] == earned(True)  # the base again
    assert progress(c)["account"]["rested_xp"] == 300 - earned(True)


def test_a_freeze_is_earned_every_seven_days_and_saves_a_missed_one(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    first = daily_rules.madrid_day(clock.now)
    for i in range(7):  # seven on-time daily answers in a row
        day = first + timedelta(days=i)
        db.add(
            Attempt(
                user_id=ana["id"],
                question_id=bank[90001],
                mode="daily",
                answer={},
                correct=True,
                day=day,
                area="rules",
                created_at=clock.now + timedelta(days=i),
                submitted_at=clock.now + timedelta(days=i),
                late=False,
            )
        )
    db.commit()
    night = board_rules.madrid_midnight(first + timedelta(days=7)) + timedelta(hours=3)
    assert maintenance.run(db, night)["freezes_earned"] == 1
    assert maintenance.run(db, night)["freezes_earned"] == 0  # once per streak day
    # Day 8 is missed; the next night spends the freeze on it.
    after = maintenance.run(db, night + timedelta(days=1))
    assert (after["freezes_used"], after["freezes_earned"]) == (1, 0)
    clock.now = night + timedelta(days=1, hours=7)
    login(c, "ana@alu.comillas.edu", PASSWORD)
    account = progress(c)["account"]
    assert (account["streak"], account["streak_freezes"]) == (8, 0)


def test_an_abandoned_mock_question_is_charged_by_the_nightly_job_once(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    c = new_client()
    toni = join(signed_in, c, "Toni", "technical_director")
    state = c.post("/api/mock/quizzes/9002/start").json()
    qid = state["current"]["question"]["id"]
    clock.advance(days=2)
    closed = maintenance.run(db, clock.now)["mock_questions_closed"]
    assert closed == 1 and maintenance.run(db, clock.now)["mock_questions_closed"] == 0
    a = db.scalars(select(Attempt).where(Attempt.user_id == toni["id"], Attempt.question_id == qid)).one()
    assert (a.late, a.xp) == (True, 0) and a.lp < 0
    assert db.get_one(User, toni["id"]).rank_points == approx(1050 + a.lp)


def test_rested_xp_survives_a_daily_started_and_abandoned(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    practise(c, bank[90001], right_answer(db, bank[90001]))
    clock.advance(days=1)
    login(c, "ana@alu.comillas.edu", PASSWORD)
    c.post("/api/daily/mech/start")  # opened, never answered: not playing
    clock.advance(days=1)
    assert maintenance.run(db, clock.now)["dailies_closed"] == 1  # nor is the night closing it
    clock.advance(days=1)
    login(c, "ana@alu.comillas.edu", PASSWORD)
    assert progress(c)["account"]["rested_xp"] == 300  # two full days away
    clock.advance(days=3)
    login(c, "ana@alu.comillas.edu", PASSWORD)
    assert progress(c)["account"]["rested_xp"] == 450  # capped


def test_practice_earns_xp_and_never_moves_the_rank(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    right = practise(c, bank[90001], right_answer(db, bank[90001]))
    slip = practise(c, bank[90003], wrong(db, bank[90003]))
    unsure = c.post(
        f"/api/practice/questions/{bank[90008]}/answer", json={"options": [], "unsure": True}
    ).json()
    assert right["xp"] > 0 and slip["xp"] > 0
    assert (right["lp"], slip["lp"], unsure["lp"]) == (0, 0, 0)
    assert progress(c)["rank"]["points"] == 50


def test_a_night_the_job_missed_is_caught_up(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    first = daily_rules.madrid_day(clock.now)
    for i in (0, 1, 2, 4):  # day 4 (i = 3) missed
        db.add(
            Attempt(
                user_id=ana["id"],
                question_id=bank[90001],
                mode="daily",
                answer={},
                correct=True,
                day=first + timedelta(days=i),
                area="rules",
                created_at=clock.now + timedelta(days=i),
                submitted_at=clock.now + timedelta(days=i),
                late=False,
            )
        )
    db.execute(update(User).where(User.id == ana["id"]).values(streak_freezes=1))
    db.commit()
    # The job doesn't run the night after the missed day; the next night still saves it.
    night = board_rules.madrid_midnight(first + timedelta(days=5)) + timedelta(hours=3)
    assert maintenance.run(db, night)["freezes_used"] == 1
    clock.now = night + timedelta(hours=7)
    login(c, "ana@alu.comillas.edu", PASSWORD)
    assert progress(c)["account"]["streak"] == 5  # four played and the saved day
