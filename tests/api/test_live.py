from __future__ import annotations

import csv
import io
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ifs_tests.db.models import Attempt, User
from ifs_tests.domain.xp import award, xp_for_level

from ..conftest import Clock
from .helpers import invite, login, register, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]
ANSWER_WORDS = ("official", "correct_options", "solutions")


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
    assert rows[0][5:8] == ["answer", "official answer", "right"]
    assert any(row[3] == "'=HYPERLINK(1)" and row[7] == "yes" and row[6] for row in rows[1:])
    assert not any(row[5].isdigit() for row in rows[1:])  # option text, not database ids
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


# From the adversarial review


def test_a_host_cannot_touch_the_tables_or_players_of_another_session(
    room: dict[str, Any], app_client: Any, new_client: NewClient
) -> None:
    mine = lobby(room, areas=["rules"])
    other_td = new_client()
    assert (
        register(
            other_td, invite(app_client), "rui@alu.comillas.edu", "Rui", position="technical_director"
        ).status_code
        == 201
    )
    theirs = create(other_td)
    assert room["Ana"].post(f"/api/live/sessions/{theirs}/join").status_code == 200
    aero = tables(room, mine)["Aerodynamics"]["id"]
    url = f"/api/live/sessions/{theirs}"
    assert other_td.patch(f"{url}/tables/{aero}", json={"name": "pwned"}).status_code == 404
    assert other_td.put(f"{url}/players/{room['Ana_id']}", json={"table_id": aero}).status_code == 404
    # another TD is not the host of this session
    assert other_td.post(f"/api/live/sessions/{mine}/advance").status_code == 403
    assert other_td.delete(f"/api/live/sessions/{mine}/players/{room['Ana_id']}").status_code == 403
    assert other_td.get(f"/api/live/sessions/{mine}/results.csv").status_code == 403
    assert tables(room, mine)["Aerodynamics"]["name"] == "Aerodynamics"


def test_removing_a_captain_mid_question_lets_the_other_tables_close_it(
    room: dict[str, Any], db: Session
) -> None:
    code = lobby(room, areas=["rules"])
    advance(room, code)
    assert room["Tere"].delete(f"/api/live/sessions/{code}/players/{room['Leo_id']}").status_code == 204
    t = tables(room, code)
    assert t["Aerodynamics"]["captain_id"] is None and room["Leo_id"] not in t["Aerodynamics"]["member_ids"]
    assert send(room["Leo"], code, {"options": []}) == 403  # gone, and no longer a captain
    qid = state(room["Pau"], code)["question"]["id"]
    assert send(room["Pau"], code, right_answer(db, qid)) == 204
    assert state(room["Ana"], code)["state"] == "closed"  # a table without a captain is not waited for


def test_joined_but_unseated_players_see_the_quiz_and_earn_nothing(
    room: dict[str, Any], db: Session, app_client: Any, new_client: NewClient
) -> None:
    code = lobby(room, areas=["rules"])
    late = new_client()
    r = register(late, invite(app_client), "lia@alu.comillas.edu", "Lia")
    assert r.status_code == 201
    assert late.post(f"/api/live/sessions/{code}/join").status_code == 200
    advance(room, code)
    s = state(late, code)
    assert s["my_table_id"] is None and s["question"] and not any(w in str(s) for w in ANSWER_WORDS)
    assert late.put(f"/api/live/sessions/{code}/proposal", json={"options": []}).status_code == 409
    qid = s["question"]["id"]
    send(room["Leo"], code, right_answer(db, qid))
    send(room["Pau"], code, right_answer(db, qid))
    users = set(db.scalars(select(Attempt.user_id).where(Attempt.mode == "live")))
    assert r.json()["id"] not in users and len(users) == 4


