from __future__ import annotations

import re
import secrets
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

TRACE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
trace_id_context: ContextVar[str] = ContextVar("trace_id", default="unknown")


def current_trace_id() -> str:
    return trace_id_context.get()


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-trace-id", "")
        trace_id = incoming if TRACE_PATTERN.fullmatch(incoming) else secrets.token_hex(16)
        token = trace_id_context.set(trace_id)
        try:
            response = await call_next(request)
            response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            trace_id_context.reset(token)
