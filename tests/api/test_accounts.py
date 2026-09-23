from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from ifs_tests.auth.sessions import COOKIE
from ifs_tests.db.models import AuditLog, User
from ifs_tests.services.accounts import create_first_admin

from ..conftest import Clock

pytestmark = pytest.mark.integration

ADMIN = {"email": "admin@alu.comillas.edu", "password": "pit lane boss 2026"}
GOOD_PASSWORD = "tractive system 900V!"


@pytest.fixture
def admin(db: Session, clock: Clock) -> User:
    return create_first_admin(db, ADMIN["email"], "Admin", ADMIN["password"], clock.now)


def login(c: TestClient, email: str, password: str) -> None:
    r = c.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text


def invite(c: TestClient, **body: object) -> str:
    r = c.post("/api/admin/invites", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["url"]).rsplit("/", 1)[1]


def register(c: TestClient, token: str, email: str, name: str, password: str = GOOD_PASSWORD) -> int:
    r = c.post(
        "/auth/register", json={"token": token, "email": email, "display_name": name, "password": password}
    )
    return int(r.status_code)


def test_login_sets_a_hardened_session_cookie(app_client: TestClient, admin: User) -> None:
    r = app_client.post("/auth/login", json=ADMIN)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag in cookie
    assert "Domain" not in cookie
    assert "password" not in r.text


def test_invite_register_and_single_use(app_client: TestClient, admin: User) -> None:
    login(app_client, **ADMIN)
    token = invite(app_client, role="member", vertical="Driverless")
    app_client.post("/auth/logout")

    assert app_client.get(f"/auth/invites/{token}").json()["vertical"] == "Driverless"
    assert register(app_client, token, "marta@alu.comillas.edu", "Marta", "short") == 400
    assert register(app_client, token, "marta@alu.comillas.edu", "Marta", "password123") == 400
    assert register(app_client, token, "Marta@ALU.comillas.edu ", "Marta") == 201

    me = app_client.get("/api/me").json()
    assert (
        me["email"] == "marta@alu.comillas.edu" and me["role"] == "member" and me["vertical"] == "Driverless"
    )
    assert register(app_client, token, "other@alu.comillas.edu", "Other") == 404


def test_invites_expire_and_can_be_revoked(app_client: TestClient, admin: User, clock: Clock) -> None:
    login(app_client, **ADMIN)
    expiring = invite(app_client)
    clock.advance(minutes=1)
    revoked = invite(app_client)
    invite_id = app_client.get("/api/admin/invites").json()[0]["id"]
    assert app_client.delete(f"/api/admin/invites/{invite_id}").status_code == 204
    assert app_client.get(f"/auth/invites/{revoked}").status_code == 404
    clock.advance(days=8)
    assert app_client.get(f"/auth/invites/{expiring}").status_code == 404


def test_display_names_are_unique_ignoring_case(app_client: TestClient, admin: User) -> None:
    login(app_client, **ADMIN)
    token = invite(app_client)
    assert register(app_client, token, "a@alu.comillas.edu", "ADMIN") == 409


def test_wrong_passwords_lock_the_account(app_client: TestClient, admin: User, clock: Clock) -> None:
    wrong = {"email": ADMIN["email"], "password": "not the password"}
    unknown = app_client.post("/auth/login", json={"email": "nobody@x.com", "password": "whatever123"})
    for _ in range(5):
        r = app_client.post("/auth/login", json=wrong)
        assert r.status_code == 401 and r.json() == unknown.json()
    assert app_client.post("/auth/login", json=ADMIN).status_code == 401
    clock.advance(minutes=16)
    assert app_client.post("/auth/login", json=ADMIN).status_code == 200


def test_csrf_guard(app_client: TestClient, admin: User) -> None:
    no_header = app_client.post("/auth/login", json=ADMIN, headers={"X-CSRF": ""})
    foreign = app_client.post("/auth/login", json=ADMIN, headers={"Origin": "https://evil.example"})
    same = app_client.post("/auth/login", json=ADMIN, headers={"Origin": "https://testserver"})
    assert (no_header.status_code, foreign.status_code, same.status_code) == (403, 403, 200)


def test_sessions_expire_when_idle_and_absolutely(app_client: TestClient, admin: User, clock: Clock) -> None:
    login(app_client, **ADMIN)
    clock.advance(hours=11)
    assert app_client.get("/api/me").status_code == 200
    clock.advance(hours=13)
    assert app_client.get("/api/me").status_code == 401

    login(app_client, **ADMIN)
    for _ in range(3):
        clock.advance(days=9, hours=23)
        clock.advance(hours=1)
        app_client.get("/api/me")
        clock.advance(hours=-1)
    clock.advance(days=1)
    assert app_client.get("/api/me").status_code == 401


def test_logout(app_client: TestClient, admin: User) -> None:
    login(app_client, **ADMIN)
    assert app_client.post("/auth/logout").status_code == 204
    assert app_client.get("/api/me").status_code == 401


