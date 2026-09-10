#!/usr/bin/env python3
"""
Sync master_listings.json from listing_details.json, then re-scrape description/date gaps.

Usage:
  python3 backfill_listing_gaps.py --workdir /root/work --kind sale
  python3 backfill_listing_gaps.py --workdir /root/work/rent --kind rent --wait-cdp
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/root/work")
from yad2_cdp_tabs import ensure_scrape_tab, list_pages  # noqa: E402
from yad2_listing_fields import gap_tokens  # noqa: E402

CDP = "http://127.0.0.1:11222"
DOM_JS = r"""
(() => {
  var el = document.querySelector('[data-testid="property-description"]');
  return el ? (el.innerText || el.textContent || '').trim() : '';
})()
"""


def load_mod(workdir: Path):
    spec = importlib.util.spec_from_file_location("sld", workdir / "scrape_listing_details.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cdp_busy() -> bool:
    try:
        out = subprocess.check_output(["pgrep", "-f", "cdp_scrape_batch.py"], text=True)
        return bool(out.strip())
    except subprocess.CalledProcessError:
        return False


def sync_master(mod) -> int:
    items = mod.merge_master()
    return len(items)


def run_gap_batches(workdir: Path, batch_size: int = 10) -> None:
    while True:
        meta = json.loads(
            subprocess.check_output(
                [sys.executable, str(workdir / "next_scrape_batch.py"), str(batch_size), "--gap-only"],
                text=True,
            )
        )
        if meta.get("batch_size", 0) == 0:
            break
        if cdp_busy():
            time.sleep(5)
            continue
        subprocess.run(
            [sys.executable, str(workdir / "cdp_scrape_batch.py"), str(batch_size), "--gap-only"],
            cwd=str(workdir),
            check=False,
        )
        time.sleep(1)


async def _eval(page: dict, expr: str, timeout: float = 30):
    import websockets

    ws_url = re.sub(r"ws://[^/]+", "ws://127.0.0.1:11222", page["webSocketDebuggerUrl"])
    try:
        ws = await websockets.connect(ws_url, open_timeout=8, max_size=5_000_000)
    except TypeError:
        ws = await websockets.connect(ws_url, max_size=5_000_000)
    await ws.send(json.dumps({
        "id": 1,
        "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True},
    }))
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            data = json.loads(raw)
            if data.get("id") != 1:
                continue
            return data.get("result", {}).get("result", {}).get("value")
    finally:
        await ws.close()


async def _navigate(page: dict, url: str, timeout: float = 25):
    import websockets

    ws_url = re.sub(r"ws://[^/]+", "ws://127.0.0.1:11222", page["webSocketDebuggerUrl"])
    try:
        ws = await websockets.connect(ws_url, open_timeout=8, max_size=5_000_000)
    except TypeError:
        ws = await websockets.connect(ws_url, max_size=5_000_000)
    await ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=max(1, deadline - time.time()))
        data = json.loads(raw)
        if data.get("id") == 1:
            break
    await ws.close()
    await asyncio.sleep(2)


async def dom_backfill(mod, kind: str, tokens: list[str]) -> int:
    if not tokens:
        return 0
    tab = await ensure_scrape_tab(kind, navigate=False)
    pages = [p for p in list_pages() if p.get("type") == "page"]
    page = next((p for p in pages if p.get("id") == tab.get("id")), None)
    if not page:
        raise RuntimeError("no CDP page for DOM backfill")
    master = {m["token"]: m for m in json.loads(mod.MASTER.read_text())}
    done = mod.load_details()
    fixed = 0
    for token in tokens:
        row = done.get(token)
        link = (row or {}).get("link") or (master.get(token) or {}).get("link")
        if not link:
            continue
        await _navigate(page, link)
        desc = await _eval(page, DOM_JS, timeout=20)
        if not desc or not str(desc).strip():
            continue
        feed = master.get(token) or {"token": token, "listing_type": kind, "link": link}
        api = {"dom_description": str(desc).strip(), "info_text": str(desc).strip()}
        existing = done.get(token) or feed
        parsed = mod.parse_api_item(
            token,
            feed,
            {**api, "date_added": existing.get("date_advertised") or ""},
            existing.get("views"),
        )
        done[token] = parsed
        fixed += 1
    mod.save_details(done)
    sync_master(mod)
    return fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("--kind", choices=["sale", "rent"], required=True)
    ap.add_argument("--wait-cdp", action="store_true", help="wait until cdp_scrape_batch idle")
    ap.add_argument("--skip-rescrape", action="store_true", help="only sync master from details")
    args = ap.parse_args()

    mod = load_mod(args.workdir)
    n = sync_master(mod)
    print(json.dumps({"sync_master": n}), flush=True)

    if args.skip_rescrape:
        return

    gaps_before = gap_tokens(mod.load_details())
    print(json.dumps({"gaps_before": len(gaps_before), "sample": gaps_before[:8]}), flush=True)
    if not gaps_before:
        return

    if args.wait_cdp:
        while cdp_busy():
            time.sleep(5)

    # Patch cdp_scrape_batch to accept --gap-only via next_scrape_batch (already wired).
    # Run batches until gap queue empty.
    old_argv = sys.argv
    try:
        while gap_tokens(mod.load_details()):
            if cdp_busy():
                if args.wait_cdp:
                    time.sleep(5)
                    continue
                break
            meta = json.loads(
                subprocess.check_output(
                    [sys.executable, str(args.workdir / "next_scrape_batch.py"), "10", "--gap-only"],
                    text=True,
                )
            )
            if meta.get("batch_size", 0) == 0:
                break
            subprocess.run(
                [sys.executable, str(args.workdir / "cdp_scrape_batch.py"), "10"],
                cwd=str(args.workdir),
                check=False,
            )
            sync_master(mod)
            time.sleep(1)
    finally:
        sys.argv = old_argv

    remaining = gap_tokens(mod.load_details())
    if remaining and not cdp_busy():
        fixed = asyncio.run(dom_backfill(mod, args.kind, remaining))
        print(json.dumps({"dom_backfill_fixed": fixed, "gaps_after": len(gap_tokens(mod.load_details()))}), flush=True)
    else:
        print(json.dumps({"gaps_after": len(remaining), "note": "skipped dom while cdp busy"}), flush=True)


if __name__ == "__main__":
    main()
