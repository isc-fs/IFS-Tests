from __future__ import annotations

import json
import threading
import time
import tracemalloc
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, inspect, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from ifs_tests.db.models import Attempt, AuditLog, Base, Invite, LiveAnswer, LiveSession, StreakFreeze, User
from ifs_tests.db.models import Session as LoginSession
from ifs_tests.services import maintenance, privacy
from ifs_tests.services.accounts import AccountError

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
    stored = db.scalars(select(Attempt).join(User).where(User.display_name == "Marta")).one()
    assert [(a["xp"], a["lp"]) for a in data["answers"]] == [(stored.xp, stored.lp)] and stored.xp > 0
    assert (data["account"]["xp"], data["account"]["rank_points"]) == (stored.xp, 50 + stored.lp)
    assert data["reports"][0]["message"] == "Option B looks wrong"
    assert data["sign_ins"] and [h["action"] for h in data["account_history"]] == ["user.register"]
    text = str(data)
    assert "leo@" not in text and "argon2" not in text and "hash" not in text


# Where each users column appears in the export's "account", or why it doesn't.
ACCOUNT = {
    "email": "email",
    "display_name": "display_name",
    "vertical": "vertical",
    "subdepartments": "subdepartments",
    "position": "position",
    "role": "role",
    "status": "status",
    "xp": "xp",
    "legacy_xp": "xp_before_ranked",
    "rank_points": "rank_points",
    "rank_season": "rank_season",
    "rank_best": "best_division",
    "combo": "right_in_a_row",
    "miss_streak": "wrong_in_a_row",
    "rested_xp": "rested_xp",
    "rested_on": "rested_on",
    "streak_freezes": "streak_freezes",
    "freeze_earned_on": "streak_freeze_earned_on",
    "leaderboard_opt_out": "hidden_from_leaderboard",
    "created_at": "joined_at",
    "last_seen": "last_seen",
    "failed_logins": "failed_sign_ins",
    "locked_until": "locked_until",
    "left_at": "inactive_since",
}
ACCOUNT_NOT_EXPORTED = {
    "id": "the database's key, meaningless outside it",
    "password_hash": "a secret, and says nothing about the person",
}
# Each column that points at a user: where the export holds those rows, or why it doesn't.
POINTING = {
    ("attempts", "user_id"): "answers",
    ("practice_hints", "user_id"): "pending_hints",
    ("mock_sessions", "user_id"): "mock_runs",
    ("live_players", "user_id"): "live.joined",
    ("live_tables", "captain_id"): "live.joined",
    ("live_sessions", "host_id"): "live.hosted",
    ("live_answers", "by_user_id"): "live.answers_sent_as_captain",
    ("live_proposals", "user_id"): "live.proposals",
    ("reports", "user_id"): "reports",
    ("invites", "used_by"): "invite",
    ("streak_freezes", "user_id"): "streak_freezes_used",
    ("password_resets", "user_id"): "password_resets",
    ("sessions", "user_id"): "sign_ins",
}
POINTING_NOT_EXPORTED = {
    ("invites", "created_by"): "an admin's work on someone else's account: in actions",
    ("password_resets", "created_by"): "an admin's work on someone else's account: in actions",
    ("reports", "resolved_by"): "a reviewer's work on someone else's report: in actions",
}


def test_every_personal_column_is_exported_or_deliberately_left_out(
    app_client: TestClient, admin: User, new_client: NewClient
) -> None:
    """A new users column or table pointing at a user fails here until it is exported (ADR 0006) or
    listed above with a reason."""
    columns = {a.key for a in inspect(User).column_attrs}
    assert columns == ACCOUNT.keys() | ACCOUNT_NOT_EXPORTED.keys()
    pointing = {
        (t.name, c.name)
        for t in Base.metadata.tables.values()
        for c in t.columns
        if any(fk.column.table.name == "users" for fk in c.foreign_keys)
    }
    assert pointing == POINTING.keys() | POINTING_NOT_EXPORTED.keys()

    login(app_client)
    marta = new_client()
    member(app_client, marta, "marta@alu.comillas.edu", "Marta")
    data = export(marta)
    assert set(ACCOUNT.values()) <= data["account"].keys()
    for path in POINTING.values():
        part = data
        for key in path.split("."):
            assert key in part, path
            part = part[key]
    assert "actions" in data


