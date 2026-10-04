"""Refuse state-changing requests that a web page the user is visiting could send to this local app.

A browser sends a cross-site POST to 127.0.0.1 even though CORS hides the answer, so a hostile page could start GPU parsing
and paid OpenAI calls. Browsers always put `Origin` on such a POST (and `Sec-Fetch-Site: cross-site`), so the app only
accepts its own origin. Requests without these headers (curl, tests) are not browser-driven and pass.
"""
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def allowed_origins(port: int) -> set[str]:
    return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}


def add_origin_guard(app: FastAPI, port: int) -> None:
    allowed = allowed_origins(port)

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if (origin is not None and origin not in allowed) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        return await call_next(request)
