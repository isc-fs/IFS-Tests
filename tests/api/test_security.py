from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from ifs_tests.db.models import User

from .helpers import ADMIN, invite, login, register

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


def test_every_api_route_needs_a_member_and_admin_routes_an_admin(
    app_client: TestClient, admin: User, new_client: NewClient
) -> None:
    paths = app_client.get("/api/openapi.json").json()["paths"]
    routes = [
        (method.upper(), re.sub(r"\{[^}]+\}", "1", path))
        for path, ops in paths.items()
        if path.startswith("/api/")
        for method in ops
    ]
    assert len(routes) >= 10
    for method, path in routes:
        assert app_client.request(method, path, json={}).status_code == 401, (method, path)
    login(app_client)
    m = new_client()
    register(m, invite(app_client), "m@alu.comillas.edu", "Member")
    for method, path in routes:
        if path.startswith("/api/admin/"):
            assert m.request(method, path, json={}).status_code == 403, (method, path)


def test_csrf_guard(app_client: TestClient, admin: User) -> None:
    assert app_client.post("/auth/login", json=ADMIN, headers={"X-CSRF": ""}).status_code == 403
    assert (
        app_client.post("/auth/login", json=ADMIN, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert (
        app_client.post("/auth/login", json=ADMIN, headers={"Origin": "https://testserver"}).status_code
        == 200
    )


def test_no_secret_fields_in_the_api_schema(app_client: TestClient) -> None:
    schema = app_client.get("/api/openapi.json").text
    for secret in ("password_hash", "token_hash", "id_hash", "failed_logins"):
        assert secret not in schema


def test_bad_input_is_a_client_error_never_a_500(app_client: TestClient, admin: User) -> None:
    nul = app_client.post("/auth/login", json={"email": "a\x00b@x.com", "password": "xxxxxxxxxxxx"})
    assert nul.status_code == 422
    login(app_client)
    assert app_client.post("/api/admin/invites", json={"note": "a\x00b"}).status_code == 422
    assert app_client.patch("/api/admin/users/99999999999", json={}).status_code == 422
    assert app_client.post("/api/admin/invites", json={"surprise": 1}).status_code == 422


def test_validation_errors_do_not_echo_passwords(app_client: TestClient) -> None:
    r = app_client.post("/auth/login", json={"email": "x" * 300, "password": "my secret password"})
    assert r.status_code == 422 and "my secret password" not in r.text


def test_unknown_api_paths_are_404_for_every_method(app_client: TestClient) -> None:
    for method, path in [("GET", "/api"), ("HEAD", "/api/me"), ("GET", "/auth/nope"), ("PUT", "/api/me")]:
        assert app_client.request(method, path, headers={"X-CSRF": "1"}).status_code == 404, (method, path)
