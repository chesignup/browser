#!/usr/bin/env python3
"""
yad2 scrape watchdog — keep CDP detail batches running through interrupts.

Tab policy: exactly ONE Chromium tab per batch worker. Reuse it via
yad2_cdp_tabs.ensure_scrape_tab(); never open tabs in captcha wait loops.

Recovers from:
  - hung / dead tabs (navigate same tab in-place)
  - captcha / Radware (poll single tab; human clears at viewer)
  - empty batch JSON / apply failures (bounded retries)

Usage (from job workdir containing cdp_scrape_batch.py):
  python3 /root/.cursor/skills/yad2/scripts/scrape_watchdog.py \\
    --workdir /root/work/rent --kind rent --batch 40
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/root/work")
from yad2_cdp_tabs import ensure_scrape_tab_sync, is_captcha_page, list_pages  # noqa: E402

VIEWER_HINT = "http://100.92.122.70:6081/"


def read_progress(workdir: Path) -> dict:
    path = workdir / "scrape_progress.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def run_batch(workdir: Path, batch: int, timeout: int) -> tuple[int, str]:
    cmd = [sys.executable, str(workdir / "cdp_scrape_batch.py"), str(batch)]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        return proc.returncode, out.strip()
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        return 124, out + "\nWATCHDOG_SUBPROCESS_TIMEOUT"


def parse_last_json(out: str) -> dict | None:
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except Exception:
                continue
    return None


def wait_captcha_clear(kind: str, viewer: str, deadline: float, poll: int) -> bool:
    """Poll the single scrape tab — do NOT open new tabs."""
    print(json.dumps({
        "watchdog": "captcha",
        "viewer": viewer,
        "hint": "Complete Press & Hold on the one open yad2 tab",
        "tabs": len(list_pages()),
    }), flush=True)
    while time.time() < deadline:
        info = ensure_scrape_tab_sync(kind, navigate=False)
        if info.get("live") and not info.get("captcha"):
            print(json.dumps({"watchdog": "captcha_cleared", "tab": info.get("id")}), flush=True)
            return True
        time.sleep(poll)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default="/root/work", type=Path)
    ap.add_argument("--kind", default="forsale", choices=["forsale", "sale", "rent"])
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--max-iters", type=int, default=200)
    ap.add_argument("--batch-timeout", type=int, default=360)
    ap.add_argument("--captcha-wait", type=int, default=600)
    ap.add_argument("--captcha-poll", type=int, default=15)
    ap.add_argument("--max-consecutive-fail", type=int, default=8)
    ap.add_argument("--viewer", default=VIEWER_HINT)
    ap.add_argument(
        "--batch-pause",
        type=int,
        default=15,
        help="seconds to sleep after a successful batch (Radware per-session quota)",
    )
    args = ap.parse_args()

    workdir: Path = args.workdir
    if not (workdir / "cdp_scrape_batch.py").exists():
        print(f"missing cdp_scrape_batch.py in {workdir}", file=sys.stderr)
        sys.exit(1)

    kind = "sale" if args.kind == "forsale" else args.kind
    start = time.time()
    fails = 0

    # Startup: one tab only
    boot = ensure_scrape_tab_sync(kind, navigate=True)
    print(json.dumps({"watchdog": "boot", **boot}), flush=True)

    for i in range(1, args.max_iters + 1):
        info = ensure_scrape_tab_sync(kind, navigate=False)
        if info.get("captcha") or not info.get("live"):
            if not wait_captcha_clear(kind, args.viewer, time.time() + args.captcha_wait, args.captcha_poll):
                print(json.dumps({"watchdog": "captcha_timeout", "progress": read_progress(workdir)}), flush=True)
                sys.exit(3)

        rc, out = run_batch(workdir, args.batch, args.batch_timeout)
        last = parse_last_json(out) or {}
        print(out[-2000:] if len(out) > 2000 else out, flush=True)

        if last.get("done") is True or last.get("pending") == 0:
            print(json.dumps({
                "watchdog": "complete",
                "iters": i,
                "elapsed_s": int(time.time() - start),
                "progress": read_progress(workdir),
            }), flush=True)
            sys.exit(0)

        if last.get("captcha") or rc == 3:
            if not wait_captcha_clear(kind, args.viewer, time.time() + args.captcha_wait, args.captcha_poll):
                fails += 1
                if fails >= args.max_consecutive_fail:
                    print(json.dumps({"watchdog": "captcha_give_up", "progress": read_progress(workdir)}), flush=True)
                    sys.exit(3)
                continue
            fails = 0
            continue

        if rc == 0 and ("batch_ok" in (out or "") or last.get("batch_ok") is not None):
            fails = 0
            pending = last.get("pending")
            done = last.get("done")
            print(json.dumps({
                "watchdog": "ok",
                "iter": i,
                "done": done,
                "pending": pending,
                "tabs": len(list_pages()),
                "elapsed_s": int(time.time() - start),
            }), flush=True)
            if pending == 0:
                print(json.dumps({"watchdog": "complete", "progress": read_progress(workdir)}), flush=True)
                sys.exit(0)
            if args.batch_pause > 0:
                time.sleep(args.batch_pause)
            continue

        fails += 1
        print(json.dumps({
            "watchdog": "recover",
            "iter": i,
            "rc": rc,
            "fails": fails,
            "action": "navigate_same_tab",
        }), flush=True)
        ensure_scrape_tab_sync(kind, navigate=True)
        time.sleep(2)
        if fails >= args.max_consecutive_fail:
            print(json.dumps({
                "watchdog": "exhausted",
                "progress": read_progress(workdir),
                "last": last,
            }), flush=True)
            sys.exit(1)

    print(json.dumps({"watchdog": "max_iters", "progress": read_progress(workdir)}), flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
