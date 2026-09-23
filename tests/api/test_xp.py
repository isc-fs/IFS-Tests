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
from ifs_tests.db.models import AnswerOption, Attempt, AuditLog, Question, User
from ifs_tests.domain import daily as daily_rules
from ifs_tests.domain.xp import RANKS, TOP, award, difficulty, floor_for, level_for, xp_for_level
from ifs_tests.services import maintenance, xp
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import invite, login, register, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


@pytest.fixture
def bank(db: Session, clock: Clock, tmp_path: Path) -> dict[int, int]:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.execute(update(Question).values(difficulty=3))
    db.commit()
    return {fsquiz_id: qid for fsquiz_id, qid in db.execute(select(Question.fsquiz_id, Question.id))}


def join(admin_client: TestClient, c: TestClient, name: str, rank: str | None = None) -> dict[str, object]:
    extra = {"rank": rank} if rank else {}
    r = register(c, invite(admin_client), f"{name.lower()}@alu.comillas.edu", name, **extra)
    assert r.status_code == 201, r.text
    return dict(r.json())


@pytest.fixture
def signed_in(app_client: TestClient, admin: User) -> TestClient:
    login(app_client)
    return app_client


def options(db: Session, qid: int) -> list[int]:
    return list(
        db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == qid).order_by("position"))
    )


@pytest.mark.parametrize(
    ("rank", "level", "title", "aids", "penalty"),
    [
        (None, 0, "Mingo I", {"formulas": True, "learn_more": True, "hint": True}, 0),
        ("member", 3, "Mingo IV", {"formulas": True, "learn_more": True, "hint": True}, 5),
        ("department_head", 5, "Jefe I", {"formulas": False, "learn_more": False, "hint": True}, 15),
        ("technical_director", 10, "DT I", {"formulas": False, "learn_more": False, "hint": False}, 45),
    ],
)
def test_the_rank_you_join_with_sets_your_starting_level(
    signed_in: TestClient,
    new_client: NewClient,
    rank: str | None,
    level: int,
    title: str,
    aids: dict[str, bool],
    penalty: int,
) -> None:
    c = new_client()
    me = join(signed_in, c, "Ana", rank)
    assert (me["rank"], me["xp"]) == (rank or "mingo", xp_for_level(level))
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


def test_an_unknown_rank_is_refused(signed_in: TestClient, new_client: NewClient) -> None:
    r = register(new_client(), invite(signed_in), "ana@alu.comillas.edu", "Ana", rank="team_principal")
    assert r.status_code == 422


def test_people_move_their_own_rank_up_only_and_it_is_audited(
    signed_in: TestClient, new_client: NewClient, db: Session
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    up = c.patch("/api/me", json={"rank": "department_head"}).json()
    assert (up["rank"], up["xp"], up["progress"]["title"]) == (
        "department_head",
        floor_for("department_head"),
        "Jefe I",
    )
    down = c.patch("/api/me", json={"rank": "mingo"})
    assert down.status_code == 403
    assert down.json()["fields"] == {"rank": "Only an admin can lower your rank."}
    assert c.patch("/api/me", json={"rank": "department_head", "display_name": "Ana B"}).status_code == 200
    assert c.patch("/api/me", json={"rank": "boss"}).status_code == 422
    audit = db.execute(
        select(AuditLog.action, AuditLog.actor_id, AuditLog.details).where(AuditLog.action == "user.rank")
    )
    assert [tuple(a) for a in audit] == [("user.rank", ana["id"], {"rank": ["mingo", "department_head"]})]
    lowered = signed_in.patch(f"/api/admin/users/{ana['id']}", json={"rank": "mingo"}).json()
    assert (lowered["rank"], lowered["xp"]) == ("mingo", floor_for("department_head"))  # XP never drops


def test_admins_correct_a_rank_and_it_is_audited(
    signed_in: TestClient, new_client: NewClient, db: Session
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    r = signed_in.patch(f"/api/admin/users/{ana['id']}", json={"rank": "member"})
    assert r.status_code == 200, r.text
    assert (r.json()["rank"], r.json()["xp"]) == ("member", floor_for("member"))
    assert c.get("/api/me").json()["progress"]["title"] == "Mingo IV"
    actions = [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert actions[-1] == "user.update"
    details = db.scalars(select(AuditLog.details).order_by(AuditLog.id.desc())).first()
    assert details == {"rank": ["mingo", "member"]}


def test_members_cannot_use_the_admin_route_to_change_ranks(
    signed_in: TestClient, new_client: NewClient
) -> None:
    c = new_client()
    ana = join(signed_in, c, "Ana")
    assert c.patch(f"/api/admin/users/{ana['id']}", json={"rank": "technical_director"}).status_code == 403


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


def test_wrong_answers_cost_xp_at_high_levels_but_never_below_the_rank(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", "technical_director")
    qid = bank[90001]
    wrong = options(db, qid)[1]
    r = c.post(f"/api/practice/questions/{qid}/answer", json={"options": [wrong]}).json()
    assert r["correct"] is False
    assert r["xp"] == award(False, 3, "practice", RANKS["technical_director"]) == -6
    assert r["level"] == 10
    assert c.get("/api/me").json()["xp"] == floor_for("technical_director")
    assert db.scalars(select(Attempt.xp)).all() == [-6]


def test_a_penalty_comes_off_xp_earned_above_the_floor(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    toni = join(signed_in, c, "Toni", "technical_director")
    db.execute(update(User).where(User.id == toni["id"]).values(xp=floor_for("technical_director") + 100))
    db.commit()
    qid = bank[90001]
    c.post(f"/api/practice/questions/{qid}/answer", json={"options": [options(db, qid)[1]]})
    assert c.get("/api/me").json()["xp"] == floor_for("technical_director") + 94


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
        ("Toni", -6, "DT I", 10),  # the badge shows lifetime level, not the period's XP
    ]
    assert toni.get("/api/leaderboard").json()["me"]["xp"] == -6


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
    join(signed_in, c, "Ana")
    started = c.post("/api/daily/mech/start").json()
    qid = started["question"]["id"]
    c.post(f"/api/practice/questions/{qid}/answer", json=_wrong(started))  # sees the official answer
    r = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=right_answer(db, qid)).json()
    assert r["xp"] == award(True, 3, "daily", 0, repeat=True) == 5

    state = c.post("/api/mock/quizzes/9002/start").json()
    seen = state["current"]["question"]["id"]
    c.post(f"/api/practice/questions/{seen}/answer", json=right_answer(db, seen))
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
    penalty = award(False, 3, "daily", RANKS["technical_director"])
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
        award(False, 3, "daily", RANKS["department_head"]),
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
    dh = RANKS["department_head"]
    assert items == [award(False, 3, "mock", dh)] + [award(True, 3, "mock", dh)] * 4
    assert state["summary"]["xp"] == sum(items)


def test_imported_questions_get_a_difficulty(db: Session, clock: Clock, tmp_path: Path) -> None:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    for q in db.scalars(select(Question)):
        assert q.difficulty == difficulty(q.answer_kind, q.time_s), q.fsquiz_id
