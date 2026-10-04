from __future__ import annotations

import hashlib
import re

# Thứ tự quan trọng: pattern dài/đặc thù chạy trước để không bị pattern ngắn cắt dở
# (ví dụ số thẻ 16 số không bị nhận nhầm thành số điện thoại).
PII_PATTERNS: dict[str, str] = {
    "email": r"[\w\.-]+@[\w\.-]+\.\w+",
    "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
    "cccd": r"\b\d{12}\b",
    "phone_vn": r"(?<!\d)(?:\+84|0)(?:[ .-]?\d){9}(?!\d)",
    # Hộ chiếu Việt Nam: 1 chữ cái + 7 chữ số (ví dụ B1234567).
    "passport": r"\b[A-Z]\d{7}\b",
    # Địa chỉ Việt Nam: số nhà + từ khóa đường/phố/ngõ/ngách/hẻm + tên.
    "address": (
        r"(?i)\b(?:số\s+)?\d{1,4}[a-z]?(?:/\d+)*\s+"
        r"(?:đường|phố|ngõ|ngách|hẻm)\s+[^,.;\n]{1,40}"
    ),
}

_COMPILED = {name: re.compile(pattern) for name, pattern in PII_PATTERNS.items()}


def scrub_text(text: str) -> str:
    safe = text
    for name, pattern in _COMPILED.items():
        safe = pattern.sub(f"[REDACTED_{name.upper()}]", safe)
    return safe


def summarize_text(text: str, max_len: int = 80) -> str:
    safe = scrub_text(text).strip().replace("\n", " ")
    return safe[:max_len] + ("..." if len(safe) > max_len else "")


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
