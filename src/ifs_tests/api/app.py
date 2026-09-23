from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

from .. import __version__
from ..settings import Settings, get_settings
from .security import SecurityHeaders


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs = not settings.is_deployed
    app = FastAPI(
        title="IFS-Tests",
        version=__version__,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    app.add_middleware(SecurityHeaders)

    @app.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
    def healthz() -> dict[str, str]:
        # Process-only on purpose: uptime probes must not wake or load the database.
        return {"status": "ok", "version": __version__}

    @app.api_route(
        "/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False
    )
    def api_not_found(path: str) -> None:
        raise HTTPException(status_code=404)

    _mount_spa(app, settings.web_dist)
    return app


def _mount_spa(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if not index.is_file():
        return

    if (dist / "assets").is_dir():
        app.mount("/assets", ImmutableStatic(directory=dist / "assets"), name="assets")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str) -> FileResponse:
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist.resolve()):
            return FileResponse(file)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


class ImmutableStatic(StaticFiles):
    """Vite emits content-hashed file names under /assets, so they can be cached forever."""

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


app = create_app()
