from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Attempt, AuditLog, Question, User
from ifs_tests.domain import daily as daily_rules
from ifs_tests.domain.xp import START_LEVEL, TOP, award, difficulty, floor_for, level_for, xp_for_level
from ifs_tests.services import maintenance, xp
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import invite, options, register, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


def join(
    admin_client: TestClient, c: TestClient, name: str, position: str | None = None
) -> dict[str, object]:
    extra = {"position": position} if position else {}
    r = register(c, invite(admin_client), f"{name.lower()}@alu.comillas.edu", name, **extra)
    assert r.status_code == 201, r.text
    return dict(r.json())


def cost(db: Session, qid: int, mode: str, level: int, **kwargs: Any) -> int:
    """What a wrong answer to this question costs, from its own area, kind and number of options."""
    q = db.get_one(Question, qid)
    n = len(options(db, qid))
    return award(False, 3, mode, level, area=q.area, answer_kind=q.answer_kind, options=n, **kwargs)


@pytest.mark.parametrize(
    ("position", "level", "title", "aids", "penalty"),
    [
        (None, 0, "Mingo I", {"formulas": True, "learn_more": True, "hint": True}, 0),
        ("member", 3, "Mingo IV", {"formulas": True, "learn_more": True, "hint": True}, 5),
        ("department_head", 5, "Jefe I", {"formulas": False, "learn_more": False, "hint": True}, 15),
        ("technical_director", 10, "DT I", {"formulas": False, "learn_more": False, "hint": False}, 45),
    ],
)
def test_the_position_you_join_with_sets_your_starting_level(
    signed_in: TestClient,
    new_client: NewClient,
    position: str | None,
    level: int,
    title: str,
    aids: dict[str, bool],
    penalty: int,
) -> None:
    c = new_client()
    me = join(signed_in, c, "Ana", position)
    assert (me["position"], me["xp"]) == (position or "mingo", xp_for_level(level))
    progress = c.get("/api/me").json()["progress"]
    ladder = progress.pop("ladder")
    assert progress == {
        "level": level,
        "title": title,
        "tier": title.split()[0],
        "level_xp": xp_for_level(level),
        "next_level_xp": xp_for_level(level + 1),
        "penalty": penalty,
        "streak": 0,
        "streak_bonus": 0,
        "aids": aids,
    }
    assert [s["title"] for s in ladder][:3] == ["Mingo I", "Mingo II", "Mingo III"]
    assert ladder[TOP] == {
        "level": TOP,
        "tier": "Top",
        "title": None,  # a surprise until DT V
        "xp": xp_for_level(TOP),
        "aids": {"formulas": False, "learn_more": False, "hint": False},
        "penalty": 75,
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
    db.execute(update(User).where(User.id == ana["id"]).values(xp=xp_for_level(TOP - 1)))
    db.commit()
    progress = c.get("/api/me").json()["progress"]
    assert (progress["title"], progress["ladder"][TOP]["title"]) == ("DT V", top)
    db.execute(update(User).where(User.id == ana["id"]).values(xp=10**6))
    db.commit()
    progress = c.get("/api/me").json()["progress"]
    assert (progress["level"], progress["title"], progress["tier"], progress["next_level_xp"]) == (
        TOP,
        top,
        "Top",
        None,
    )


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


def test_admins_change_a_position_up_or_down_and_it_is_audited(
    signed_in: TestClient, new_client: NewClient, db: Session
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    r = signed_in.patch(f"/api/admin/users/{ana['id']}", json={"position": "department_head"})
    assert r.status_code == 200, r.text
    assert (r.json()["position"], r.json()["xp"]) == ("department_head", floor_for("department_head"))
    assert c.get("/api/me").json()["progress"]["title"] == "Jefe I"
    details = db.scalars(select(AuditLog.details).order_by(AuditLog.id.desc())).first()
    assert details == {"position": ["mingo", "department_head"]}
    lowered = signed_in.patch(f"/api/admin/users/{ana['id']}", json={"position": "mingo"}).json()
    assert (lowered["position"], lowered["xp"]) == ("mingo", floor_for("department_head"))  # XP never drops


def test_members_cannot_use_the_admin_route_to_change_positions(
    signed_in: TestClient, new_client: NewClient
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    assert (
        c.patch(f"/api/admin/users/{ana['id']}", json={"position": "technical_director"}).status_code == 403
    )


def test_practice_repeats_earn_a_tenth_once_a_day(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    qid = bank[90001]
    right = options(db, qid)[0]
    first = c.post(f"/api/practice/questions/{qid}/answer", json={"options": [right]}).json()
    for _ in range(3):
        assert c.post(f"/api/practice/questions/{qid}/answer", json={"options": [right]}).json()["xp"] == 0
    clock.advance(hours=11)
    c.get("/api/me")
    clock.advance(hours=2)  # past Madrid midnight; sessions go idle after 12 h
    again = c.post(f"/api/practice/questions/{qid}/answer", json={"options": [right]}).json()
    assert first["xp"] == award(True, 3, "practice", 0) == 12
    assert again["xp"] == award(True, 3, "practice", 0, repeat=True) == 1
    assert c.get("/api/me").json()["xp"] == 13


def test_wrong_answers_cost_xp_at_high_levels_but_never_below_the_position(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "technical_director")
    qid = bank[90001]
    wrong = options(db, qid)[1]
    r = c.post(f"/api/practice/questions/{qid}/answer", json={"options": [wrong]}).json()
    assert r["correct"] is False
    assert r["xp"] == cost(db, qid, "practice", START_LEVEL["technical_director"]) == -4  # a third: 4 options
    assert r["level"] == 10
    assert c.get("/api/me").json()["xp"] == floor_for("technical_director")
    assert db.scalars(select(Attempt.xp)).all() == [-4]


def test_a_penalty_comes_off_xp_earned_above_the_floor(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    toni = join(signed_in, c, "Toni", "technical_director")
    db.execute(update(User).where(User.id == toni["id"]).values(xp=floor_for("technical_director") + 100))
    db.commit()
    qid = bank[90001]
    c.post(f"/api/practice/questions/{qid}/answer", json={"options": [options(db, qid)[1]]})
    assert c.get("/api/me").json()["xp"] == floor_for("technical_director") + 96


def test_mingos_lose_nothing_for_wrong_answers(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    qid = bank[90001]
    r = c.post(f"/api/practice/questions/{qid}/answer", json={"options": [options(db, qid)[1]]}).json()
    assert (r["xp"], r["level"]) == (0, 0)


def test_the_leaderboard_ranks_by_xp_earned_and_shows_losses(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    ana, toni = new_client(), new_client()
    join(signed_in, ana, "Ana")
    join(signed_in, toni, "Toni", "technical_director")
    qid = bank[90001]
    right, wrong = options(db, qid)[:2]
    ana.post(f"/api/practice/questions/{qid}/answer", json={"options": [right]})
    toni.post(f"/api/practice/questions/{qid}/answer", json={"options": [wrong]})
    rows = ana.get("/api/leaderboard").json()["rows"]
    assert [(r["display_name"], r["xp"], r["title"], r["level"]) for r in rows] == [
        ("Ana", 12, "Mingo I", 0),
        ("Toni", -4, "DT I", 10),  # the badge shows lifetime level, not the period's XP
    ]
    assert toni.get("/api/leaderboard").json()["me"]["xp"] == -4


def test_the_streak_shows_on_the_profile_and_boosts_gains(
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
    progress = c.get("/api/me").json()["progress"]
    assert (progress["streak"], progress["streak_bonus"]) == (3, 10)
    other = bank[90002]
    r = c.post(f"/api/practice/questions/{other}/answer", json=right_answer(db, other)).json()
    assert r["xp"] == award(True, 3, "practice", 0, streak_days=3) == 14


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
        assert q.difficulty == difficulty(q.answer_kind, q.time_s)


def test_a_question_seen_before_earns_a_tenth_in_every_mode(
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
    assert r["xp"] == award(True, 3, "daily", 0, repeat=True) == 5

    seen = bank[90001]  # the first question of quiz 9002
    c.post(f"/api/practice/questions/{seen}/answer", json=right_answer(db, seen))
    state = c.post("/api/mock/quizzes/9002/start").json()
    assert state["current"]["question"]["id"] == seen
    state = c.post(
        f"/api/mock/sessions/{state['session_id']}/answer",
        json={"attempt_id": state["current"]["attempt_id"], **right_answer(db, seen)},
    ).json()
    while state["current"]:
        body = right_answer(db, state["current"]["question"]["id"])
        state = c.post(
            f"/api/mock/sessions/{state['session_id']}/answer",
            json={"attempt_id": state["current"]["attempt_id"], **body},
        ).json()
    items = [i["feedback"]["xp"] for i in state["summary"]["items"]]
    assert items[0] == award(True, 3, "mock", 0, repeat=True) and items[1] == award(True, 3, "mock", 0)


def test_practice_wrong_then_right_earns_nothing_more_that_day(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    qid = bank[90001]
    right, wrong = options(db, qid)[:2]
    assert c.post(f"/api/practice/questions/{qid}/answer", json={"options": [wrong]}).json()["xp"] == 0
    assert c.post(f"/api/practice/questions/{qid}/answer", json={"options": [right]}).json()["xp"] == 0
    assert c.get("/api/me").json()["xp"] == 0


def test_the_answer_that_crosses_a_level_says_so(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    db.execute(update(User).where(User.id == ana["id"]).values(xp=xp_for_level(1) - 1))
    db.commit()
    qid = bank[90001]
    first = c.post(f"/api/practice/questions/{qid}/answer", json={"options": [options(db, qid)[0]]}).json()
    assert (first["level"], first["level_up"]) == (1, True)
    other = bank[90002]
    second = c.post(f"/api/practice/questions/{other}/answer", json=right_answer(db, other)).json()
    assert (second["level"], second["level_up"]) == (1, False)


def test_you_keep_your_place_when_xp_won_and_lost_cancel_out(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    toni = join(signed_in, c, "Toni", "technical_director")
    qid = bank[90001]
    for xp_amount in (9, -9):
        db.add(
            Attempt(
                user_id=toni["id"],
                question_id=qid,
                mode="practice",
                answer={},
                correct=xp_amount > 0,
                created_at=datetime.now(UTC),
                xp=xp_amount,
            )
        )
    db.commit()
    board = c.get("/api/leaderboard").json()
    assert board["me"] is not None and board["me"]["xp"] == 0


def _wrong(started: dict[str, Any]) -> dict[str, Any]:
    opts = [o["id"] for o in started["question"]["options"]]
    return {"options": opts} if opts else {"value": "-1"}


def test_a_daily_left_to_run_out_costs_like_a_wrong_answer(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "technical_director")
    started = c.post("/api/daily/mech/start").json()
    clock.now = datetime.fromisoformat(started["deadline_at"]) + timedelta(seconds=4)
    area = c.get("/api/daily").json()["areas"][0]
    penalty = cost(db, started["question"]["id"], "daily", START_LEVEL["technical_director"], late=True)
    assert (area["state"], area["late"], area["correct"], area["xp"]) == ("done", True, False, penalty)
    assert c.get("/api/me").json()["progress"]["streak"] == 0
    stored = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=_wrong(started)).json()
    assert stored["xp"] == penalty  # already closed: nothing changes
    assert db.scalars(select(Attempt.xp).where(Attempt.mode == "daily")).all() == [penalty]


def test_the_nightly_job_closes_abandoned_dailies_once(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c, d = new_client(), new_client()
    join(signed_in, c, "Toni", "department_head")
    join(signed_in, d, "Ana")
    c.post("/api/daily/mech/start")
    d.post("/api/daily/mech/start")
    fresh = c.post("/api/daily/elec/start").json()
    clock.advance(minutes=30)
    db.execute(update(Attempt).where(Attempt.id == fresh["attempt_id"]).values(deadline_at=clock.now))
    db.commit()
    assert maintenance.run(db, clock.now)["dailies_closed"] == 2  # the one still inside its grace stays open
    assert maintenance.run(db, clock.now)["dailies_closed"] == 0
    got = dict(db.execute(select(Attempt.user_id, Attempt.xp).where(Attempt.area == "mech")).tuples().all())
    assert sorted(got.values()) == [
        award(False, 3, "daily", START_LEVEL["department_head"]),
        0,
    ]  # a mingo loses nothing


def test_a_daily_answer_reports_the_level_it_left_you_at(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    started = c.post("/api/daily/mech/start").json()
    r = c.post(
        f"/api/daily/attempts/{started['attempt_id']}/answer",
        json=right_answer(db, started["question"]["id"]),
    ).json()
    assert (r["feedback"]["xp"], r["feedback"]["level"]) == (award(True, 3, "daily", 0), level_for(r["xp"]))


def test_a_mock_question_left_to_run_out_costs_like_a_wrong_answer(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "department_head")
    state = c.post("/api/mock/quizzes/9002/start").json()
    clock.now = datetime.fromisoformat(state["current"]["deadline_at"]) + timedelta(seconds=4)
    state = c.get(f"/api/mock/sessions/{state['session_id']}").json()
    c.get(f"/api/mock/sessions/{state['session_id']}")  # reloading doesn't charge twice
    while state["current"]:
        body = right_answer(db, state["current"]["question"]["id"])
        state = c.post(
            f"/api/mock/sessions/{state['session_id']}/answer",
            json={"attempt_id": state["current"]["attempt_id"], **body},
        ).json()
    items = [i["feedback"]["xp"] for i in state["summary"]["items"]]
    dh = START_LEVEL["department_head"]
    assert items == [award(False, 3, "mock", dh)] + [award(True, 3, "mock", dh)] * 4
    assert state["summary"]["xp"] == sum(items)


def test_imported_questions_get_a_difficulty(db: Session, clock: Clock, tmp_path: Path) -> None:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    for q in db.scalars(select(Question)):
        assert q.difficulty == difficulty(q.answer_kind, q.time_s), q.fsquiz_id


def test_at_the_top_rules_cost_most_and_typed_answers_least(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    toni = join(signed_in, c, "Toni", "technical_director")
    db.execute(update(User).where(User.id == toni["id"]).values(xp=xp_for_level(TOP) + 1000))
    db.commit()
    cases = {
        90008: ("rules", "choice-one", -9),
        90001: ("mech", "choice-one", -4),
        90003: ("elec", "choice-many", -5),
        90002: ("mech", "number", -2),
    }
    for fsquiz_id, (area, kind, xp_lost) in cases.items():
        q = db.get_one(Question, bank[fsquiz_id])
        assert (q.area, q.answer_kind) == (area, kind)
        body = (
            {"value": "-1"}
            if kind == "number"
            else {"options": [o for o in options(db, q.id) if o not in right_answer(db, q.id)["options"]][:1]}
        )
        r = c.post(f"/api/practice/questions/{q.id}/answer", json=body).json()
        assert (r["correct"], r["xp"]) == (False, xp_lost), fsquiz_id
        assert r["xp"] == cost(db, q.id, "practice", TOP)


def test_im_not_sure_in_practice_shows_the_answer_for_nothing(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "technical_director")
    qid = bank[90008]
    r = c.post(
        f"/api/practice/questions/{qid}/answer", json={"unsure": True, "options": [options(db, qid)[0]]}
    ).json()
    assert (r["correct"], r["passed"], r["xp"]) == (False, True, 0)
    assert r["official"] and r["correct_options"]
    a = db.scalars(select(Attempt)).one()
    assert (a.passed, a.correct, a.answer["unsure"]) == (True, False, True)
    clock.advance(hours=11)
    c.get("/api/me")
    clock.advance(hours=2)
    again = c.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid)).json()
    assert again["xp"] == award(
        True, 3, "practice", START_LEVEL["technical_director"], repeat=True
    )  # already seen


def test_im_not_sure_does_nothing_for_an_ungraded_question(
    signed_in: TestClient, new_client: NewClient, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    r = c.post(f"/api/practice/questions/{bank[90009]}/answer", json={"unsure": True}).json()
    assert (r["correct"], r["passed"], r["xp"]) == (None, False, 0)


def test_im_not_sure_in_the_daily_keeps_the_streak_but_not_after_the_clock(
    signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "technical_director")
    started = c.post("/api/daily/mech/start").json()
    r = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json={"unsure": True}).json()
    assert (r["feedback"]["passed"], r["feedback"]["correct"], r["xp"], r["streak"]) == (True, False, 0, 1)
    review = c.get("/api/daily/mech/review").json()
    assert (review["feedback"]["passed"], review["xp"]) == (True, 0)
    late = c.post("/api/daily/elec/start").json()
    clock.now = datetime.fromisoformat(late["deadline_at"]) + timedelta(seconds=10)
    r = c.post(f"/api/daily/attempts/{late['attempt_id']}/answer", json={"unsure": True}).json()
    assert (
        r["xp"] == cost(db, late["question"]["id"], "daily", START_LEVEL["technical_director"], late=True) < 0
    )


def test_im_not_sure_in_a_mock_quiz_moves_on_for_nothing(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "technical_director")
    state = c.post("/api/mock/quizzes/9002/start").json()
    first = True
    while state["current"]:
        body = {"unsure": True} if first else right_answer(db, state["current"]["question"]["id"])
        first = False
        state = c.post(
            f"/api/mock/sessions/{state['session_id']}/answer",
            json={"attempt_id": state["current"]["attempt_id"], **body},
        ).json()
    items = state["summary"]["items"]
    assert (items[0]["feedback"]["passed"], items[0]["feedback"]["xp"], items[0]["feedback"]["correct"]) == (
        True,
        0,
        False,
    )
    assert state["summary"]["correct"] == len(items) - 1
