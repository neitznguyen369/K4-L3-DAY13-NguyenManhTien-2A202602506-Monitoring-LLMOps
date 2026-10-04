"""Dựng dashboard 6 panel từ data/logs.jsonl theo contract config/dashboard.yaml.

Không cần thư viện ngoài: sinh một file HTML tự chứa (biểu đồ SVG inline). Mở file bằng
trình duyệt để chụp evidence, hoặc thêm --png để render ảnh bằng wkhtmltoimage nếu có.

    python scripts/build_dashboard.py
    python scripts/build_dashboard.py --out submission/evidence/11-dashboard-overview.html --png
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio  # noqa: E402
from app.metrics import percentile  # noqa: E402

OK_COLOR = "#1a7f37"
BAD_COLOR = "#cf222e"
LINE_COLOR = "#0969da"
LINE2_COLOR = "#8250df"


# --------------------------------------------------------------------------- data
def load_records(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            rec["_ts"] = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
        except (KeyError, ValueError, AttributeError):
            continue
        records.append(rec)
    return records


def minute_key(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def bucket_series(records: list[dict], start: datetime, minutes: int, value_fn, agg) -> list[float | None]:
    """Gom record theo phút trong cửa sổ [start, start+minutes) rồi áp dụng agg."""
    buckets: dict[int, list[float]] = defaultdict(list)
    for rec in records:
        idx = int((minute_key(rec["_ts"]) - start).total_seconds() // 60)
        if 0 <= idx < minutes:
            value = value_fn(rec)
            if value is not None:
                buckets[idx].append(value)
    return [agg(buckets[i]) if buckets.get(i) else None for i in range(minutes)]


# --------------------------------------------------------------------------- svg
def svg_chart(values: list[float | None], *, kind: str, threshold: float | None, unit: str,
              color: str = LINE_COLOR, width: int = 420, height: int = 130) -> str:
    left, right, top, bottom = 46, 8, 8, 20
    plot_w, plot_h = width - left - right, height - top - bottom
    present = [v for v in values if v is not None]
    ymax = max(present + ([threshold] if threshold is not None else []) + [1e-9]) * 1.15
    n = max(len(values), 1)

    def x(i: float) -> float:
        return left + plot_w * (i + 0.5) / n

    def y(v: float) -> float:
        return top + plot_h * (1 - v / ymax)

    parts = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" '
             f'style="background:#fff;border:1px solid #d0d7de">']
    for frac in (0, 0.5, 1):
        gy = top + plot_h * (1 - frac)
        parts.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{width - right}" y2="{gy:.1f}" stroke="#eaeef2"/>')
        parts.append(f'<text x="{left - 4}" y="{gy + 3:.1f}" font-size="9" text-anchor="end" fill="#57606a">'
                     f'{fmt(ymax * frac)}</text>')
    if kind == "bar":
        bar_w = max(2.0, plot_w / n * 0.7)
        for i, v in enumerate(values):
            if v is not None:
                parts.append(f'<rect x="{x(i) - bar_w / 2:.1f}" y="{y(v):.1f}" width="{bar_w:.1f}" '
                             f'height="{top + plot_h - y(v):.1f}" fill="{color}"/>')
    else:
        pts = [(x(i), y(v)) for i, v in enumerate(values) if v is not None]
        if len(pts) > 1:
            parts.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>'
                         % (color, " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)))
        for px, py in pts:
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{color}"/>')
    if threshold is not None:
        ty = y(threshold)
        parts.append(f'<line x1="{left}" y1="{ty:.1f}" x2="{width - right}" y2="{ty:.1f}" '
                     f'stroke="{BAD_COLOR}" stroke-dasharray="5,3"/>')
        parts.append(f'<text x="{width - right - 2}" y="{ty - 3:.1f}" font-size="9" text-anchor="end" '
                     f'fill="{BAD_COLOR}">threshold {fmt(threshold)} {html.escape(unit)}</text>')
    parts.append(f'<text x="{left}" y="{height - 6}" font-size="9" fill="#57606a">-{n} min</text>')
    parts.append(f'<text x="{width - right}" y="{height - 6}" font-size="9" text-anchor="end" fill="#57606a">now</text>')
    parts.append("</svg>")
    return "".join(parts)


def fmt(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 1:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


# --------------------------------------------------------------------------- panels
def check(value: float, threshold: dict) -> bool:
    return value <= threshold["value"] if threshold["operator"] == "lte" else value >= threshold["value"]


def panel_html(panel: dict, big: str, ok: bool, chart: str, notes: list[str]) -> str:
    th = panel["threshold"]
    op = "≤" if th["operator"] == "lte" else "≥"
    color = OK_COLOR if ok else BAD_COLOR
    status = "OK" if ok else "BREACH"
    note_html = "".join(f"<div class='note'>{html.escape(n)}</div>" for n in notes)
    return (
        "<div class='panel'>"
        f"<div class='title'>{html.escape(panel['title'])} "
        f"<span class='unit'>[{html.escape(panel['unit'])}]</span></div>"
        f"<div class='big' style='color:{color}'>{html.escape(big)} "
        f"<span class='badge' style='background:{color}'>{status}</span></div>"
        f"<div class='slo'>SLO/threshold: {th['aggregation']} {op} {th['value']}</div>"
        f"{chart}{note_html}</div>"
    )


def build(records: list[dict], cfg: dict, end: datetime) -> tuple[str, dict]:
    dash = cfg["dashboard"]
    minutes = int(dash["time_range_minutes"])
    start = minute_key(end) - timedelta(minutes=minutes - 1)
    window = [r for r in records if start <= r["_ts"] < minute_key(end) + timedelta(minutes=1)]
    panels = {p["id"]: p for p in dash["panels"]}

    received = [r for r in window if r.get("event") == "request_received"]
    sent = [r for r in window if r.get("event") == "response_sent"]
    failed = [r for r in window if r.get("event") == "request_failed"]

    lat = [r["latency_ms"] for r in sent if r.get("latency_ms") is not None]
    ttft = [r["ttft_ms"] for r in sent if r.get("ttft_ms") is not None]
    p50, p95, p99 = (percentile(lat, p) for p in (50, 95, 99))
    ttft_p95 = percentile(ttft, 95)

    active_minutes = max(1, len({minute_key(r["_ts"]) for r in received})) if received else 1
    rate = len(received) / active_minutes
    error_rate = (len(failed) / len(received) * 100) if received else 0.0
    tool_events = [r for r in window if r.get("tool_success") is not None]
    retrieval_success = (sum(1 for r in tool_events if r["tool_success"] is True) / len(tool_events) * 100
                         if tool_events else 100.0)
    error_breakdown = Counter(r.get("error_type", "unknown") for r in failed)
    total_cost = sum(r.get("cost_usd") or 0 for r in sent)
    tok_in = sum(r.get("tokens_in") or 0 for r in sent)
    tok_out = sum(r.get("tokens_out") or 0 for r in sent)
    quality = mean([r["quality_score"] for r in sent if r.get("quality_score") is not None] or [0.0])

    latency_series = bucket_series(sent, start, minutes, lambda r: r.get("latency_ms"),
                                   lambda v: percentile([int(x) for x in v], 95))
    traffic_series = bucket_series(received, start, minutes, lambda r: 1.0, lambda v: float(len(v)))
    error_series = bucket_series(failed, start, minutes, lambda r: 1.0, lambda v: float(len(v)))
    cost_series = bucket_series(sent, start, minutes, lambda r: r.get("cost_usd"), sum)
    token_series = bucket_series(sent, start, minutes,
                                 lambda r: (r.get("tokens_in") or 0) + (r.get("tokens_out") or 0), sum)
    quality_series = bucket_series(sent, start, minutes, lambda r: r.get("quality_score"), mean)

    def th(pid: str) -> dict:
        return panels[pid]["threshold"]

    cards = [
        panel_html(panels["latency"], f"P95 {fmt(p95)} ms", check(p95, th("latency")),
                   svg_chart(latency_series, kind="line", threshold=th("latency")["value"], unit="ms"),
                   [f"P50 {fmt(p50)} ms | P95 {fmt(p95)} ms | P99 {fmt(p99)} ms | TTFT P95 {fmt(ttft_p95)} ms",
                    "Chart: P95 latency per minute"]),
        panel_html(panels["traffic"], f"{fmt(rate)} req/min", check(rate, th("traffic")),
                   svg_chart(traffic_series, kind="bar", threshold=th("traffic")["value"], unit="req/min"),
                   [f"Total requests in window: {len(received)}", "Chart: requests per minute"]),
        panel_html(panels["errors"], f"{fmt(error_rate)} % errors", check(error_rate, th("errors")),
                   svg_chart(error_series, kind="bar", threshold=None, unit="errors", color=BAD_COLOR),
                   [f"Retrieval success: {fmt(retrieval_success)} % (min 90 %)",
                    "Error breakdown: " + (", ".join(f"{k}={v}" for k, v in error_breakdown.items()) or "none"),
                    "Chart: failed requests per minute"]),
        panel_html(panels["cost"], f"$ {total_cost:.4f}", check(total_cost, th("cost")),
                   svg_chart(cost_series, kind="bar", threshold=th("cost")["value"], unit="usd", color=LINE2_COLOR),
                   [f"Avg cost / request: $ {(total_cost / len(sent) if sent else 0):.6f}",
                    "Chart: cost per minute"]),
        panel_html(panels["tokens"], f"in {tok_in:,} / out {tok_out:,}",
                   check(max(tok_in, tok_out), th("tokens")),
                   svg_chart(token_series, kind="bar", threshold=th("tokens")["value"], unit="tokens"),
                   ["Threshold applies to each of tokens_in and tokens_out",
                    "Chart: total tokens per minute"]),
        panel_html(panels["quality"], f"{quality:.2f}", check(quality, th("quality")),
                   svg_chart(quality_series, kind="line", threshold=th("quality")["value"], unit="score",
                             color=OK_COLOR),
                   ["Heuristic quality proxy (0-1), mean of response_sent.quality_score",
                    "Chart: mean quality per minute"]),
    ]

    stamp = f"{start:%Y-%m-%d %H:%M} → {minute_key(end):%H:%M} UTC"
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(dash['title'])}</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;background:#f6f8fa;margin:12px;color:#24292f}}
h1{{font-size:18px;margin:0 0 2px}} .sub{{font-size:12px;color:#57606a;margin-bottom:10px}}
.panel{{display:inline-block;vertical-align:top;width:440px;background:#fff;border:1px solid #d0d7de;
border-radius:6px;padding:8px 10px;margin:0 8px 10px 0}}
.title{{font-weight:bold;font-size:13px}} .unit{{font-weight:normal;color:#57606a}}
.big{{font-size:22px;font-weight:bold;margin:4px 0}}
.badge{{font-size:10px;color:#fff;padding:2px 6px;border-radius:8px;vertical-align:middle}}
.slo{{font-size:11px;color:#57606a;margin-bottom:4px}} .note{{font-size:11px;color:#57606a;margin-top:3px}}
</style></head><body>
<h1>{html.escape(dash['title'])}</h1>
<div class="sub">Source: data/logs.jsonl | Time range: last {minutes} min ({stamp}) |
Auto-refresh target: {dash['refresh_seconds']}s | Records in window: {len(window)}</div>
{''.join(cards)}
</body></html>"""
    summary = {
        "window": stamp, "requests": len(received), "latency_p50": p50, "latency_p95": p95,
        "latency_p99": p99, "ttft_p95": ttft_p95, "rate_per_min": round(rate, 2),
        "error_rate_pct": round(error_rate, 2), "retrieval_success_pct": round(retrieval_success, 2),
        "total_cost_usd": round(total_cost, 6), "tokens_in": tok_in, "tokens_out": tok_out,
        "quality_mean": round(quality, 3),
    }
    return page, summary


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Dựng dashboard 6 panel từ data/logs.jsonl")
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "dashboard.html")
    parser.add_argument("--png", action="store_true", help="Render thêm ảnh PNG bằng wkhtmltoimage (nếu có)")
    parser.add_argument("--end", help="Mốc cuối cửa sổ (ISO UTC). Mặc định: bây giờ.")
    args = parser.parse_args()

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    records = load_records(args.logs)
    if not records:
        print(f"Không có log hợp lệ trong {args.logs}. Hãy chạy API và load test trước.")
        return 1
    end = datetime.fromisoformat(args.end.replace("Z", "+00:00")) if args.end else datetime.now(timezone.utc)

    page, summary = build(records, cfg, end)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(f"Đã ghi {args.out}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.png:
        tool = shutil.which("wkhtmltoimage")
        if not tool:
            print("Không tìm thấy wkhtmltoimage; hãy mở file HTML bằng trình duyệt và chụp màn hình.")
            return 0
        png = args.out.with_suffix(".png")
        subprocess.run([tool, "--quiet", "--width", "1400", str(args.out), str(png)], check=False)
        print(f"Đã render {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
