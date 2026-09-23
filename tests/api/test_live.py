from __future__ import annotations

import csv
import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Attempt, Question, User
from ifs_tests.domain.xp import award, xp_for_level
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import invite, login, register, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]
ANSWER_WORDS = ("official", "correct_options", "solutions")


@pytest.fixture
def bank(db: Session, clock: Clock, tmp_path: Path) -> dict[int, int]:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.execute(update(Question).values(difficulty=3))
    db.commit()
    return {fsquiz_id: qid for fsquiz_id, qid in db.execute(select(Question.fsquiz_id, Question.id))}


@pytest.fixture
def room(app_client: TestClient, admin: User, new_client: NewClient, bank: dict[int, int]) -> dict[str, Any]:
    """A TD host and four players: Ana and Leo (aero), Marta and Pau (batteries)."""
    login(app_client)
    people: dict[str, Any] = {}
    for name, position, subs in [
        ("Tere", "technical_director", []),
        ("Ana", "mingo", ["AE"]),
        ("Leo", "department_head", ["AE"]),
        ("Marta", "mingo", ["BT"]),
        ("Pau", "member", ["BT"]),
    ]:
        c = new_client()
        r = register(c, invite(app_client), f"{name.lower()}@alu.comillas.edu", name, position=position)
        assert r.status_code == 201, r.text
        if subs:
            assert c.patch("/api/me", json={"subdepartments": subs}).status_code == 200
        people[name] = c
        people[f"{name}_id"] = r.json()["id"]
    return people


def create(host: TestClient, **config: Any) -> str:
    r = host.post("/api/live/sessions", json={"count": 2, "timing": "fixed", "seconds": 60, **config})
    assert r.status_code == 201, r.text
    return str(r.json()["code"])


def state(c: TestClient, code: str) -> dict[str, Any]:
    r = c.get(f"/api/live/sessions/{code}")
    assert r.status_code == 200, r.text
    return dict(r.json())


def lobby(room: dict[str, Any], **config: Any) -> str:
    """A session with everyone joined, seated at the Aero and Batteries tables by sub-department."""
    code = create(room["Tere"], **config)
    for name in ("Ana", "Leo", "Marta", "Pau"):
        assert room[name].post(f"/api/live/sessions/{code}/join").status_code == 200
    assert room["Tere"].post(f"/api/live/sessions/{code}/tables/auto").status_code == 204
    return code


def tables(room: dict[str, Any], code: str) -> dict[str, dict[str, Any]]:
    return {t["name"]: t for t in state(room["Tere"], code)["tables"]}


def advance(room: dict[str, Any], code: str) -> None:
    assert room["Tere"].post(f"/api/live/sessions/{code}/advance").status_code == 204


def send(c: TestClient, code: str, body: dict[str, Any]) -> int:
    return int(c.post(f"/api/live/sessions/{code}/answer", json=body).status_code)


def wrong(db: Session, qid: int) -> dict[str, Any]:
    body = right_answer(db, qid)
    return {"options": []} if "options" in body else {"value": "-99999"}


def test_hosting_follows_the_position_on_the_team_never_the_xp_level(
    room: dict[str, Any], db: Session, app_client: TestClient
) -> None:
    db.execute(
        update(User).where(User.id == room["Ana_id"]).values(xp=xp_for_level(14))
    )  # DT V on the ladder
    db.commit()
    assert room["Ana"].get("/api/me").json()["can_host"] is False
    assert room["Ana"].post("/api/live/sessions", json={}).status_code == 403
    assert room["Tere"].get("/api/me").json()["can_host"] is True
    assert room["Tere"].post("/api/live/sessions", json={}).status_code == 201
    assert app_client.post("/api/live/sessions", json={}).status_code == 201  # admins host too


def test_joining_with_a_code_and_what_outsiders_see(room: dict[str, Any], new_client: NewClient) -> None:
    code = create(room["Tere"])
    assert room["Ana"].get(f"/api/live/sessions/{code}").status_code == 403  # join first
    joined = room["Ana"].post(f"/api/live/sessions/{code.lower()}/join").json()
    assert (joined["state"], joined["role"], joined["host_name"]) == ("lobby", "player", "Tere")
    assert room["Ana"].post(f"/api/live/sessions/{code}/join").status_code == 200  # joining twice is harmless
    assert [p["name"] for p in state(room["Tere"], code)["players"]] == ["Ana"]
    assert room["Ana"].get("/api/live/sessions/ZZZZZZ").status_code == 404
    assert room["Ana"].get("/api/live/sessions/bad!").status_code == 422
    assert new_client().get(f"/api/live/sessions/{code}").status_code == 401