def test_answers_must_be_options_of_the_question_on_screen(
    room: dict[str, Any], db: Session, bank: dict[int, int]
) -> None:
    code = lobby(room, areas=["rules"])
    advance(room, code)
    qid = state(room["Leo"], code)["question"]["id"]
    foreign = next(q for q in bank.values() if q != qid)
    from tests.api.helpers import options

    stray = options(db, foreign)
    if stray:
        assert send(room["Leo"], code, {"options": stray[:1]}) == 400
        assert room["Ana"].put(
            f"/api/live/sessions/{code}/proposal", json={"options": stray[:1]}
        ).status_code in (204, 400)
    assert state(room["Ana"], code)["tables"][0]["answered"] is False  # nothing was recorded


def test_a_rehearsal_with_speed_points_hides_points_and_tallies_until_the_end(
    room: dict[str, Any], db: Session
) -> None:
    code = lobby(room, areas=["rules"], count=2, feedback="end", speed_points=True)
    advance(room, code)
    qid = state(room["Leo"], code)["question"]["id"]
    send(room["Leo"], code, right_answer(db, qid))
    send(room["Pau"], code, wrong(db, qid))
    for who in ("Ana", "Marta", "Tere"):
        s = state(room[who], code)
        assert s["state"] == "closed"
        assert [(t["right"], t["points"]) for t in s["tables"]] == [(0, 0), (0, 0)], (
            who
        )  # points > 0 would say "right"
        assert s["reveals"] == [] and s["room_right"] is None and not any(w in str(s) for w in ANSWER_WORDS)
    assert room["Tere"].post(f"/api/live/sessions/{code}/end").status_code == 204
    done = {t["name"]: (t["right"], t["points"] > 0) for t in state(room["Ana"], code)["tables"]}
    assert done == {"Aerodynamics": (1, True), "Batteries": (0, False)}


def test_a_session_ended_in_the_lobby_still_shows_and_exports(room: dict[str, Any]) -> None:
    code = lobby(room)
    assert room["Tere"].post(f"/api/live/sessions/{code}/end").status_code == 204
    s = state(room["Ana"], code)
    assert (s["state"], s["total"], s["room_asked"], s["reveals"]) == ("finished", 0, 0, [])
    rows = list(csv.reader(io.StringIO(room["Tere"].get(f"/api/live/sessions/{code}/results.csv").text)))
    assert len(rows) == 1  # the header only
    for path in ("advance", "tables/auto", "end"):
        assert room["Tere"].post(f"/api/live/sessions/{code}/{path}").status_code == 409


def test_the_events_stream_needs_the_same_access_as_the_state(room: dict[str, Any]) -> None:
    code = create(room["Tere"])
    assert room["Ana"].get(f"/api/live/sessions/{code}/events").status_code == 403  # not joined


def test_seating_is_for_the_lobby_only(room: dict[str, Any]) -> None:
    code = lobby(room, areas=["rules"])
    advance(room, code)
    assert room["Tere"].post(f"/api/live/sessions/{code}/tables/auto").status_code == 409
    assert room["Tere"].put(f"/api/live/sessions/{code}/tables", json={"tables": []}).status_code == 409
    assert len(tables(room, code)) == 2


# BUG: moving a player to another table mid-question scores them twice for the same question.
def test_a_player_moved_mid_question_is_scored_once(room: dict[str, Any], db: Session) -> None:
    code = lobby(room, areas=["rules"])
    advance(room, code)
    qid = state(room["Leo"], code)["question"]["id"]
    assert send(room["Leo"], code, right_answer(db, qid)) == 204  # Aero answers: Ana scores
    bat = tables(room, code)["Batteries"]["id"]
    assert (
        room["Tere"]
        .put(f"/api/live/sessions/{code}/players/{room['Ana_id']}", json={"table_id": bat})
        .status_code
        == 204
    )
    assert (
        send(room["Pau"], code, right_answer(db, qid)) == 204
    )  # Batteries answers with Ana now seated there
    ana = db.scalars(select(Attempt).where(Attempt.mode == "live", Attempt.user_id == room["Ana_id"])).all()
    assert len(ana) == 1, [(a.xp, a.correct) for a in ana]