def test_the_export_holds_the_rank_and_account_level_state(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session
) -> None:
    login(app_client)
    marta = new_client()
    uid = member(app_client, marta, "marta@alu.comillas.edu", "Marta")["id"]
    values = {
        "legacy_xp": 1234,
        "rank_season": 2025,
        "rank_best": 5,
        "combo": 4,
        "miss_streak": 2,
        "rested_xp": 300,
        "rested_on": date(2026, 9, 28),
        "streak_freezes": 1,
        "freeze_earned_on": date(2026, 9, 21),
    }
    db.execute(update(User).where(User.id == uid).values(values))
    db.add_all(StreakFreeze(user_id=uid, day=date(2026, 9, d)) for d in (29, 25))
    db.commit()
    app_client.post(f"/api/admin/users/{uid}/reset-link")

    data = export(marta)
    a = data["account"]
    assert (a["xp_before_ranked"], a["rank_season"], a["best_division"]) == (1234, 2025, "Jefe I")
    assert (a["right_in_a_row"], a["wrong_in_a_row"]) == (4, 2)
    assert (a["rested_xp"], a["rested_on"]) == (300, "2026-09-28")
    assert (a["streak_freezes"], a["streak_freeze_earned_on"]) == (1, "2026-09-21")
    assert data["streak_freezes_used"] == ["2026-09-25", "2026-09-29"]
    resets = data["password_resets"]
    assert [(r["created_at"], r["used_at"]) for r in resets] == [("2026-10-01T10:00:00Z", None)]
    assert "hash" not in str(resets)


def test_the_export_keeps_a_mock_run_secret_until_it_ends(player: TestClient, db: Session) -> None:  # noqa: F811
    run = player.post(f"/api/mock/quizzes/{CV}/start").json()
    run = answer(player, run, right_answer(db, run["current"]["question"]["id"]))
    first = export(player)["answers"]
    assert [(a["mode"], a["correct"], a["xp"], a["lp"]) for a in first if a["submitted_at"]] == [
        ("mock", None, 0, 0)
    ]
    while run["current"]:
        run = answer(player, run, right_answer(db, run["current"]["question"]["id"]))
    assert all(a["correct"] and a["xp"] > 0 and a["lp"] > 0 for a in export(player)["answers"])


def test_the_export_keeps_live_results_secret_until_the_session_ends(
    room: dict[str, Any],  # noqa: F811
    db: Session,
) -> None:
    code = lobby(room, areas=["rules"], count=2)
    advance(room, code)
    qid = state(room["Leo"], code)["question"]["id"]
    assert send(room["Leo"], code, right_answer(db, qid)) == 204
    # Still open for the other table: nothing shared yet, and the captain's answer hides its result.
    assert [a for a in export(room["Ana"])["answers"] if a["mode"] == "live"] == []
    assert export(room["Leo"])["live"]["answers_sent_as_captain"][0]["correct"] is None
    assert room["Tere"].post(f"/api/live/sessions/{code}/end").status_code == 204
    after = export(room["Ana"])["answers"]
    assert [(a["correct"], a["xp"] > 0, a["lp"]) for a in after] == [(True, True, 0)]  # live moves no LP
    assert [h["code"] for h in export(room["Tere"])["live"]["hosted"]] == [code]


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
    # The database function measures the keep on its own clock too, so these entries are dated in the past.
    db.execute(update(AuditLog).values(at=clock.now - timedelta(days=700)))
    db.commit()
    before = count(db, AuditLog)
    assert maintenance.run(db, clock.now)["audit_purged"] == 0
    db.execute(update(AuditLog).values(at=clock.now - timedelta(days=1000)))
    db.commit()
    assert maintenance.run(db, clock.now)["audit_purged"] == before


def test_any_latin_name_downloads_its_data(
    app_client: TestClient, admin: User, new_client: NewClient, clock: Clock
) -> None:
    login(app_client)
    c = new_client()
    member(app_client, c, "lukasz@alu.comillas.edu", "Łukasz Dvořák")
    r = c.get("/api/me/export")
    assert r.status_code == 200 and r.json()["account"]["display_name"] == "Łukasz Dvořák"
    assert r.headers["content-disposition"] == 'attachment; filename="mingoquiz-export-2026-10-01.json"'


