#!/usr/bin/env python3
"""Live post-scrape status for tmux; prints FINDINGS.md when matching is done."""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
YAD2 = HERE.parent
os.chdir(HERE)


def cache_stats() -> tuple[int, int]:
    p = HERE / "geo_cache.json"
    if not p.exists():
        return 0, 0
    try:
        cache = json.loads(p.read_text())
    except json.JSONDecodeError:
        return 0, 0
    hits = sum(1 for v in cache.values() if v)
    return len(cache), hits


def geo_count(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    try:
        rows = json.loads(path.read_text())
    except json.JSONDecodeError:
        return 0, 0
    n = len(rows) if isinstance(rows, list) else 0
    g = sum(1 for r in rows if isinstance(r, dict) and r.get("lat") not in (None, ""))
    return n, g


def run_alive() -> bool:
    try:
        out = subprocess.check_output(["pgrep", "-f", "yad2/research/run.py"], text=True)
        return bool(out.strip())
    except subprocess.CalledProcessError:
        return False


def yield_rows() -> list:
    p = HERE / "sale_yield.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def phase() -> str:
    log = (HERE / "run.log").read_text() if (HERE / "run.log").exists() else ""
    sale_done = '"folder": "/home/s/opt/yad2/sale"' in log
    rent_done = '"folder": "/home/s/opt/yad2/rent"' in log
    rows = yield_rows()
    alive = run_alive()
    if rows and '"yield_rows"' in log:
        return "done"
    if rent_done and alive:
        return "matching"
    if sale_done and alive:
        return "geocoding-rent"
    if alive:
        return "geocoding-sale"
    if rows:
        return "done"
    return "waiting"


def load_heartbeat() -> dict:
    p = HERE / "progress.json"
    if not p.exists():
        return {}
    try:
        h = json.loads(p.read_text())
        return h if isinstance(h, dict) else {}
    except Exception:
        return {}


def render_progress() -> str:
    keys, hits = cache_stats()
    sn, sg = 3271, 3271
    rn, rg = 3931, 0
    h = load_heartbeat()
    label = h.get("label") or ""
    if label == "rent" and h.get("total"):
        rn, rg = int(h["total"]), int(h.get("geocoded") or 0)
    elif label == "sale" and h.get("total"):
        sn, sg = int(h["total"]), int(h.get("geocoded") or 0)
    else:
        rn, rg = geo_count(YAD2 / "rent" / "listings_geo.json")
        if rg:
            pass
        sn, sg = geo_count(YAD2 / "sale" / "listings_geo.json")
    ph = phase()
    now = datetime.now().strftime("%H:%M:%S")
    lines = [
        f"{now}  {ph}  cache {hits}/{keys}",
        f"sale geo {sg}/{sn or 3271}   rent geo {rg}/{rn or 3931}",
        "pair: ≤600m AND rooms/size/elevator/ממד/parking",
    ]
    return "\n".join(lines)


def main() -> None:
    last_phase = ""
    while True:
        ph = phase()
        print("\033[2J\033[H", end="")
        print(render_progress(), flush=True)
        findings = HERE / "FINDINGS.md"
        if ph == "done" and (yield_rows() or findings.exists()):
            if not findings.exists() or "No sale/rent pairs" in findings.read_text()[:80]:
                subprocess.run(["python3", str(HERE / "findings.py")], check=False)
            text = findings.read_text() if findings.exists() else ""
            # compact pane: first scale bullets
            brief = []
            for line in text.splitlines():
                if line.startswith("- ") or line.startswith("# "):
                    brief.append(line[:120])
                if len(brief) >= 8:
                    break
            print("\n" + "\n".join(brief), flush=True)
            print(f"\nfull: {findings}", flush=True)
            break
        if ph != last_phase:
            last_phase = ph
        time.sleep(2)
    print("\nIdle. FINDINGS.md is in this directory. Ctrl-C to close this pane.", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