# BUG: while a live question is open, any player can read its answer through practice mode.
def test_the_open_live_question_is_not_answered_by_practice_mode(room: dict[str, Any]) -> None:
    code = lobby(room, areas=["rules"])
    advance(room, code)
    qid = state(room["Ana"], code)["question"]["id"]
    r = room["Ana"].post(f"/api/practice/questions/{qid}/answer", json={"unsure": True})
    assert r.status_code == 409 or not (r.json().get("official") or r.json().get("correct_options")), r.json()


# From the backend and security reviews


def test_time_running_out_shows_its_reveal_and_never_closes_the_next_question(
    room: dict[str, Any], clock: Clock
) -> None:
    code = lobby(room, areas=["rules", "mech"], seconds=30)
    advance(room, code)
    clock.advance(seconds=34)  # nobody noticed the deadline yet
    advance(room, code)  # so this press closes the question (and its reveal shows) instead of skipping it
    s = state(room["Ana"], code)
    assert (s["state"], s["position"], len(s["reveals"])) == ("closed", 0, 1)
    advance(room, code)
    assert (state(room["Ana"], code)["state"], state(room["Ana"], code)["position"]) == ("open", 1)


def test_a_double_tap_on_advance_does_not_skip_a_step(room: dict[str, Any]) -> None:
    code = lobby(room, areas=["rules"])
    seen = {"state": "lobby", "position": -1}
    assert room["Tere"].post(f"/api/live/sessions/{code}/advance", json=seen).status_code == 204
    assert room["Tere"].post(f"/api/live/sessions/{code}/advance", json=seen).status_code == 409
    assert state(room["Ana"], code)["state"] == "open"


def test_a_removed_player_cannot_join_again(room: dict[str, Any]) -> None:
    code = lobby(room)
    assert room["Tere"].delete(f"/api/live/sessions/{code}/players/{room['Ana_id']}").status_code == 204
    assert room["Ana"].post(f"/api/live/sessions/{code}/join").status_code == 403
    assert room["Ana_id"] not in [p["user_id"] for p in state(room["Tere"], code)["players"]]


def test_a_reviewer_at_a_table_cannot_read_the_open_question_in_the_review_tools(
    room: dict[str, Any], db: Session
) -> None:
    db.execute(update(User).where(User.id == room["Ana_id"]).values(role="reviewer"))
    db.commit()
    code = lobby(room, areas=["rules"])
    advance(room, code)
    qid = state(room["Ana"], code)["question"]["id"]
    r = room["Ana"].get(f"/api/review/questions/{qid}").json()
    assert r["answer_hidden"] is True and not r["official"]


def test_a_rehearsal_holds_back_xp_until_the_end(room: dict[str, Any], db: Session) -> None:
    code = lobby(room, areas=["rules"], count=1, feedback="end")
    advance(room, code)
    qid = state(room["Leo"], code)["question"]["id"]
    send(room["Leo"], code, right_answer(db, qid))
    assert db.scalars(select(Attempt).where(Attempt.mode == "live")).all() == []  # XP would give it away
    advance(room, code)  # close
    advance(room, code)  # finish: now everyone at the table shares it
    rows = db.scalars(select(Attempt).where(Attempt.mode == "live")).all()
    assert sorted(a.user_id for a in rows) == sorted([room["Ana_id"], room["Leo_id"]]) and all(
        a.xp > 0 for a in rows
    )


def test_one_catch_all_table_at_most_and_auto_seating_picks_everyone_else(
    room: dict[str, Any], app_client: TestClient, new_client: NewClient
) -> None:
    code = lobby(room)
    url = f"/api/live/sessions/{code}/tables"
    two = [
        {"name": "A", "member_ids": [room["Ana_id"]], "catch_all": True},
        {"name": "B", "member_ids": [room["Leo_id"]], "catch_all": True},
    ]
    assert room["Tere"].put(url, json={"tables": two}).status_code == 400
    loner = new_client()
    assert register(loner, invite(app_client), "sol@alu.comillas.edu", "Sol").status_code == 201
    loner.post(f"/api/live/sessions/{code}/join")
    room["Tere"].post(f"{url}/auto")
    assert {t["name"]: t["catch_all"] for t in state(room["Tere"], code)["tables"]}["Everyone else"] is True
