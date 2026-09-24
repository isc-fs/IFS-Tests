from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from .. import __version__
from ..auth.passwords import HashingBusy
from ..services.errors import UserError
from ..settings import Settings, get_settings
from .routes import admin, auth, daily, leaderboard, learning, me, mock, practice, review
from .security import CSRFGuard, SecurityHeaders


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs = not settings.is_deployed
    app = FastAPI(
        title="MingoQuiz",
        version=__version__,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.settings = settings
    app.add_middleware(CSRFGuard, allowed_origins=settings.allowed_origins)
    app.add_middleware(SecurityHeaders)

    @app.exception_handler(UserError)
    async def user_error(_: Request, e: UserError) -> JSONResponse:
        return JSONResponse({"detail": e.message, "fields": e.fields}, status_code=e.status)

    @app.exception_handler(HashingBusy)
    async def hashing_busy(_: Request, __: HashingBusy) -> JSONResponse:
        detail = "Lots of people are signing in right now. Try again in a few seconds."
        return JSONResponse({"detail": detail, "fields": {}}, status_code=503, headers={"Retry-After": "5"})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, e: RequestValidationError) -> JSONResponse:
        # FastAPI echoes the submitted value back by default; that would include passwords.
        errors = [{"loc": err["loc"], "msg": err["msg"], "type": err["type"]} for err in e.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    for router in (
        auth.router,
        me.router,
        admin.router,
        practice.router,
        daily.router,
        mock.router,
        review.router,
        review.reports,
        leaderboard.router,
        learning.router,
    ):
        app.include_router(router)

    @app.api_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
    def healthz() -> dict[str, str]:
        # Process-only on purpose: uptime probes must not wake or load the database.
        return {"status": "ok", "version": __version__}

    methods = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]
    for prefix in ("/api", "/auth"):
        app.add_api_route(prefix, _not_found, methods=methods, include_in_schema=False)
        app.add_api_route(prefix + "/{path:path}", _not_found, methods=methods, include_in_schema=False)

    # Question images, named by content hash, so they never change once written.
    app.mount("/media", ImmutableStatic(directory=settings.media_dir, check_dir=False), name="media")
    _mount_spa(app, settings.web_dist)
    return app


def _not_found() -> None:
    raise HTTPException(status_code=404)


def _mount_spa(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if not index.is_file():
        return
    root = dist.resolve()
    if (dist / "assets").is_dir():
        app.mount("/assets", ImmutableStatic(directory=dist / "assets"), name="assets")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str) -> FileResponse:
        try:
            file = (dist / path).resolve()
            if path and file.is_file() and file.is_relative_to(root):
                return FileResponse(file)
        except (ValueError, OSError):  # NUL bytes, over-long names
            pass
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


class ImmutableStatic(StaticFiles):
    """Vite emits content-hashed file names under /assets, so they can be cached forever."""

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


app = create_app()
