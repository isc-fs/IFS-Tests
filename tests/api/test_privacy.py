from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ifs_tests.db.models import Attempt, AuditLog, Invite, LiveAnswer, LiveSession, User
from ifs_tests.db.models import Session as LoginSession
from ifs_tests.services import maintenance

from ..conftest import Clock
from .helpers import ADMIN, PASSWORD, invite, login, member, register, right_answer
from .test_live import advance, lobby, room, send, state  # noqa: F401
from .test_mock import CV, answer, player  # noqa: F401

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


def practise(c: TestClient, db: Session) -> int:
    q = c.get("/api/practice/next").json()
    while not q["graded"]:
        q = c.get("/api/practice/next", params={"skip": q["id"]}).json()
    qid = int(q["id"])
    assert c.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid)).status_code == 200
    return qid


def export(c: TestClient) -> dict[str, Any]:
    r = c.get("/api/me/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].startswith('attachment; filename="mingoquiz-')
    return dict(r.json())


def count(db: Session, model: Any, *where: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def test_the_export_holds_my_data_and_nobody_elses(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    login(app_client)
    marta, leo = new_client(), new_client()
    member(app_client, marta, "marta@alu.comillas.edu", "Marta")
    member(app_client, leo, "leo@alu.comillas.edu", "Leo")
    mine = practise(marta, db)
    practise(leo, db)
    report = marta.post(f"/api/questions/{mine}/report", json={"message": "Option B looks wrong"})
    assert report.status_code == 204

    data = export(marta)
    assert data["account"]["email"] == "marta@alu.comillas.edu"
    assert [(a["question_id"], a["mode"], a["correct"]) for a in data["answers"]] == [
        (mine, "practice", True)
    ]
    assert data["reports"][0]["message"] == "Option B looks wrong"
    assert data["sign_ins"] and [h["action"] for h in data["account_history"]] == ["user.register"]
    text = str(data)
    assert "leo@" not in text and "argon2" not in text and "hash" not in text


def test_the_export_keeps_a_mock_run_secret_until_it_ends(player: TestClient, db: Session) -> None:  # noqa: F811
    run = player.post(f"/api/mock/quizzes/{CV}/start").json()
    run = answer(player, run, right_answer(db, run["current"]["question"]["id"]))
    first = export(player)["answers"]
    assert [(a["mode"], a["correct"], a["xp"]) for a in first if a["submitted_at"]] == [("mock", None, 0)]
    while run["current"]:
        run = answer(player, run, right_answer(db, run["current"]["question"]["id"]))
    assert all(a["correct"] and a["xp"] > 0 for a in export(player)["answers"])


def test_the_export_keeps_live_results_secret_until_the_session_ends(
    room: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    code = lobby(room, areas=["rules"], count=2)
    advance(room, code)
    qid = state(room["Leo"], code)["question"]["id"]
    assert send(room["Leo"], code, right_answer(db, qid)) == 204
    live = [a for a in export(room["Ana"])["answers"] if a["mode"] == "live"]
    assert [(a["correct"], a["xp"]) for a in live] == [(None, 0)]
    assert export(room["Leo"])["live"]["answers_sent_as_captain"][0]["correct"] is None
    assert room["Tere"].post(f"/api/live/sessions/{code}/end").status_code == 204
    assert [a["correct"] for a in export(room["Ana"])["answers"]] == [True]
    assert export(room["Tere"])["live"]["hosted"] == [code]


def test_deleting_my_account_takes_my_password_and_removes_everything(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    login(app_client)
    marta = new_client()
    token = invite(app_client, note="Marta Ruiz, aero")
    uid = register(marta, token, "marta@alu.comillas.edu", "Marta").json()["id"]
    practise(marta, db)
    wrong = marta.post("/api/me/delete", json={"password": "not my password at all"})
    assert wrong.status_code == 403 and wrong.json()["fields"] == {"password": "Your password is wrong."}
    r = marta.post("/api/me/delete", json={"password": PASSWORD})
    assert r.status_code == 204 and "Max-Age=0" in r.headers["set-cookie"]

    assert marta.get("/api/me").status_code == 401
    assert (
        marta.post("/auth/login", json={"email": "marta@alu.comillas.edu", "password": PASSWORD}).status_code
        == 401
    )
    db.expire_all()
    assert db.get(User, uid) is None
    for model in (Attempt, LoginSession):
        assert count(db, model, model.user_id == uid) == 0
    assert db.scalar(select(Invite.note).where(Invite.used_by.is_(None))) is None  # the invite named her
    notes = [e.details for e in db.scalars(select(AuditLog).where(AuditLog.action == "invite.create"))]
    assert notes and all("note" not in d for d in notes)
    deleted = db.scalars(select(AuditLog).where(AuditLog.action == "user.delete")).one()
    assert (deleted.target, deleted.details) == (f"user:{uid}", {"by": "self"})
    log = app_client.get("/api/admin/audit").json()
    assert {e["target"] for e in log if e["action"] == "user.delete"} == {"a deleted account"}


def test_the_only_admin_cannot_delete_their_account(signed_in: TestClient, db: Session) -> None:
    r = signed_in.post("/api/me/delete", json={"password": ADMIN["password"]})
    assert r.status_code == 409 and "only admin" in r.json()["detail"]
    assert signed_in.get("/api/me").status_code == 200


def test_wrong_passwords_to_delete_count_towards_the_lock(
    app_client: TestClient, admin: User, new_client: NewClient
) -> None:
    login(app_client)
    marta = new_client()
    member(app_client, marta, "marta@alu.comillas.edu", "Marta")
    codes = [
        marta.post("/api/me/delete", json={"password": f"guess number {i}"}).status_code for i in range(6)
    ]
    assert codes == [403] * 5 + [429]
    assert marta.post("/api/me/delete", json={"password": PASSWORD}).status_code == 429


def test_a_host_leaving_ends_their_sessions_and_the_players_keep_their_results(
    room: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    code = lobby(room, areas=["rules"], count=2, feedback="end")
    advance(room, code)
    qid = state(room["Leo"], code)["question"]["id"]
    send(room["Leo"], code, right_answer(db, qid))
    # Ana leaves mid-rehearsal: her share goes with her, the rest of the table's waits for the end.
    assert room["Ana"].post("/api/me/delete", json={"password": PASSWORD}).status_code == 204
    assert db.scalar(select(LiveAnswer.member_ids)) == [room["Leo_id"]]
    assert room["Tere"].post("/api/me/delete", json={"password": PASSWORD}).status_code == 204
    s = state(room["Leo"], code)
    assert (s["state"], s["host_name"]) == ("finished", "a former member")
    assert db.scalar(select(LiveSession.host_id)) is None
    assert [a.user_id for a in db.scalars(select(Attempt).where(Attempt.mode == "live"))] == [room["Leo_id"]]


def test_admins_delete_other_accounts_never_their_own(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session
) -> None:
    login(app_client)
    marta = new_client()
    uid = member(app_client, marta, "marta@alu.comillas.edu", "Marta")["id"]
    assert app_client.delete(f"/api/admin/users/{admin.id}").status_code == 403
    assert app_client.delete(f"/api/admin/users/{uid}").status_code == 204
    assert app_client.delete(f"/api/admin/users/{uid}").status_code == 404
    assert marta.get("/api/me").status_code == 401
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "user.delete")).one()
    assert (entry.actor_id, entry.details) == (admin.id, {"by": "admin"})


def test_alumni_are_deleted_a_year_after_they_leave(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session, clock: Clock
) -> None:
    login(app_client)
    people = {name: new_client() for name in ("Marta", "Leo", "Pau")}
    ids = {n: member(app_client, c, f"{n.lower()}@alu.comillas.edu", n)["id"] for n, c in people.items()}
    r = app_client.post("/api/admin/alumni", json={"user_ids": [ids["Marta"], ids["Leo"], admin.id]})
    assert r.json() == {"marked": 2}  # never the admin doing it
    assert people["Marta"].get("/api/me").status_code == 401  # signed out
    users = {u["display_name"]: u for u in app_client.get("/api/admin/users").json()}
    assert users["Marta"]["status"] == "alumni" and users["Marta"]["left_at"]
    back = app_client.patch(f"/api/admin/users/{ids['Leo']}", json={"status": "active"}).json()
    assert back["left_at"] is None  # Leo came back: no deletion pending

    assert maintenance.run(db, clock.now + timedelta(days=364))["alumni_deleted"] == 0
    assert maintenance.run(db, clock.now + timedelta(days=366))["alumni_deleted"] == 1
    db.expire_all()
    left = set(db.scalars(select(User.display_name)))
    assert "Marta" not in left and {"Leo", "Pau"} <= left
    assert db.scalars(select(AuditLog.details).where(AuditLog.action == "user.delete")).one() == {
        "by": "retention"
    }


def test_the_audit_log_keeps_two_years(signed_in: TestClient, db: Session, clock: Clock) -> None:
    db.execute(update(AuditLog).values(at=clock.now))
    db.commit()
    before = count(db, AuditLog)
    assert maintenance.run(db, clock.now + timedelta(days=729))["audit_purged"] == 0
    assert maintenance.run(db, clock.now + timedelta(days=740))["audit_purged"] == before
