from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ifs_tests.auth.passwords import hash_password
from ifs_tests.auth.sessions import COOKIE
from ifs_tests.db.models import User
from ifs_tests.services.accounts import LOGIN_FAILED

from ..conftest import Clock
from .helpers import ADMIN, PASSWORD, invite, login, member, register

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


def test_login_sets_a_hardened_cookie_and_rotates_it(app_client: TestClient, admin: User) -> None:
    first = app_client.post("/auth/login", json=ADMIN)
    cookie = first.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=") and "Domain" not in cookie
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag in cookie
    old = app_client.cookies[COOKIE]
    login(app_client)
    assert app_client.cookies[COOKIE] != old
    stale = TestClient(app_client.app, base_url="https://testserver", cookies={COOKIE: old})
    assert stale.get("/api/me").status_code == 401


def test_invite_register_and_single_use(app_client: TestClient, admin: User, new_client: NewClient) -> None:
    login(app_client)
    token = invite(app_client, role="member", vertical="Driverless")
    guest = new_client()
    info = guest.post("/auth/invites/lookup", json={"token": token}).json()
    assert info["vertical"] == "Driverless" and info["role"] == "member"
    r = register(guest, token, "Marta@ALU.comillas.edu ", "Marta")
    assert r.status_code == 201
    me = guest.get("/api/me").json()
    assert me["email"] == "marta@alu.comillas.edu" and me["vertical"] == "Driverless"
    assert register(new_client(), token, "other@alu.comillas.edu", "Other").status_code == 404


def test_registration_reports_every_field_problem_at_once(
    app_client: TestClient, admin: User, new_client: NewClient
) -> None:
    login(app_client)
    token = invite(app_client)
    r = register(new_client(), token, "not-an-email", "Admin", "password123")
    assert r.status_code == 400
    assert set(r.json()["fields"]) == {"email", "display_name", "password"}
    assert register(new_client(), token, "ok@alu.comillas.edu", "Fine Name").status_code == 201


def test_member_picks_a_vertical_when_the_invite_has_none(
    app_client: TestClient, admin: User, new_client: NewClient
) -> None:
    login(app_client)
    guest = new_client()
    assert (
        register(guest, invite(app_client), "v@alu.comillas.edu", "Vera", vertical="Electronics").status_code
        == 201
    )
    assert guest.get("/api/me").json()["vertical"] == "Electronics"


def test_duplicate_email_is_a_409_and_keeps_the_invite_usable(
    app_client: TestClient, admin: User, new_client: NewClient
) -> None:
    login(app_client)
    token = invite(app_client)
    r = register(new_client(), token, "ADMIN@alu.comillas.edu", "Someone")
    assert r.status_code == 400 and "already exists" in r.json()["fields"]["email"]
    assert register(new_client(), token, "someone@alu.comillas.edu", "Someone").status_code == 201


@pytest.mark.parametrize("name", ["ADMIN", "admin", "Е2E Аdmin"])
def test_display_names_are_unique_and_look_alikes_are_refused(
    app_client: TestClient, admin: User, new_client: NewClient, name: str
) -> None:
    login(app_client)
    r = register(new_client(), invite(app_client), "n@alu.comillas.edu", name)
    assert r.status_code == 400 and "display_name" in r.json()["fields"]


def test_invites_expire_and_can_be_revoked(app_client: TestClient, admin: User, clock: Clock) -> None:
    login(app_client)
    expiring = invite(app_client)
    clock.advance(minutes=1)
    revoked = invite(app_client)
    newest = app_client.get("/api/admin/invites").json()[0]["id"]
    assert app_client.delete(f"/api/admin/invites/{newest}").status_code == 204
    assert app_client.post("/auth/invites/lookup", json={"token": revoked}).status_code == 404
    assert app_client.delete(f"/api/admin/invites/{newest}").status_code == 404
    clock.advance(days=7)
    assert app_client.post("/auth/invites/lookup", json={"token": expiring}).status_code == 404


def test_lockout_after_five_failures(app_client: TestClient, admin: User, clock: Clock) -> None:
    wrong = {"email": ADMIN["email"], "password": "not the password"}
    for _ in range(4):
        assert app_client.post("/auth/login", json=wrong).json()["detail"] == LOGIN_FAILED
    login(app_client)  # a success resets the counter
    for _ in range(5):
        app_client.post("/auth/login", json=wrong)
    locked = app_client.post("/auth/login", json=ADMIN)
    unknown = app_client.post("/auth/login", json={"email": "nobody@x.com", "password": "whatever123"})
    assert locked.status_code == unknown.status_code == 401 and locked.json() == unknown.json()
    clock.advance(minutes=14, seconds=59)
    assert app_client.post("/auth/login", json=ADMIN).status_code == 401
    clock.advance(seconds=1)
    login(app_client)