def test_seating_by_subdepartment_makes_specialist_tables_with_the_senior_member_as_captain(
    room: dict[str, Any],
) -> None:
    code = lobby(room)
    t = tables(room, code)
    assert set(t) == {"Aerodynamics", "Batteries"}
    assert sorted(t["Aerodynamics"]["member_ids"]) == sorted([room["Ana_id"], room["Leo_id"]])
    assert t["Aerodynamics"]["captain_id"] == room["Leo_id"]  # Department Head outranks a Mingo
    assert (t["Aerodynamics"]["topics"], t["Batteries"]["topics"]) == (["aero"], ["hv"])


def test_seating_by_hand_is_checked(room: dict[str, Any], new_client: NewClient) -> None:
    code = lobby(room)
    url = f"/api/live/sessions/{code}/tables"
    ana, leo, marta = room["Ana_id"], room["Leo_id"], room["Marta_id"]
    bad = [
        [{"name": "A", "member_ids": [ana, 99999]}],  # not in the session
        [{"name": "A", "member_ids": [ana]}, {"name": "B", "member_ids": [ana]}],  # at two tables
        [{"name": "A", "member_ids": [ana], "captain_id": leo}],  # captain elsewhere
    ]
    for tables_in in bad:
        assert room["Tere"].put(url, json={"tables": tables_in}).status_code == 400, tables_in
    ok = [
        {
            "name": "Mixed",
            "member_ids": [ana, marta],
            "captain_id": marta,
            "topics": ["hv"],
            "catch_all": True,
        }
    ]
    assert room["Tere"].put(url, json={"tables": ok}).status_code == 204
    assert room["Ana"].put(url, json={"tables": ok}).status_code == 403  # only the host


def test_only_captains_answer_every_table_shares_its_result_and_answers_stay_hidden_until_the_close(
    room: dict[str, Any], db: Session
) -> None:
    code = lobby(room, areas=["rules"])
    advance(room, code)
    s = state(room["Ana"], code)
    assert s["state"] == "open" and s["question"] and s["question_table_id"] is None
    assert not s["reveals"] and s["room_right"] is None
    assert not any(w in str(s) for w in ANSWER_WORDS)
    qid = s["question"]["id"]
    assert send(room["Ana"], code, right_answer(db, qid)) == 403  # Leo captains Aero
    assert send(room["Leo"], code, right_answer(db, qid)) == 204
    assert send(room["Leo"], code, right_answer(db, qid)) == 409  # one answer per table
    assert state(room["Ana"], code)["my_answer"] is not None
    assert state(room["Marta"], code)["my_answer"] is None  # the other table's answer is theirs to know
    assert send(room["Pau"], code, wrong(db, qid)) == 204  # the last table answering closes the question
    closed = state(room["Marta"], code)
    assert closed["state"] == "closed"
    reveal = closed["reveals"][0]
    assert reveal["feedback"]["official"] and {a["table_id"]: a["correct"] for a in reveal["answers"]} == {
        tables(room, code)["Aerodynamics"]["id"]: True,
        tables(room, code)["Batteries"]["id"]: False,
    }
    assert (closed["room_right"], closed["room_asked"]) == (1, 1)  # the best table, when every table answers
    gained = award(True, 3, "live", 0)
    xp = dict(db.execute(select(Attempt.user_id, Attempt.xp).where(Attempt.mode == "live")).tuples().all())
    assert xp[room["Ana_id"]] == xp[room["Leo_id"]] > 0 and xp[room["Ana_id"]] == gained
    assert xp[room["Marta_id"]] == 0  # a Mingo loses nothing
    assert xp[room["Pau_id"]] < 0  # a returning member starts at Mingo IV, where wrong answers cost
    board = room["Ana"].get("/api/leaderboard").json()
    assert {r["display_name"]: r["xp"] for r in board["rows"]}["Ana"] == gained


