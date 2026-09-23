from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from ifs_tests.db.models import User

from .helpers import invite, login, member, register

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


def test_links_use_the_configured_public_origin(app_client: TestClient, admin: User) -> None:
    login(app_client)
    url = app_client.post("/api/admin/invites", json={}).json()["url"]
    assert url.startswith("https://testserver/invite#")


def test_users_list_and_audit_trail(app_client: TestClient, admin: User, new_client: NewClient) -> None:
    login(app_client)
    member(app_client, new_client(), "zoe@alu.comillas.edu", "Zoe")
    member(app_client, new_client(), "alvaro@alu.comillas.edu", "Álvaro")
    m = member(app_client, new_client(), "ana@alu.comillas.edu", "Ana")
    app_client.post(f"/api/admin/users/{m['id']}/reset-link")
    users = app_client.get("/api/admin/users").json()
    assert [u["display_name"] for u in users] == ["Admin", "Álvaro", "Ana", "Zoe"]
    assert all("password_hash" not in u for u in users)
    audit = app_client.get("/api/admin/audit", params={"limit": 3}).json()
    assert [(a["action"], a["actor"], a["target"]) for a in audit] == [
        ("reset.create", "Admin", "Ana"),
        ("user.register", "Ana", "Ana"),
        ("invite.create", "Admin", audit[2]["target"]),
    ]
    for limit in (0, 501):
        assert app_client.get("/api/admin/audit", params={"limit": limit}).status_code == 422


def test_revoke_sessions(app_client: TestClient, admin: User, new_client: NewClient) -> None:
    login(app_client)
    ana = new_client()
    m = member(app_client, ana, "ana@alu.comillas.edu", "Ana")
    assert app_client.post(f"/api/admin/users/{m['id']}/revoke-sessions").status_code == 204
    assert ana.get("/api/me").status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PATCH", "/api/admin/users/999"),
        ("POST", "/api/admin/users/999/reset-link"),
        ("POST", "/api/admin/users/999/revoke-sessions"),
        ("DELETE", "/api/admin/invites/999"),
    ],
)
def test_unknown_ids_are_404(app_client: TestClient, admin: User, method: str, path: str) -> None:
    login(app_client)
    assert app_client.request(method, path, json={}).status_code == 404


def test_self_changes_and_the_last_admin_are_guarded(
    app_client: TestClient, admin: User, new_client: NewClient
) -> None:
    login(app_client)
    assert app_client.patch(f"/api/admin/users/{admin.id}", json={"role": "member"}).status_code == 403
    second = new_client()
    r = register(second, invite(app_client, role="admin"), "second@alu.comillas.edu", "Second")
    second_id = r.json()["id"]
    assert second.patch(f"/api/admin/users/{admin.id}", json={"status": "disabled"}).status_code == 200
    assert app_client.get("/api/me").status_code == 401  # disabled: sessions gone
    assert second.patch(f"/api/admin/users/{second_id}", json={"role": "member"}).status_code == 403


def test_reviewers_cannot_administer(app_client: TestClient, admin: User, new_client: NewClient) -> None:
    login(app_client)
    reviewer = new_client()
    register(reviewer, invite(app_client, role="reviewer"), "rev@alu.comillas.edu", "Rev")
    assert reviewer.get("/api/admin/users").status_code == 403
    assert reviewer.patch("/api/me", json={"role": "admin"}).status_code == 422
