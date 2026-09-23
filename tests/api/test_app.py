from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ifs_tests.api.app import create_app
from ifs_tests.settings import Settings


def client(tmp_path: Path, env: str = "test", dist: Path | None = None) -> TestClient:
    return TestClient(create_app(Settings(env=env, web_dist=dist or tmp_path / "none")))


def test_healthz_and_security_headers(tmp_path: Path) -> None:
    r = client(tmp_path).get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_unknown_api_route_is_404_not_spa(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>")
    assert client(tmp_path, dist=dist).get("/api/nope").status_code == 404


def test_spa_fallback_and_asset_caching(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)")
    c = client(tmp_path, dist=dist)
    page = c.get("/practice/mech")
    assert page.status_code == 200 and "spa" in page.text
    assert page.headers["cache-control"] == "no-cache"
    asset = c.get("/assets/app-abc123.js")
    assert "immutable" in asset.headers["cache-control"]
    assert c.get("/../pyproject.toml").text != Path("pyproject.toml").read_text()


def test_docs_hidden_when_deployed(tmp_path: Path) -> None:
    assert client(tmp_path, env="test").get("/api/openapi.json").status_code == 200
    assert client(tmp_path, env="prod").get("/api/openapi.json").status_code == 404


def test_head_requests_work_for_uptime_probes(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>")
    c = client(tmp_path, dist=dist)
    assert c.head("/healthz").status_code == 200
    assert c.head("/").status_code == 200
