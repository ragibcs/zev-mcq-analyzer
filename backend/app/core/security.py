"""Security middleware: rate limiting, body-size limits, optional API auth.

Nothing here is a substitute for deployment-level controls (reverse proxy,
TLS), but it enforces the basics for local and single-tenant deployments.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import ClassVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window in-memory rate limiter (per client IP)."""

    def __init__(self, app):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._settings = get_settings()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        limit = self._settings.rate_limit_requests
        window = self._settings.rate_limit_window_seconds
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()

        bucket = self._hits[client_ip]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Please retry later."},
            )
        bucket.append(now)
        return await call_next(request)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies larger than the configured maximum."""

    def __init__(self, app):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._max_bytes = get_settings().max_body_bytes

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        content_length = request.headers.get("content-length")
        if (
            content_length
            and content_length.isdigit()
            and int(content_length) > self._max_bytes
        ):
            return JSONResponse(
                status_code=413,
                content={"error": "Request body too large."},
            )
        return await call_next(request)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Optional shared-secret auth for the backend itself.

    Enabled only when API_KEY is set. Health check stays open for monitoring.
    """

    OPEN_PATHS: ClassVar[set[str]] = {"/health", "/docs", "/openapi.json", "/redoc"}

    def __init__(self, app):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._api_key = get_settings().api_key

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if not self._api_key or request.url.path in self.OPEN_PATHS:
            return await call_next(request)
        provided = request.headers.get("x-api-key", "")
        if provided != self._api_key:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or missing API key."},
            )
        return await call_next(request)