def test_disabled_accounts_are_deleted_a_year_later_too(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session, clock: Clock
) -> None:
    login(app_client)
    uid = member(app_client, new_client(), "marta@alu.comillas.edu", "Marta")["id"]
    app_client.post("/api/admin/alumni", json={"user_ids": [uid]})
    disabled = app_client.patch(f"/api/admin/users/{uid}", json={"status": "disabled"}).json()
    assert disabled["left_at"] == "2026-10-01T10:00:00Z"  # the year still runs from when she left
    assert maintenance.run(db, clock.now + timedelta(days=366))["alumni_deleted"] == 1


def test_accounts_made_inactive_without_a_date_get_one_at_night(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session, clock: Clock
) -> None:
    login(app_client)
    uid = member(app_client, new_client(), "marta@alu.comillas.edu", "Marta")["id"]
    db.execute(update(User).where(User.id == uid).values(status="alumni", left_at=None))  # an older release
    db.commit()
    maintenance.run(db, clock.now)
    assert maintenance.run(db, clock.now + timedelta(days=364))["alumni_deleted"] == 0
    assert maintenance.run(db, clock.now + timedelta(days=366))["alumni_deleted"] == 1


def test_admins_fetch_the_data_of_someone_who_cannot_sign_in(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session
) -> None:
    login(app_client)
    marta = new_client()
    uid = register(marta, invite(app_client, note="Marta, aero"), "marta@alu.comillas.edu", "Marta").json()[
        "id"
    ]
    app_client.post("/api/admin/alumni", json={"user_ids": [uid]})
    data = app_client.get(f"/api/admin/users/{uid}/export").json()
    assert data["account"]["status"] == "alumni" and data["account"]["deleted_on"]
    assert data["invite"]["note"] == "Marta, aero"
    assert [e["action"] for e in export(app_client)["actions"]][-1] == "user.export"
    assert {e["on"] for e in export(app_client)["actions"]} >= {"invite", "user"}


# Races (found by review): each runs the conflicting work for real against Postgres.


