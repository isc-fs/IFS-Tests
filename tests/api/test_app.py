from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ifs_tests.api.app import create_app
from ifs_tests.settings import Settings


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    (tmp_path / "dist" / "assets").mkdir(parents=True)
    (tmp_path / "dist" / "index.html").write_text("<html>spa</html>")
    (tmp_path / "dist" / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("top secret")
    return tmp_path / "dist"


def client(dist: Path, env: str = "test") -> TestClient:
    return TestClient(create_app(Settings(env=env, web_dist=dist)))


def test_healthz_and_security_headers(dist: Path) -> None:
    r = client(dist).get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client(dist).head("/healthz").status_code == 200


def test_spa_fallback_and_asset_caching(dist: Path) -> None:
    c = client(dist)
    page = c.get("/practice/mech")
    assert "spa" in page.text and page.headers["cache-control"] == "no-cache"
    assert "immutable" in c.get("/assets/app-abc123.js").headers["cache-control"]
    assert c.head("/").status_code == 200


@pytest.mark.parametrize(
    "path", ["/%2e%2e/secret.txt", "/..%2fsecret.txt", "/%00", "/" + "a" * 300, "/a/" * 100]
)
def test_spa_never_serves_outside_dist_or_crashes(dist: Path, path: str) -> None:
    r = client(dist).get(path)
    assert r.status_code == 200 and "top secret" not in r.text


def test_docs_hidden_when_deployed(dist: Path) -> None:
    assert client(dist, "test").get("/api/openapi.json").status_code == 200
    assert client(dist, "prod").get("/api/openapi.json").status_code == 404


def test_app_without_a_build_still_serves_the_api(tmp_path: Path) -> None:
    c = client(tmp_path / "missing")
    assert c.get("/healthz").status_code == 200 and c.get("/").status_code == 404
