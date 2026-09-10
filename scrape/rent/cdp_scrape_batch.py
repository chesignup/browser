#!/usr/bin/env python3
"""Run next rent scrape batch entirely via CDP."""
from __future__ import annotations
import asyncio, json, re, subprocess, sys, urllib.request
from pathlib import Path
import websockets

sys.path.insert(0, "/root/work")
from yad2_cdp_tabs import ensure_scrape_tab, list_pages  # noqa: E402

CDP = "http://127.0.0.1:11222"
ROOT = Path("/root/work/rent")
KIND = "rent"
ARGS = [a for a in sys.argv[1:] if a != "--gap-only"]
GAP_ONLY = "--gap-only" in sys.argv
BATCH = int(ARGS[0]) if ARGS else 20


def list_pages():
    return json.loads(urllib.request.urlopen(f"{CDP}/json", timeout=5).read())


async def eval_on(page, expr: str, timeout=300):
    ws_url = re.sub(r"ws://[^/]+", "ws://127.0.0.1:11222", page["webSocketDebuggerUrl"])
    try:
        ws = await websockets.connect(ws_url, open_timeout=8, max_size=20_000_000)
    except TypeError:
        ws = await websockets.connect(ws_url, max_size=20_000_000)
    msg_id = 1
    await ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True, "awaitPromise": False},
    }))
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            data = json.loads(raw)
            if data.get("id") != msg_id:
                continue
            if "error" in data:
                raise RuntimeError(data["error"])
            result = data.get("result", {})
            if result.get("exceptionDetails"):
                raise RuntimeError(json.dumps(result["exceptionDetails"], ensure_ascii=False)[:500])
            return result.get("result", {}).get("value")
    finally:
        await ws.close()


async def pick_live_page(pages, timeout=8):
    candidates = []
    for p in pages:
        if p.get("type") != "page":
            continue
        url = p.get("url") or ""
        title = p.get("title") or ""
        if "validate.perfdrive" in url or "Captcha" in title or "Radware" in title:
            continue
        if "yad2.co.il" not in url:
            continue
        candidates.append(p)
    prefer = [p for p in candidates if "rent" in (p.get("url") or "")]
    ordered = prefer + [p for p in candidates if p not in prefer]
    last_err = None
    for p in ordered:
        try:
            val = await eval_on(p, "location.hostname", timeout=timeout)
            if val and "yad2" in str(val):
                return p
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"no live yad2 page; last_err={last_err!r}")


def build_expr(batch: int) -> tuple[dict, str]:
    nb_cmd = [sys.executable, str(ROOT / "next_scrape_batch.py"), str(batch)]
    if GAP_ONLY:
        nb_cmd.append("--gap-only")
    meta = json.loads(subprocess.check_output(nb_cmd, text=True))
    js = (ROOT / "scrape_batch.js").read_text()
    if js.startswith("/**"):
        js = js[js.find("*/") + 2:]
    js = js.replace(
        "window.__SCRAPE_LAST__ = results;\n  var ok = results.filter(function (r) { return !r.error && r.api; }).length;\n  return JSON.stringify({ ok: ok, fetched: results.length, errors: results.length - ok, results: results });",
        """window.__SCRAPE_LAST__ = results;
  var ok = results.filter(function (r) { return !r.error && r.api; }).length;
  var payload = { ok: ok, fetched: results.length, errors: results.length - ok, results: results };
  window.__SCRAPE_JSON__ = JSON.stringify(payload);
  return window.__SCRAPE_JSON__;""",
    )
    master = json.loads((ROOT / "master_listings.json").read_text())
    links = {
        m["token"]: m["link"]
        for m in master
        if m.get("token") in meta.get("tokens", []) and m.get("link")
    }
    expr = (
        "window.__SCRAPE_TOKENS__ = " + json.dumps(meta["tokens"]) + ";\n"
        + "window.__SCRAPE_LINKS__ = " + json.dumps(links) + ";\n"
        + js.strip()
    )
    return meta, expr


async def main():
    if BATCH <= 0:
        nb_cmd = [sys.executable, str(ROOT / "next_scrape_batch.py"), "0"]
        if GAP_ONLY:
            nb_cmd.append("--gap-only")
        meta = json.loads(subprocess.check_output(nb_cmd, text=True))
        print(json.dumps(meta))
        return
    meta, expr = build_expr(BATCH)
    if meta["batch_size"] == 0:
        print(json.dumps({"done": True, "pending_before": meta["pending_before"]}))
        return
    tab = await ensure_scrape_tab(KIND, navigate=False)
    pages = [p for p in list_pages() if p.get("type") == "page"]
    page = next((p for p in pages if p.get("id") == tab.get("id")), None)
    if not page:
        page = await pick_live_page(list_pages())
    elif not tab.get("live"):
        page = await pick_live_page(list_pages())
    probe = await eval_on(page, "(document.body&&document.body.innerText||'').slice(0,80)", timeout=30)
    if probe and ("Press & Hold" in probe or "Are you human" in probe or "Radware" in probe):
        print(json.dumps({"captcha": True, "probe": probe}))
        sys.exit(3)
    js = await eval_on(page, expr, timeout=300)
    if not js:
        rebuild = r"""(function(){var r=window.__SCRAPE_LAST__||[];if(!r.length)return null;var ok=r.filter(function(x){return !x.error&&x.api}).length;var payload={ok:ok,fetched:r.length,errors:r.length-ok,results:r};window.__SCRAPE_JSON__=JSON.stringify(payload);return window.__SCRAPE_JSON__;})()"""
        js = await eval_on(page, rebuild, timeout=60)
    if not js:
        raise RuntimeError("empty scrape json")
    if not isinstance(js, str):
        js = json.dumps(js)
    Path("/tmp/rent_batch_result.json").write_text(js)
    summary = json.loads(js)
    apply = subprocess.check_output(
        [sys.executable, str(ROOT / "apply_scrape_batch.py"), "/tmp/rent_batch_result.json"],
        text=True,
    )
    print(json.dumps({"batch_meta": meta, "summary": {"ok": summary.get("ok"), "fetched": summary.get("fetched"), "errors": summary.get("errors")}}))
    print(apply.strip())


if __name__ == "__main__":
    asyncio.run(main())