def test_proposals_reach_the_captain_of_the_table_that_answers(room: dict[str, Any], db: Session) -> None:
    code = lobby(room, areas=["rules"])
    advance(room, code)
    qid = state(room["Ana"], code)["question"]["id"]
    body = right_answer(db, qid)
    assert room["Ana"].put(f"/api/live/sessions/{code}/proposal", json=body).status_code == 204
    seen_by_leo = state(room["Leo"], code)["proposals"]
    assert [(p["name"], p["options"]) for p in seen_by_leo] == [("Ana", body["options"])]
    assert state(room["Marta"], code)["proposals"] == []  # another table's proposals stay at that table


def test_specialists_each_question_goes_to_the_table_owning_its_topic(
    room: dict[str, Any], db: Session, bank: dict[int, int]
) -> None:
    code = lobby(room, topics=["hv"], areas=[], count=1, routing="owners")
    advance(room, code)
    s = state(room["Marta"], code)
    t = tables(room, code)
    assert s["question_table_id"] == t["Batteries"]["id"]
    qid = s["question"]["id"]
    assert send(room["Leo"], code, right_answer(db, qid)) == 403  # not Aero's question
    body = right_answer(db, qid)
    assert room["Ana"].put(f"/api/live/sessions/{code}/proposal", json=body).status_code == 204
    assert [p["name"] for p in state(room["Pau"], code)["proposals"]] == ["Ana"]  # to the owning captain
    assert send(room["Pau"], code, body) == 204
    closed = state(room["Ana"], code)
    assert (closed["state"], closed["room_right"], closed["room_asked"]) == ("closed", 1, 1)
    live_xp = dict(
        db.execute(select(Attempt.user_id, Attempt.xp).where(Attempt.mode == "live")).tuples().all()
    )
    assert set(live_xp) == {room["Marta_id"], room["Pau_id"]}  # only the table that answered


def test_a_rehearsal_reveals_nothing_until_the_end(
    room: dict[str, Any], db: Session, bank: dict[int, int]
) -> None:
    code = lobby(room, questions="quiz", quiz_id=9002, timing="real", feedback="end")
    advance(room, code)
    s = state(room["Ana"], code)
    assert s["total"] == 5 and s["budget_s"]  # each question on its real time budget
    for _ in range(s["total"]):
        qid = state(room["Leo"], code)["question"]["id"]
        send(room["Leo"], code, right_answer(db, qid))
        advance(room, code)  # closes the question (the Batteries table never answers)
        closed = state(room["Ana"], code)
        assert closed["reveals"] == [] and closed["room_right"] is None
        advance(room, code)
    done = state(room["Ana"], code)
    assert done["state"] == "finished" and len(done["reveals"]) == 5
    assert done["room_right"] == 5 and done["room_asked"] == 5
    assert room["Tere"].post(f"/api/live/sessions/{code}/advance").status_code == 409


def test_time_runs_out_on_the_server(room: dict[str, Any], db: Session, clock: Clock) -> None:
    code = lobby(room, areas=["rules"], seconds=30)
    advance(room, code)
    qid = state(room["Leo"], code)["question"]["id"]
    clock.advance(seconds=34)
    assert send(room["Leo"], code, right_answer(db, qid)) == 409
    assert state(room["Ana"], code)["state"] == "closed"


def test_speed_points_reward_fast_right_answers_when_switched_on(
    room: dict[str, Any], db: Session, clock: Clock
) -> None:
    code = lobby(room, areas=["rules"], seconds=60, speed_points=True)
    advance(room, code)
    qid = state(room["Leo"], code)["question"]["id"]
    clock.advance(seconds=30)
    send(room["Leo"], code, right_answer(db, qid))
    send(room["Pau"], code, wrong(db, qid))
    points = {t["name"]: t["points"] for t in state(room["Tere"], code)["tables"]}
    assert points == {"Aerodynamics": 750, "Batteries": 0}


def test_im_not_sure_from_a_captain_costs_nothing(room: dict[str, Any], db: Session) -> None:
    db.execute(update(User).where(User.id == room["Leo_id"]).values(xp=xp_for_level(12)))
    db.commit()
    code = lobby(room, areas=["rules"])
    advance(room, code)
    assert send(room["Leo"], code, {"unsure": True}) == 204
    passed = db.scalars(
        select(Attempt).where(Attempt.mode == "live", Attempt.user_id == room["Leo_id"])
    ).one()
    assert (passed.passed, passed.xp) == (True, 0)


