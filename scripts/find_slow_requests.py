"""Bước 2 của Metrics -> Logs -> Traces: lọc log để lấy correlation_id của request bất thường.

    python scripts/find_slow_requests.py --threshold-ms 2000
    python scripts/find_slow_requests.py --threshold-ms 2000 --feature monitoring --top 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio  # noqa: E402


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Liệt kê request chậm/lỗi từ data/logs.jsonl")
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument("--threshold-ms", type=int, default=2000)
    parser.add_argument("--feature", help="Chỉ xét một feature")
    parser.add_argument("--since", help="Chỉ xét log có ts >= giá trị này (ISO, ví dụ 2026-09-30T09:27:00)")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    if not args.logs.exists():
        print(f"Không tìm thấy {args.logs}")
        return 1

    rows = []
    for line in args.logs.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if args.since and rec.get("ts", "") < args.since:
            continue
        if args.feature and rec.get("feature") != args.feature:
            continue
        if rec.get("event") == "response_sent" and (rec.get("latency_ms") or 0) > args.threshold_ms:
            rows.append(rec)
        elif rec.get("event") == "request_failed":
            rows.append(rec)

    rows.sort(key=lambda r: r.get("latency_ms") or 0, reverse=True)
    print(f"{len(rows)} request bất thường (latency > {args.threshold_ms} ms hoặc request_failed)")
    for rec in rows[: args.top]:
        print(
            f"{rec['ts']} | {rec['event']:<14} | {rec['correlation_id']} | feature={rec.get('feature')} | "
            f"latency_ms={rec.get('latency_ms')} | ttft_ms={rec.get('ttft_ms')} | error_type={rec.get('error_type')}"
        )
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