def test_admin_reset_link(app_client: TestClient, admin: User, db: Session) -> None:
    login(app_client, **ADMIN)
    token = invite(app_client)
    register(app_client, token, "leo@alu.comillas.edu", "Leo")
    leo = TestClient(app_client.app, base_url="https://testserver", headers={"X-CSRF": "1"})
    login(leo, "leo@alu.comillas.edu", GOOD_PASSWORD)

    login(app_client, **ADMIN)
    leo_id = db.scalar(select(User.id).where(User.email == "leo@alu.comillas.edu"))
    reset = app_client.post(f"/api/admin/users/{leo_id}/reset-link").json()["url"].rsplit("/", 1)[1]
    app_client.post("/auth/logout")

    assert app_client.get(f"/auth/resets/{reset}").status_code == 200
    assert app_client.post("/auth/reset", json={"token": reset, "password": "short"}).status_code == 400
    assert (
        app_client.post("/auth/reset", json={"token": reset, "password": "brand new leo pass"}).status_code
        == 204
    )
    assert leo.get("/api/me").status_code == 401  # old sessions revoked
    login(app_client, "leo@alu.comillas.edu", "brand new leo pass")
    assert (
        app_client.post("/auth/reset", json={"token": reset, "password": "again new pass!"}).status_code
        == 404
    )


def test_change_password_keeps_only_this_session(app_client: TestClient, admin: User) -> None:
    other = TestClient(app_client.app, base_url="https://testserver", headers={"X-CSRF": "1"})
    login(other, **ADMIN)
    login(app_client, **ADMIN)
    bad = {"current_password": "nope nope nope", "new_password": "another good one!"}
    assert app_client.post("/api/me/password", json=bad).status_code == 403
    ok = {"current_password": ADMIN["password"], "new_password": "another good one!"}
    assert app_client.post("/api/me/password", json=ok).status_code == 204
    assert app_client.get("/api/me").status_code == 200
    assert other.get("/api/me").status_code == 401


def test_profile_update(app_client: TestClient, admin: User) -> None:
    login(app_client, **ADMIN)
    r = app_client.patch("/api/me", json={"display_name": "  Chief   Admin ", "leaderboard_opt_out": True})
    assert r.json()["display_name"] == "Chief Admin" and r.json()["leaderboard_opt_out"] is True
    assert app_client.patch("/api/me", json={"vertical": "Aero"}).status_code == 422
    assert app_client.patch("/api/me", json={"display_name": "<script>"}).status_code == 400


def test_last_admin_and_self_changes_are_guarded(app_client: TestClient, admin: User, db: Session) -> None:
    login(app_client, **ADMIN)
    assert app_client.patch(f"/api/admin/users/{admin.id}", json={"role": "member"}).status_code == 403

    token = invite(app_client, role="admin")
    other = TestClient(app_client.app, base_url="https://testserver", headers={"X-CSRF": "1"})
    assert register(other, token, "second@alu.comillas.edu", "Second") == 201
    second = db.scalar(select(User.id).where(User.email == "second@alu.comillas.edu"))
    assert other.patch(f"/api/admin/users/{admin.id}", json={"status": "disabled"}).status_code == 200
    assert app_client.get("/api/me").status_code == 401  # disabled: sessions gone
    assert other.patch(f"/api/admin/users/{second}", json={"role": "member"}).status_code == 403


def test_privileged_actions_are_audited(app_client: TestClient, admin: User, db: Session) -> None:
    login(app_client, **ADMIN)
    token = invite(app_client)
    register(app_client, token, "ana@alu.comillas.edu", "Ana")
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"user.bootstrap_admin", "invite.create", "user.register"} <= actions


def test_every_api_route_requires_a_member_and_admin_routes_an_admin(
    app_client: TestClient, admin: User
) -> None:
    paths = app_client.get("/api/openapi.json").json()["paths"]
    routes = [
        (method.upper(), path.replace("{user_id}", "1").replace("{invite_id}", "1"))
        for path, ops in paths.items()
        if path.startswith("/api/")
        for method in ops
    ]
    assert len(routes) >= 10
    for method, path in routes:
        assert app_client.request(method, path, json={}).status_code == 401, (method, path)

    login(app_client, **ADMIN)
    token = invite(app_client)
    member = TestClient(app_client.app, base_url="https://testserver", headers={"X-CSRF": "1"})
    register(member, token, "m@alu.comillas.edu", "Member")
    for method, path in routes:
        if path.startswith("/api/admin/"):
            assert member.request(method, path, json={}).status_code == 403, (method, path)


def test_no_secret_fields_in_the_api_schema(app_client: TestClient) -> None:
    schema = app_client.get("/api/openapi.json").text
    for secret in ("password_hash", "token_hash", "id_hash", "failed_logins"):
        assert secret not in schema
