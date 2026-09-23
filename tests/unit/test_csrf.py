from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ifs_tests.api.security import CSRFGuard
from ifs_tests.settings import Settings

ALLOWED = frozenset({"https://quiz.example"})


async def _ok(scope: Any, receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def status(method: str, path: str, headers: dict[str, str]) -> int:
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }
    asyncio.run(CSRFGuard(_ok, ALLOWED)(scope, None, send))  # type: ignore[arg-type]
    return int(sent[0]["status"])


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("path", ["/api/me", "/auth/login"])
def test_writes_need_the_header(method: str, path: str) -> None:
    assert status(method, path, {}) == 403
    assert status(method, path, {"x-csrf": "1"}) == 200


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("https://quiz.example", 200),
        ("https://quiz.example/", 200),
        ("null", 403),
        ("https://quiz.example.evil.com", 403),
        ("http://quiz.example", 403),
    ],
)
def test_origin_must_be_ours(origin: str, expected: int) -> None:
    assert status("POST", "/api/me", {"x-csrf": "1", "origin": origin}) == expected


def test_reads_and_other_paths_pass() -> None:
    assert status("GET", "/api/me", {}) == 200
    assert status("POST", "/healthz", {}) == 200


def test_deployed_origins_exclude_dev_servers() -> None:
    origins = Settings(env="prod", public_origin="https://quiz.iscracingteam.com/").allowed_origins
    assert origins == frozenset({"https://quiz.iscracingteam.com"})


def test_deployed_environments_must_be_served_over_https() -> None:
    with pytest.raises(ValueError, match="https"):
        Settings(env="prod", public_origin="http://quiz.iscracingteam.com")
    assert Settings(env="prod", public_origin="https://quiz.iscracingteam.com").session_cookie == "__Host-sid"
    assert Settings(env="local", public_origin="http://localhost:8000").session_cookie == "sid"
