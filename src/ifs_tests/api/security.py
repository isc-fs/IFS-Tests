from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
]


class SecurityHeaders:
    """Adds the security headers to every HTTP response. HSTS is set by Nginx, which terminates TLS."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    (k, v) for k, v in HEADERS if k not in present
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)


UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFGuard:
    """State-changing requests to /api and /auth must carry `X-CSRF: 1` and, if the browser sends an Origin,
    it must be ours. Cross-site pages can't add custom headers without a CORS preflight, which we never allow."""

    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self.allowed = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] in UNSAFE
            and scope["path"].startswith(("/api/", "/auth/"))
        ):
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            origin = headers.get(b"origin", b"").decode()
            if headers.get(b"x-csrf") != b"1" or (origin and origin.rstrip("/") not in self.allowed):
                await _reject(send)
                return
        await self.app(scope, receive, send)


async def _reject(send: Send) -> None:
    body = b'{"detail":"Cross-site request blocked."}'
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
