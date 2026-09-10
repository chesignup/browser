#!/usr/bin/env python3
"""Single-tab CDP hygiene for yad2 scrape workers."""
from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

CDP = "http://127.0.0.1:11222"
STATE_PATH = Path("/tmp/yad2_scrape_tab.json")

KIND_URL = {
    "rent": "https://www.yad2.co.il/realestate/rent",
    "sale": "https://www.yad2.co.il/realestate/forsale",
    "forsale": "https://www.yad2.co.il/realestate/forsale",
}


def list_pages() -> list[dict]:
    return [p for p in json.loads(urllib.request.urlopen(f"{CDP}/json", timeout=8).read()) if p.get("type") == "page"]


def is_captcha_page(p: dict) -> bool:
    url = p.get("url") or ""
    title = p.get("title") or ""
    return (
        "validate.perfdrive" in url
        or "Captcha" in title
        or "Radware" in title
        or "Press & Hold" in title
        or title.startswith("400 Bad Request")
    )


def is_scrape_page(p: dict, kind: str | None = None) -> bool:
    url = p.get("url") or ""
    if "yad2.co.il/realestate" not in url:
        return False
    if kind == "rent":
        return "/rent" in url
    if kind in ("sale", "forsale"):
        return "/forsale" in url
    return True


def close_page(page_id: str) -> bool:
    try:
        urllib.request.urlopen(f"{CDP}/json/close/{page_id}", timeout=5).read()
        return True
    except Exception:
        return False


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {}


def save_state(page_id: str, kind: str, url: str = "") -> None:
    STATE_PATH.write_text(json.dumps({"id": page_id, "kind": kind, "url": url}, indent=2))


def open_tab(url: str) -> dict:
    encoded = urllib.parse.quote(url, safe=":/?&=%")
    req = urllib.request.Request(f"{CDP}/json/new?{encoded}", method="PUT")
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


async def _eval(page: dict, expr: str, timeout: float = 8):
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


async def navigate_page(page: dict, url: str, timeout: float = 15) -> None:
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
    await asyncio.sleep(1.5)


async def is_live(page: dict) -> bool:
    try:
        host = await _eval(page, "location.hostname", timeout=6)
        return bool(host and "yad2" in str(host))
    except Exception:
        return False


def close_all_except(keep_id: str | None) -> int:
    closed = 0
    for p in list_pages():
        pid = p.get("id")
        if not pid or pid == keep_id:
            continue
        if close_page(pid):
            closed += 1
    return closed


def prune_tabs(keep_id: str | None = None, kind: str | None = None) -> dict:
    """Close every tab except keep_id (or best scrape tab for kind). Returns summary."""
    pages = list_pages()
    if keep_id and any(p.get("id") == keep_id for p in pages):
        keeper = keep_id
    else:
        st = load_state()
        keeper = st.get("id") if st.get("id") in {p.get("id") for p in pages} else None
    if not keeper:
        for p in pages:
            if is_captcha_page(p):
                continue
            if kind and is_scrape_page(p, kind):
                keeper = p["id"]
                break
        if not keeper:
            for p in pages:
                if not is_captcha_page(p) and "google.com" not in (p.get("url") or ""):
                    keeper = p["id"]
                    break
    closed = close_all_except(keeper)
    remaining = len(list_pages())
    return {"kept": keeper, "closed": closed, "remaining": remaining}


async def ensure_scrape_tab(kind: str = "rent", navigate: bool = True) -> dict:
    """
    Exactly one browser tab for scraping. Reuse saved tab; navigate in-place;
    never leave a pile of captcha tabs open.
    """
    kind = "sale" if kind == "forsale" else kind
    url = KIND_URL.get(kind, KIND_URL["rent"])
    pages = list_pages()
    by_id = {p["id"]: p for p in pages if p.get("id")}

    page = None
    st = load_state()
    if st.get("id") in by_id:
        page = by_id[st["id"]]

    if page is None:
        for p in pages:
            if is_captcha_page(p):
                continue
            if is_scrape_page(p, kind):
                page = p
                break

    if page is None:
        for p in pages:
            if not is_captcha_page(p) and "google.com" not in (p.get("url") or ""):
                page = p
                break

    if page is None:
        page = open_tab(url)
        time.sleep(2)
        pages = list_pages()
        by_id = {p["id"]: p for p in pages if p.get("id")}
        page = by_id.get(page.get("id"), page)

    keep_id = page["id"]
    closed = close_all_except(keep_id)

    if navigate:
        try:
            await navigate_page(page, url)
        except Exception:
            pass

    pages = list_pages()
    page = next((p for p in pages if p.get("id") == keep_id), page)
    save_state(keep_id, kind, page.get("url") or url)
    live = await is_live(page)
    return {
        "id": keep_id,
        "url": page.get("url"),
        "title": page.get("title"),
        "captcha": is_captcha_page(page),
        "live": live,
        "closed": closed,
        "remaining": len(list_pages()),
    }


def ensure_scrape_tab_sync(kind: str = "rent", navigate: bool = True) -> dict:
    return asyncio.run(ensure_scrape_tab(kind, navigate=navigate))


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "prune"
    if cmd == "prune":
        kind = sys.argv[2] if len(sys.argv) > 2 else None
        print(json.dumps(prune_tabs(kind=kind), indent=2))
    elif cmd == "close-all":
        n = close_all_except(None)
        print(json.dumps({"closed": n, "remaining": len(list_pages())}))
    elif cmd == "ensure":
        kind = sys.argv[2] if len(sys.argv) > 2 else "rent"
        print(json.dumps(ensure_scrape_tab_sync(kind), indent=2))
    elif cmd == "status":
        st = load_state()
        pages = list_pages()
        print(json.dumps({
            "state": st,
            "tabs": len(pages),
            "captcha_tabs": sum(1 for p in pages if is_captcha_page(p)),
        }, indent=2))
    else:
        print("usage: yad2_cdp_tabs.py [prune|close-all|ensure|status] [rent|sale]", file=sys.stderr)
        sys.exit(2)
