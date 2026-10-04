from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from app import logging_config
from app.logging_config import scrub_event
from app.main import app
from app.middleware import new_correlation_id, resolve_correlation_id

CHAT_BODY = {
    "user_id": "student-01",
    "session_id": "session-01",
    "feature": "qa",
    "message": "Contact me at student@vinuni.edu.vn or 0901234567",
}


def _post_chat(headers: dict | None = None) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/chat", json=CHAT_BODY, headers=headers or {})

    return asyncio.run(send())


def _read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_generated_correlation_id_has_required_format() -> None:
    assert re.fullmatch(r"req-[0-9a-f]{8}", new_correlation_id())
    assert re.fullmatch(r"req-[0-9a-f]{8}", resolve_correlation_id(None))


def test_incoming_request_id_is_reused_and_unsafe_ids_are_replaced() -> None:
    assert resolve_correlation_id("req-deadbeef") == "req-deadbeef"
    assert re.fullmatch(r"req-[0-9a-f]{8}", resolve_correlation_id("bad id\nwith newline"))
    assert re.fullmatch(r"req-[0-9a-f]{8}", resolve_correlation_id("x" * 200))


def test_response_headers_and_logs_carry_the_same_correlation_id(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    response = _post_chat({"x-request-id": "req-cafe0001"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-cafe0001"
    assert int(response.headers["x-response-time-ms"]) >= 0
    assert response.json()["correlation_id"] == "req-cafe0001"
    events = _read_events(log_path)
    assert events and all(e["correlation_id"] == "req-cafe0001" for e in events)


def test_logs_are_enriched_and_pii_is_scrubbed(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    _post_chat()

    raw = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in raw
    assert "0901234567" not in raw
    received = next(e for e in _read_events(log_path) if e["event"] == "request_received")
    for field in ("user_id_hash", "session_id", "feature", "model", "env"):
        assert received[field]
    assert received["user_id_hash"] != "student-01"
    assert "REDACTED_EMAIL" in received["payload"]["message_preview"]


def test_context_does_not_leak_between_requests(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    _post_chat({"x-request-id": "req-aaaa0001"})
    _post_chat({"x-request-id": "req-bbbb0002"})

    ids = [e["correlation_id"] for e in _read_events(log_path)]
    assert ids.count("req-aaaa0001") == ids.count("req-bbbb0002") > 0


def test_scrub_event_handles_nested_values_and_keeps_system_fields() -> None:
    event = {
        "event": "x",
        "user_id_hash": "123456789012",
        "correlation_id": "req-12345678",
        "payload": {"a": "mail a@b.com", "n": {"deep": ["call 0901234567"]}},
        "detail": "card 4111 1111 1111 1111",
    }

    out = scrub_event(None, "info", event)

    assert out["user_id_hash"] == "123456789012"
    assert out["correlation_id"] == "req-12345678"
    assert "a@b.com" not in json.dumps(out)
    assert "0901234567" not in json.dumps(out)
    assert "4111" not in out["detail"]
