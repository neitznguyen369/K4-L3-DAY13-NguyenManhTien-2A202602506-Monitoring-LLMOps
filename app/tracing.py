from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

try:
    from langfuse import get_client, observe, propagate_attributes

    LANGFUSE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - chỉ dùng khi chưa cài requirements
    LANGFUSE_SDK_AVAILABLE = False

    def observe(*args: Any, **kwargs: Any):
        def decorator(func):
            return func

        return decorator

    class _DummyObservation:
        def update(self, **kwargs: Any) -> None:
            return None

    class _DummyClient:
        def update_current_span(self, **kwargs: Any) -> None:
            return None

        def update_current_generation(self, **kwargs: Any) -> None:
            return None

        def start_as_current_observation(self, **kwargs: Any):
            @contextmanager
            def _ctx():
                yield _DummyObservation()

            return _ctx()

        def flush(self) -> None:
            return None

    def get_client():
        return _DummyClient()

    @contextmanager
    def propagate_attributes(**kwargs: Any):
        yield


def get_langfuse_client():
    return get_client()


def tracing_enabled() -> bool:
    return LANGFUSE_SDK_AVAILABLE and bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )


def start_observation(**kwargs: Any):
    """Mở một child observation (retriever/generation/span...) dưới span hiện tại.

    Dùng get_client() của SDK trực tiếp để tách biệt với client được inject cho việc
    lấy prompt; observation tự lồng vào root `lab-agent-run` nhờ OpenTelemetry context.
    """
    return get_client().start_as_current_observation(**kwargs)