def test_the_host_moves_people_between_questions_and_removes_them(room: dict[str, Any], db: Session) -> None:
    code = lobby(room, areas=["rules"])
    t = tables(room, code)
    url = f"/api/live/sessions/{code}"
    advance(room, code)
    assert (
        room["Tere"]
        .put(f"{url}/players/{room['Leo_id']}", json={"table_id": t["Batteries"]["id"]})
        .status_code
        == 204
    )
    assert tables(room, code)["Aerodynamics"]["captain_id"] is None  # a captain who moves stops captaining
    ana = room["Ana_id"]
    assert (
        room["Tere"].patch(f"{url}/tables/{t['Aerodynamics']['id']}", json={"captain_id": ana}).status_code
        == 204
    )
    assert (
        room["Tere"].patch(f"{url}/tables/{t['Batteries']['id']}", json={"captain_id": ana}).status_code
        == 400
    )
    assert room["Tere"].delete(f"{url}/players/{room['Pau_id']}").status_code == 204
    assert room["Pau"].get(url).status_code == 403
    assert room["Ana"].put(f"{url}/players/{ana}", json={"table_id": None}).status_code == 403
    assert room["Tere"].post(f"{url}/end").status_code == 204
    assert room["Ana"].post(f"{url}/join").status_code == 409


def test_the_host_downloads_the_results_as_a_safe_csv(room: dict[str, Any], db: Session) -> None:
    code = lobby(room, areas=["rules"], count=1)
    assert (
        room["Tere"]
        .patch(
            f"/api/live/sessions/{code}/tables/{tables(room, code)['Aerodynamics']['id']}",
            json={"name": "=HYPERLINK(1)"},
        )
        .status_code
        == 204
    )
    advance(room, code)
    qid = state(room["Leo"], code)["question"]["id"]
    send(room["Leo"], code, right_answer(db, qid))
    r = room["Tere"].get(f"/api/live/sessions/{code}/results.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:3] == ["question", "text", "answered by"]
    assert any(row[3] == "'=HYPERLINK(1)" and row[6] == "yes" for row in rows[1:])
    assert room["Ana"].get(f"/api/live/sessions/{code}/results.csv").status_code == 403


def test_the_events_stream_announces_the_version(
    room: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ifs_tests.api.routes.live.STREAM_SECONDS", 1)
    code = lobby(room)
    with room["Ana"].stream("GET", f"/api/live/sessions/{code}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["x-accel-buffering"] == "no"
        first = next(r.iter_lines())
    assert first == f"data: {state(room['Ana'], code)['version']}"
    assert room["Marta"].get("/api/live/sessions/AAAAAA/events").status_code == 404


def test_settings_are_fixed_once_started_and_questions_must_exist(room: dict[str, Any]) -> None:
    code = lobby(room, areas=["rules"])
    url = f"/api/live/sessions/{code}"
    assert room["Tere"].put(f"{url}/config", json={"areas": ["mech"]}).status_code == 204
    empty = lobby(room, topics=["aero"], areas=[])
    assert room["Tere"].post(f"/api/live/sessions/{empty}/advance").status_code == 409  # no aero questions
    advance(room, code)
    assert room["Tere"].put(f"{url}/config", json={"areas": ["rules"]}).status_code == 409
    assert room["Tere"].post("/api/live/sessions", json={"questions": "quiz"}).status_code == 422
    assert (
        room["Tere"].post("/api/live/sessions", json={"questions": "quiz", "quiz_id": 424242}).status_code
        == 404
    )


def test_subdepartments_come_from_the_team_directory(room: dict[str, Any]) -> None:
    listed = room["Ana"].get("/api/live/subdepartments").json()
    assert {"code": "AE", "name": "Aerodynamics", "vertical": "Mechanical", "topics": ["aero"]} in listed
    assert room["Ana"].get("/api/me").json()["subdepartments"] == ["AE"]
    assert room["Ana"].patch("/api/me", json={"subdepartments": ["XX"]}).status_code == 400


def test_a_session_needs_a_captain_to_start(room: dict[str, Any]) -> None:
    code = create(room["Tere"], areas=["rules"])
    assert room["Tere"].post(f"/api/live/sessions/{code}/advance").status_code == 409
