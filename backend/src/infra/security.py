from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.config import ServerSettings
from core.errors import app_error
from infra.trace import current_trace_id

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, *, settings: ServerSettings | None = None) -> None:
        super().__init__(app)
        self.default_settings = settings or ServerSettings()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        active_settings = getattr(
            getattr(request.app.state, "settings", None),
            "server",
            self.default_settings,
        )
        origin = request.headers.get("origin")
        if (
            request.method in WRITE_METHODS
            and origin is not None
            and origin.rstrip("/") != active_settings.public_origin.rstrip("/")
        ):
            error = app_error("ORIGIN_FORBIDDEN")
            response: Response = JSONResponse(
                status_code=error.status_code,
                content={
                    "error_code": error.error_code,
                    "message": error.message,
                    "trace_id": current_trace_id(),
                },
            )
        else:
            response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        if active_settings.https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