def test_two_admins_marking_each_other_alumni_leave_an_admin(
    db: Session, app_engine: Engine, admin: User, clock: Clock
) -> None:
    b = User(email="b@x.com", password_hash="x", display_name="Bravo", role="admin")
    db.add(b)
    db.commit()
    pairs = [(admin.id, b.id), (b.id, admin.id)]
    barrier = threading.Barrier(2)
    out: list[Any] = [None, None]

    def job(i: int) -> None:
        actor, target = pairs[i]
        with sessionmaker(app_engine, expire_on_commit=False)() as s:
            me = s.get_one(User, actor)
            s.commit()
            barrier.wait()
            try:
                out[i] = privacy.mark_alumni(s, me, [target], clock.now)
            except AccountError as e:
                out[i] = e.status

    threads = [threading.Thread(target=job, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(out) == [1, 403]
    assert db.scalar(select(func.count()).where(User.role == "admin", User.status == "active")) == 1


def test_a_player_deleted_while_their_captain_answers_does_not_block_the_end(
    room: dict[str, Any],  # noqa: F811
    db: Session,
    app_engine: Engine,
    clock: Clock,
) -> None:
    code = lobby(room, areas=["rules"], count=2, feedback="end")
    advance(room, code)
    qid = state(room["Leo"], code)["question"]["id"]
    with sessionmaker(app_engine, expire_on_commit=False)() as d:
        locked = privacy._lock(d, room["Ana_id"])
        assert locked.user is not None
        privacy._delete(d, locked.user, locked.sessions, clock.now)  # not committed yet
        assert send(room["Leo"], code, right_answer(db, qid)) == 204  # still sees Ana at the table
        d.commit()
    assert room["Tere"].post(f"/api/live/sessions/{code}/end").status_code == 204
    assert [a.user_id for a in db.scalars(select(Attempt).where(Attempt.mode == "live"))] == [room["Leo_id"]]


def test_deleting_a_host_waits_for_a_captain_answering_and_screens_see_the_end(
    room: dict[str, Any],  # noqa: F811
    db: Session,
    app_engine: Engine,
    clock: Clock,
) -> None:
    code = lobby(room, areas=["rules"], count=2)
    advance(room, code)
    answering = sessionmaker(app_engine, expire_on_commit=False)()
    s = answering.scalars(select(LiveSession).with_for_update()).one()  # a captain's answer in progress
    before = s.version

    def delete_host() -> None:
        with sessionmaker(app_engine, expire_on_commit=False)() as d:
            locked = privacy._lock(d, room["Tere_id"])
            assert locked.user is not None
            privacy._delete(d, locked.user, locked.sessions, clock.now)
            d.commit()

    thread = threading.Thread(target=delete_host)
    thread.start()
    time.sleep(0.5)
    s.version += 1
    answering.commit()
    answering.close()
    thread.join(timeout=15)
    db.expire_all()
    ended = db.scalars(select(LiveSession)).one()
    assert (ended.state, ended.host_id) == ("finished", None) and ended.version == before + 2


def test_deleting_an_account_locked_meanwhile_is_refused(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session, app_engine: Engine, clock: Clock
) -> None:
    login(app_client)
    uid = member(app_client, new_client(), "marta@alu.comillas.edu", "Marta")["id"]
    with sessionmaker(app_engine, expire_on_commit=False)() as s:
        stale = s.get_one(User, uid)  # loaded before parallel wrong guesses locked the account
        s.commit()
        db.execute(update(User).where(User.id == uid).values(locked_until=clock.now + timedelta(minutes=15)))
        db.commit()
        with pytest.raises(AccountError) as refused:
            privacy.delete_self(s, stale, PASSWORD, clock.now)
    assert refused.value.status == 429
    db.expire_all()
    assert db.get(User, uid) is not None


# Capacity (PERF-04): a download holds one member's whole history in memory.


def long_history(db: Session, user_id: int, times: int) -> int:
    """`times` practice answers to every question of the bank, like several seasons of play."""
    db.execute(
        text("""
        INSERT INTO attempts (user_id, question_id, mode, answer, correct, created_at, area, xp, lp)
        SELECT :uid, q.id, 'practice', '{"options": [], "value": "12.5", "unsure": false}', true,
               now() - interval '1 hour' * g, q.area, 10, 0
        FROM questions q CROSS JOIN generate_series(1, :times) g
        """),
        {"uid": user_id, "times": times},
    )
    db.commit()
    return count(db, Attempt, Attempt.user_id == user_id)


def test_an_export_holds_the_history_once_not_as_database_rows(
    app_client: TestClient,
    admin: User,
    new_client: NewClient,
    db: Session,
    bank: dict[int, int],
    clock: Clock,
) -> None:
    login(app_client)
    marta = new_client()
    uid = member(app_client, marta, "marta@alu.comillas.edu", "Marta")["id"]
    assert long_history(db, uid, 200) > 2000
    user = db.get(User, uid)
    assert user
    privacy.export(db, user, clock.now)  # compiles and caches the statements first
    db.rollback()
    tracemalloc.start()
    try:
        answers = privacy.export(db, user, clock.now)["answers"]
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    size = len(json.dumps(answers, default=str))
    # About three bytes per byte of JSON; loading every attempt with its question took eight.
    assert peak < 4 * size, f"{peak / size:.1f} bytes of memory per byte of JSON"


def test_a_process_prepares_two_exports_at_once_and_turns_more_away(
    app_client: TestClient, admin: User, new_client: NewClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(app_client)
    members = []
    for name in ("Marta", "Leo", "Pau"):
        c = new_client()
        member(app_client, c, f"{name.lower()}@alu.comillas.edu", name)
        members.append(c)
    preparing = threading.Semaphore(0)
    finish = threading.Event()
    real = privacy.export

    def slow(*args: Any) -> dict[str, Any]:
        preparing.release()
        assert finish.wait(10)
        return real(*args)

    monkeypatch.setattr(privacy, "export", slow)
    answers: list[tuple[int, Any]] = []

    def download(c: TestClient) -> None:
        r = c.get("/api/me/export")
        answers.append((r.status_code, r.json().get("detail")))

    threads = [threading.Thread(target=download, args=(c,)) for c in members]
    for t in threads:
        t.start()
    assert preparing.acquire(timeout=10) and preparing.acquire(timeout=10)
    third_started = preparing.acquire(timeout=2)
    finish.set()
    for t in threads:
        t.join(15)
    assert not third_started
    assert sorted(answers, key=lambda a: a[0]) == [
        (200, None),
        (200, None),
        (429, "Another download is being prepared. Try again in a minute."),
    ]
    assert members[2].get("/api/me/export").status_code == 200
