#!/usr/bin/env python3
"""Terminal dashboard: progress bar + per-city table for rent detail scrape."""
from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/root/work/rent")
PROGRESS = ROOT / "scrape_progress.json"
MASTER = ROOT / "master_listings.json"
DETAILS = ROOT / "listing_details.json"
WATCHDOG_LOGS = (
    Path("/tmp/rent_watchdog.log"),
    Path("/tmp/rent_ramatgan_watchdog.log"),
    Path("/tmp/rent_detail_watchdog.log"),
)

BAR_WIDTH = 40


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def city_stats() -> tuple[dict, dict, dict[str, str]]:
    master = load_json(MASTER, [])
    details = load_json(DETAILS, [])
    if isinstance(details, dict):
        detail_rows = list(details.values())
    else:
        detail_rows = details or []
    token_city = {m["token"]: m.get("city") or "?" for m in master if m.get("token")}
    feed_by_city = Counter(token_city.values())
    done_by_city: Counter = Counter()
    err_by_city: Counter = Counter()
    for d in detail_rows:
        tok = d.get("token")
        if not tok:
            continue
        city = token_city.get(tok) or d.get("city") or "?"
        if d.get("error"):
            err_by_city[city] += 1
        else:
            done_by_city[city] += 1
    return dict(feed_by_city), {"done": done_by_city, "err": err_by_city}, token_city


def _read_watchdog_log() -> list[str]:
    best: Path | None = None
    best_mtime = 0.0
    for path in WATCHDOG_LOGS:
        if path.exists() and path.stat().st_mtime >= best_mtime:
            best, best_mtime = path, path.stat().st_mtime
    if not best:
        return []
    try:
        return best.read_text().splitlines()
    except Exception:
        return []


def watchdog_status() -> tuple[str, str]:
    lines = _read_watchdog_log()
    if not lines:
        return "unknown", ""
    try:
        for line in reversed(lines):
            if '"watchdog": "ok"' in line or '"batch_ok"' in line:
                return "running", line[:100]
            if '"watchdog": "complete"' in line:
                return "complete", line[:100]
        for line in reversed(lines):
            if '"watchdog": "captcha"' in line and '"watchdog": "captcha_cleared"' not in line:
                return "CAPTCHA — open http://100.92.122.70:6081/", line[:100]
            if '"watchdog": "exhausted"' in line or '"watchdog": "captcha_give_up"' in line:
                return "stalled", line[:100]
    except Exception:
        pass
    return "unknown", ""


def bar(done: int, total: int) -> str:
    if total <= 0:
        return "[" + "?" * BAR_WIDTH + "]"
    pct = done / total
    filled = int(BAR_WIDTH * pct)
    return "[" + "#" * filled + "-" * (BAR_WIDTH - filled) + "]"


def main() -> None:
    prog = load_json(PROGRESS, {})
    done = int(prog.get("done") or 0)
    total = int(prog.get("total") or 0)
    errors = int(prog.get("errors") or 0)
    pending = max(0, total - done)
    pct = (100.0 * done / total) if total else 0.0
    updated = prog.get("updated_at") or "—"
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    feed, stats, _ = city_stats()
    status, status_line = watchdog_status()
    cities = sorted(feed.keys(), key=lambda c: (-feed[c], c))
    term_w = shutil.get_terminal_size(fallback=(100, 24)).columns

    print("yad2 rent scrape — detail progress")
    print(f"updated {updated}  ·  display {now}")
    print()
    print(f"{bar(done, total)}  {done}/{total}  ({pct:.1f}%)")
    print(f"pending {pending}  ·  errors {errors}  ·  watchdog: {status}")
    print()
    hdr = f"{'city':<14} {'feed':>6} {'ok':>6} {'left':>6} {'err':>4} {'ok%':>6}"
    print(hdr)
    print("-" * min(term_w, len(hdr)))
    for city in cities:
        f = feed.get(city, 0)
        d = stats["done"].get(city, 0)
        e = stats["err"].get(city, 0)
        left = max(0, f - d - e)
        ok_pct = (100.0 * d / f) if f else 0.0
        mark = " ✓" if f and d == f and e == 0 else ""
        print(f"{city:<14} {f:>6} {d:>6} {left:>6} {e:>4} {ok_pct:>5.1f}%{mark}")
    print("-" * min(term_w, len(hdr)))
    print(f"{'TOTAL':<14} {total:>6} {done:>6} {pending:>6} {errors:>4} {pct:>5.1f}%")
    print("ok% = successfully scraped (100% ✓ = city complete, not errors)")
    if status_line:
        print()
        print("last:", status_line)


if __name__ == "__main__":
    main()
