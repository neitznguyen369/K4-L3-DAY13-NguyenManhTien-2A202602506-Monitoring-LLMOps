from __future__ import annotations

import re
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars

# Chỉ chấp nhận ID "sạch" từ client để tránh log injection / ID quá dài.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def new_correlation_id() -> str:
    """Sinh ID theo format req-<8 ký tự hex>."""
    return f"req-{uuid.uuid4().hex[:8]}"


def resolve_correlation_id(header_value: str | None) -> str:
    """Dùng lại x-request-id hợp lệ từ client, nếu không thì sinh ID mới."""
    candidate = (header_value or "").strip()
    if candidate and _VALID_REQUEST_ID.match(candidate):
        return candidate
    return new_correlation_id()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Xóa context của request trước để không rò metadata giữa các request.
        clear_contextvars()

        correlation_id = resolve_correlation_id(request.headers.get("x-request-id"))

        # Mọi log phát ra trong request này sẽ tự có correlation_id.
        bind_contextvars(correlation_id=correlation_id)

        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        response = await call_next(request)

        response.headers["x-request-id"] = correlation_id
        response.headers["x-response-time-ms"] = str(int((time.perf_counter() - start) * 1000))

        return response
