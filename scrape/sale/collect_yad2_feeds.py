#!/usr/bin/env python3
"""
Collect yad2 feed listings via CDP (dehydratedState).

Usage:
  python3 collect_yad2_feeds.py --kind sale --workdir /root/work --areas 3
  python3 collect_yad2_feeds.py --kind rent --workdir /root/work/rent --areas 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yad2_cdp_tabs import ensure_scrape_tab, list_pages  # noqa: E402

CDP = "http://127.0.0.1:11222"

CITY_FILTER = {
    1: {"תל אביב יפו"},
    3: {"גבעתיים", "רמת גן"},
    4: {"פתח תקווה"},
    78: {"בני ברק"},
    10: {"קרית אונו"},
}
AREA_REGION = {
    1: "tel-aviv-area",
    3: "tel-aviv-area",
    4: "center-and-sharon",
    78: "center-and-sharon",
    10: "center-and-sharon",
}
CITY_REGION = {
    "גבעתיים": "tel-aviv-area",
    "רמת גן": "tel-aviv-area",
    "תל אביב יפו": "tel-aviv-area",
    "פתח תקווה": "center-and-sharon",
    "בני ברק": "center-and-sharon",
    "קרית אונו": "center-and-sharon",
}
AREA_OUT = {
    1: "telaviv",
    3: None,  # split by city below
    4: "petachtikva",
    78: "bneiarak",
    10: "kiriatono",
}
CITY_OUT = {
    "גבעתיים": "givatayim",
    "רמת גן": "ramatgan",
    "תל אביב יפו": "telaviv",
    "פתח תקווה": "petachtikva",
    "בני ברק": "bneiarak",
    "קרית אונו": "kiriatono",
}
EXCLUDE_TYPES = {"חניה", "מחסן", "מגרשים", "בניין מגורים", "כללי"}

EXTRACT_JS = r"""
(() => {
  const scripts = Array.from(document.querySelectorAll('script:not([src])'));
  const script = scripts.find(s => (s.textContent || '').includes('dehydratedState'));
  if (!script) {
    return { error: 'no_dehydrated', body: (document.body && document.body.innerText || '').slice(0, 120), href: location.href };
  }
  let data;
  try { data = JSON.parse(script.textContent); } catch (e) {
    return { error: 'json_parse', message: String(e) };
  }
  const queries = (data.props && data.props.pageProps && data.props.pageProps.dehydratedState
    && data.props.pageProps.dehydratedState.queries) || [];
  const feedQuery = queries.find(q => {
    const k = JSON.stringify(q.queryKey || []);
    return k.includes('realestate-rent-feed') || k.includes('realestate-forsale-feed');
  });
  if (!feedQuery || !feedQuery.state || !feedQuery.state.data) {
    return { error: 'no_feed', keys: queries.map(q => q.queryKey).slice(0, 8), href: location.href };
  }
  const d = feedQuery.state.data;
  const all = [...(d.private || []), ...(d.agency || []), ...(d.platinum || []), ...(d.booster || [])];
  const items = all.map(i => ({
    token: i.token,
    city: i.address && i.address.city && i.address.city.text,
    neighborhood: i.address && i.address.neighborhood && i.address.neighborhood.text,
    street: ((i.address && i.address.street && i.address.street.text) || '') + ' ' + ((i.address && i.address.house && i.address.house.number) || ''),
    floor: i.additionalDetails && i.additionalDetails.floor != null ? i.additionalDetails.floor
      : (i.address && i.address.house && i.address.house.floor),
    price: typeof i.price === 'number' ? i.price : (i.price && i.price.replace ? Number(String(i.price).replace(/[^\d]/g,'')) : 0) || 0,
    type: (i.additionalDetails && i.additionalDetails.property && i.additionalDetails.property.text) || '',
    rooms: i.additionalDetails && (i.additionalDetails.roomsCount != null ? i.additionalDetails.roomsCount : i.additionalDetails.rooms),
    sqm: i.additionalDetails && (i.additionalDetails.squareMeter || i.additionalDetails.sqm),
    tags: (i.tags || []).map(t => (typeof t === 'string' ? t : (t && (t.name || t.text)))).filter(Boolean),
  })).filter(i => i.token);
  return {
    href: location.href,
    total: (d.pagination && d.pagination.total) || items.length,
    totalPages: d.pagination && d.pagination.totalPages || null,
    count: items.length,
    items,
  };
})()
"""


def list_pages():
    return json.loads(urllib.request.urlopen(f"{CDP}/json", timeout=5).read())


class CdpSession:
    def __init__(self, page):
        self.page = page
        self.ws = None
        self._n = 0

    async def connect(self):
        ws_url = re.sub(r"ws://[^/]+", "ws://127.0.0.1:11222", self.page["webSocketDebuggerUrl"])
        try:
            self.ws = await websockets.connect(ws_url, open_timeout=8, max_size=20_000_000)
        except TypeError:
            self.ws = await websockets.connect(ws_url, max_size=20_000_000)

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def call(self, method: str, params: dict | None = None, timeout: float = 60):
        self._n += 1
        nid = self._n
        await self.ws.send(json.dumps({"id": nid, "method": method, "params": params or {}}))
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            data = json.loads(raw)
            if data.get("id") != nid:
                continue
            if "error" in data:
                raise RuntimeError(data["error"])
            return data.get("result", {})

    async def eval(self, expr: str, timeout: float = 60):
        result = await self.call(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": False},
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            raise RuntimeError(json.dumps(result["exceptionDetails"], ensure_ascii=False)[:400])
        return result.get("result", {}).get("value")


async def navigate_and_extract(url: str, session: CdpSession, feed_needle: str):
    await session.call("Page.navigate", {"url": url}, timeout=30)
    for _ in range(40):
        probe = await session.eval("(document.body&&document.body.innerText||'').slice(0,80)", timeout=20)
        if probe and ("Press & Hold" in probe or "Are you human" in probe or "Radware" in probe):
            raise RuntimeError(f"captcha:{probe}")
        state = await session.eval(
            f"""(() => {{
              const ready = document.readyState;
              const script = Array.from(document.querySelectorAll('script:not([src])'))
                .find(s => (s.textContent||'').includes('dehydratedState'));
              if (!script) return {{ready, n:0}};
              try {{
                const data = JSON.parse(script.textContent);
                const q = (data.props.pageProps.dehydratedState.queries||[])
                  .find(qq => JSON.stringify(qq.queryKey||[]).includes('{feed_needle}'));
                const d = q && q.state && q.state.data;
                const n = d ? ((d.private||[]).length + (d.agency||[]).length) : 0;
                return {{ready, n, totalPages: d && d.pagination && d.pagination.totalPages}};
              }} catch (e) {{ return {{ready, n:0}}; }}
            }})()""",
            timeout=30,
        )
        if state and state.get("ready") == "complete" and state.get("n", 0) > 0:
            break
        await asyncio.sleep(0.6)
    else:
        await asyncio.sleep(1.5)
    return await session.eval(EXTRACT_JS, timeout=60)


def keep_item(item: dict, cities: set[str], kind: str, min_price: int, max_price: int | None) -> bool:
    if not item.get("token"):
        return False
    if (item.get("city") or "") not in cities:
        return False
    if (item.get("type") or "").strip() in EXCLUDE_TYPES:
        return False
    price = item.get("price") or 0
    if kind == "rent" and price and price < min_price:
        return False
    if kind == "sale" and max_price and price and price > max_price:
        return False
    return True


def build_url(kind: str, region: str, area: int, page: int, min_price: int, max_price: int | None) -> str:
    base = f"https://www.yad2.co.il/realestate/{'rent' if kind == 'rent' else 'forsale'}/{region}"
    if kind == "rent":
        return f"{base}?area={area}&minPrice={min_price}&page={page}"
    return f"{base}?area={area}&minPrice=0&maxPrice={max_price}&page={page}"


async def collect_area(area: int, session: CdpSession, kind: str, min_price: int, max_price: int | None) -> list[dict]:
    region = AREA_REGION[area]
    cities = CITY_FILTER[area]
    feed_needle = "realestate-rent-feed" if kind == "rent" else "realestate-forsale-feed"
    collected: dict[str, dict] = {}
    page = 1
    empty_streak = 0
    while page <= 120:
        url = build_url(kind, region, area, page, min_price, max_price)
        print(json.dumps({"collect": "page", "kind": kind, "area": area, "page": page}), flush=True)
        data = await navigate_and_extract(url, session, feed_needle)
        if not data or data.get("error"):
            print(json.dumps({"collect": "error", "area": area, "page": page, "data": data}), flush=True)
            empty_streak += 1
            if empty_streak >= 2:
                break
            page += 1
            continue
        items = data.get("items") or []
        kept = 0
        for it in items:
            if keep_item(it, cities, kind, min_price, max_price):
                collected[it["token"]] = it
                kept += 1
        print(json.dumps({
            "collect": "ok", "kind": kind, "area": area, "page": page,
            "raw": len(items), "kept": kept, "unique": len(collected),
            "totalPages": data.get("totalPages"), "total": data.get("total"),
        }), flush=True)
        if not items:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
        total_pages = data.get("totalPages")
        if total_pages and page >= int(total_pages):
            break
        page += 1
        time.sleep(0.7)
    return list(collected.values())


def save_by_city(workdir: Path, kind: str, rows: list[dict]) -> dict[str, int]:
    suffix = "_rent.json" if kind == "rent" else "_all.json"
    by_city: dict[str, list] = {}
    for r in rows:
        city = r.get("city") or "?"
        by_city.setdefault(city, []).append(r)
    counts = {}
    for city, city_rows in by_city.items():
        slug = CITY_OUT.get(city)
        if not slug:
            continue
        path = workdir / f"{slug}{suffix}"
        path.write_text(json.dumps(city_rows, ensure_ascii=False, indent=2))
        counts[city] = len(city_rows)
        print(json.dumps({"saved": str(path), "city": city, "n": len(city_rows)}), flush=True)
    return counts


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["sale", "rent"], required=True)
    ap.add_argument("--workdir", type=Path, required=True)
    ap.add_argument("--areas", default="1,3,4,78,10", help="comma-separated area codes")
    ap.add_argument("--wait-minutes", type=int, default=0, help="poll until a live yad2 tab exists")
    args = ap.parse_args()
    workdir = args.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    areas = [int(x.strip()) for x in args.areas.split(",") if x.strip()]
    kind = args.kind
    min_price = 6000 if kind == "rent" else 0
    max_price = None if kind == "rent" else 2_500_000

    deadline = time.time() + max(0, args.wait_minutes) * 60
    page = None
    first = True
    while not page:
        info = await ensure_scrape_tab(kind, navigate=first)
        first = False
        pages = [p for p in list_pages() if p.get("type") == "page"]
        page = next((p for p in pages if p.get("id") == info.get("id")), None)
        if page and info.get("live") and not info.get("captcha"):
            print(json.dumps({"collect": "tab_ready", **info}), flush=True)
            break
        page = None
        if time.time() >= deadline:
            raise RuntimeError(
                "no live yad2 tab (captcha?) — clear at http://100.92.122.70:6081/ and retry"
            )
        print(json.dumps({
            "collect": "waiting_tab",
            "kind": kind,
            "viewer": "http://100.92.122.70:6081/",
            "tabs": info.get("remaining"),
            "captcha": info.get("captcha"),
        }), flush=True)
        time.sleep(15)
    session = CdpSession(page)
    await session.connect()
    all_rows: dict[str, dict] = {}
    try:
        for area in areas:
            for row in await collect_area(area, session, kind, min_price, max_price):
                all_rows[row["token"]] = row
    finally:
        await session.close()

    save_by_city(workdir, kind, list(all_rows.values()))
    import importlib.util
    spec = importlib.util.spec_from_file_location("sld", workdir / "scrape_listing_details.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    master = mod.merge_master()
    by_city = {}
    for m in master:
        by_city[m["city"]] = by_city.get(m["city"], 0) + 1
    print(json.dumps({"kind": kind, "master": len(master), "by_city": by_city}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