@pytest.mark.parametrize("status", ["disabled", "alumni"])
def test_inactive_members_cannot_sign_in(
    app_client: TestClient, admin: User, new_client: NewClient, status: str
) -> None:
    login(app_client)
    m = member(app_client, new_client(), "leo@alu.comillas.edu", "Leo")
    assert app_client.patch(f"/api/admin/users/{m['id']}", json={"status": status}).status_code == 200
    r = new_client().post("/auth/login", json={"email": "leo@alu.comillas.edu", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == LOGIN_FAILED


def test_sessions_are_extended_by_activity_but_capped_at_30_days(
    app_client: TestClient, admin: User, clock: Clock
) -> None:
    login(app_client)
    for _ in range(65):  # 11 h steps: never idle for 12 h, crosses 30 days at step 66
        clock.advance(hours=11)
        assert app_client.get("/api/me").status_code == 200
    clock.advance(hours=11)
    assert app_client.get("/api/me").status_code == 401


def test_sessions_expire_after_12_idle_hours(app_client: TestClient, admin: User, clock: Clock) -> None:
    login(app_client)
    clock.advance(hours=11, minutes=59)
    assert app_client.get("/api/me").status_code == 200
    clock.advance(hours=12)
    assert app_client.get("/api/me").status_code == 401


def test_logout(app_client: TestClient, admin: User) -> None:
    login(app_client)
    assert app_client.post("/auth/logout").status_code == 204
    assert app_client.get("/api/me").status_code == 401


def test_reset_link_flow_closes_all_links_and_sessions(
    app_client: TestClient, admin: User, new_client: NewClient
) -> None:
    login(app_client)
    leo = new_client()
    m = member(app_client, leo, "leo@alu.comillas.edu", "Leo")
    links = [app_client.post(f"/api/admin/users/{m['id']}/reset-link").json()["url"] for _ in range(2)]
    first, second = (url.rsplit("#", 1)[1] for url in links)
    guest = new_client()
    assert guest.post("/auth/resets/lookup", json={"token": first}).status_code == 200
    assert guest.post("/auth/reset", json={"token": first, "password": "short"}).status_code == 400
    assert (
        guest.post("/auth/reset", json={"token": first, "password": "brand new leo pass"}).status_code == 204
    )
    assert leo.get("/api/me").status_code == 401
    assert guest.post("/auth/resets/lookup", json={"token": second}).status_code == 404
    login(guest, "leo@alu.comillas.edu", "brand new leo pass")


def test_change_password(app_client: TestClient, admin: User, new_client: NewClient) -> None:
    other = new_client()
    login(other)
    login(app_client)
    bad = {"current_password": "nope nope nope", "new_password": "another good one!"}
    r = app_client.post("/api/me/password", json=bad)
    assert r.status_code == 403 and "current_password" in r.json()["fields"]
    ok = {"current_password": ADMIN["password"], "new_password": "another good one!"}
    assert app_client.post("/api/me/password", json=ok).status_code == 204
    assert app_client.get("/api/me").status_code == 200
    assert other.get("/api/me").status_code == 401


def test_guessing_the_current_password_locks_the_account(app_client: TestClient, admin: User) -> None:
    login(app_client)
    bad = {"current_password": "nope nope nope", "new_password": "another good one!"}
    for _ in range(5):
        app_client.post("/api/me/password", json=bad)
    ok = {"current_password": ADMIN["password"], "new_password": "another good one!"}
    assert app_client.post("/api/me/password", json=ok).status_code == 429


def test_profile_update_and_clearing_the_vertical(app_client: TestClient, admin: User) -> None:
    login(app_client)
    r = app_client.patch(
        "/api/me", json={"display_name": "  Chief   Admin ", "vertical": "Board", "leaderboard_opt_out": True}
    )
    assert r.json() | {"id": 0} == r.json() | {
        "id": 0,
        "display_name": "Chief Admin",
        "vertical": "Board",
        "leaderboard_opt_out": True,
    }
    assert app_client.patch("/api/me", json={"leaderboard_opt_out": False}).json()["vertical"] == "Board"
    assert app_client.patch("/api/me", json={"vertical": None}).json()["vertical"] is None
    assert app_client.patch("/api/me", json={"vertical": "Aero"}).status_code == 422
    assert app_client.patch("/api/me", json={"display_name": "<script>"}).status_code == 400


def test_outdated_hashes_are_upgraded_at_login(app_client: TestClient, admin: User, db: Session) -> None:
    from argon2 import PasswordHasher

    old = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(ADMIN["password"])
    db.get_one(User, admin.id).password_hash = old
    db.commit()
    login(app_client)
    db.expire_all()
    upgraded = db.get_one(User, admin.id).password_hash
    assert upgraded != old and upgraded.startswith("$argon2id$v=19$m=19456,t=2,p=1")
    assert hash_password("x") != hash_password("x")
