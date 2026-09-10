#!/usr/bin/env python3
"""
Collect yad2 RENT feed listings via CDP (dehydratedState), same cities as sale job.

Cities / areas:
  area=1  תל אביב יפו     tel-aviv-area
  area=3  גבעתיים         tel-aviv-area  (filter city text)
  area=4  פתח תקווה       center-and-sharon
  area=78 בני ברק         center-and-sharon
  area=10 קרית אונו       center-and-sharon

Filters: minPrice=6000, whole-apartment category (/realestate/rent).
Excludes non-apartment types (חניה, מחסן, מגרשים, בניין מגורים).
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import websockets

CDP = "http://127.0.0.1:11222"
ROOT = Path("/root/work/rent")
ROOT.mkdir(parents=True, exist_ok=True)

MIN_PRICE = 6000
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
EXCLUDE_TYPES = {
    "חניה", "מחסן", "מגרשים", "בניין מגורים", "כללי",
}

EXTRACT_JS = r"""
(() => {
  const scripts = Array.from(document.querySelectorAll('script:not([src])'));
  const script = scripts.find(s => (s.textContent || '').includes('dehydratedState'));
  if (!script) {
    const body = (document.body && document.body.innerText || '').slice(0, 120);
    return { error: 'no_dehydrated', body, href: location.href, title: document.title };
  }
  let data;
  try { data = JSON.parse(script.textContent); } catch (e) {
    return { error: 'json_parse', message: String(e) };
  }
  const queries = (data.props && data.props.pageProps && data.props.pageProps.dehydratedState
    && data.props.pageProps.dehydratedState.queries) || [];
  const feedQuery = queries.find(q => {
    const k = JSON.stringify(q.queryKey || []);
    return k.includes('realestate-rent-feed') || k.includes('realestate-forsale-feed') || k.includes('forsale-feed');
  }) || queries.find(q => {
    const k = JSON.stringify(q.queryKey || []);
    return k.includes('rent-feed') || k.includes('"feed"');
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
    type: (i.additionalDetails && i.additionalDetails.property && i.additionalDetails.property.text)
      || (i.metaData && i.metaData.coverImageAlt) || '',
    rooms: i.additionalDetails && (i.additionalDetails.roomsCount != null
      ? i.additionalDetails.roomsCount
      : i.additionalDetails.rooms),
    sqm: i.additionalDetails && (i.additionalDetails.squareMeter || i.additionalDetails.sqm),
    tags: (i.tags || []).map(t => (typeof t === 'string' ? t : (t && (t.name || t.text))) ).filter(Boolean),
  })).filter(i => i.token);
  return {
    href: location.href,
    total: (d.pagination && d.pagination.total) || d.total || items.length,
    totalPages: d.pagination && d.pagination.totalPages || null,
    page: d.pagination && d.pagination.page || null,
    count: items.length,
    items,
  };
})()
"""


def list_pages():
    return json.loads(urllib.request.urlopen(f"{CDP}/json", timeout=5).read())


def open_tab(url: str):
    """Chromium here rejects GET /json/new (405); PUT works."""
    encoded = urllib.parse.quote(url, safe=":/?&=%")
    req = urllib.request.Request(f"{CDP}/json/new?{encoded}", method="PUT")
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


def pick_rent_page():
    pages = list_pages()
    for p in pages:
        if p.get("type") != "page":
            continue
        url = p.get("url") or ""
        title = p.get("title") or ""
        if "validate.perfdrive" in url or "Captcha" in title or "Radware" in title:
            continue
        if "yad2.co.il" in url and "rent" in url:
            return p
    for p in pages:
        if p.get("type") == "page" and "yad2.co.il" in (p.get("url") or ""):
            url = p.get("url") or ""
            if "validate.perfdrive" not in url:
                return p
    return None


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


async def navigate_and_extract(url: str, session: CdpSession | None = None, retries: int = 3):
    last_err = None
    own = session is None
    for attempt in range(retries):
        try:
            if own:
                page = pick_rent_page()
                if not page:
                    meta = open_tab(url)
                    time.sleep(3)
                    pages = list_pages()
                    page = next((p for p in pages if p.get("id") == meta.get("id")), None) or pick_rent_page()
                if not page:
                    raise RuntimeError("no yad2 page")
                session = CdpSession(page)
                await session.connect()
            await session.call("Page.navigate", {"url": url}, timeout=30)
            # Wait for real navigation + populated rent feed (dehydrated exists too early).
            for _ in range(40):
                probe = await session.eval("(document.body&&document.body.innerText||'').slice(0,80)", timeout=20)
                if probe and ("Press & Hold" in probe or "Are you human" in probe or "Radware" in probe):
                    raise RuntimeError(f"captcha:{probe}")
                state = await session.eval(
                    """(() => {
                      const href = location.href;
                      const ready = document.readyState;
                      const script = Array.from(document.querySelectorAll('script:not([src])'))
                        .find(s => (s.textContent||'').includes('dehydratedState'));
                      if (!script) return {href, ready, n:0};
                      try {
                        const data = JSON.parse(script.textContent);
                        const q = (data.props.pageProps.dehydratedState.queries||[])
                          .find(qq => JSON.stringify(qq.queryKey||[]).includes('realestate-rent-feed')
                                   || JSON.stringify(qq.queryKey||[]).includes('realestate-forsale-feed'));
                        const d = q && q.state && q.state.data;
                        const n = d ? ((d.private||[]).length + (d.agency||[]).length) : 0;
                        const page = d && d.pagination && d.pagination.page;
                        return {href, ready, n, page, total: d && d.pagination && d.pagination.total};
                      } catch (e) { return {href, ready, n:0, err:String(e)}; }
                    })()""",
                    timeout=30,
                )
                if (
                    state
                    and state.get("ready") == "complete"
                    and state.get("n", 0) > 0
                    and url.split("?")[0] in (state.get("href") or "")
                ):
                    # optional: page query present in href
                    break
                await asyncio.sleep(0.6)
            else:
                # one more chance even if empty (last pages)
                await asyncio.sleep(1.5)
            data = await session.eval(EXTRACT_JS, timeout=60)
            if own and session:
                await session.close()
            return data
        except Exception as e:
            last_err = e
            if own and session:
                try:
                    await session.close()
                except Exception:
                    pass
                session = None
            await asyncio.sleep(2)
    raise RuntimeError(last_err)


def keep_item(item: dict, cities: set[str]) -> bool:
    if not item.get("token"):
        return False
    city = item.get("city") or ""
    if city not in cities:
        return False
    ptype = (item.get("type") or "").strip()
    if ptype in EXCLUDE_TYPES:
        return False
    price = item.get("price") or 0
    # Keep unspecified (0) and >= min; drop below min when known
    if price and price < MIN_PRICE:
        return False
    return True


async def collect_area(area: int, session: CdpSession) -> list[dict]:
    region = AREA_REGION[area]
    cities = CITY_FILTER[area]
    collected: dict[str, dict] = {}
    page = 1
    max_pages = 80
    empty_streak = 0
    while page <= max_pages:
        url = (
            f"https://www.yad2.co.il/realestate/rent/{region}"
            f"?area={area}&minPrice={MIN_PRICE}&page={page}"
        )
        print(json.dumps({"collect": "page", "area": area, "page": page, "url": url}), flush=True)
        data = await navigate_and_extract(url, session=session)
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
            if keep_item(it, cities):
                collected[it["token"]] = it
                kept += 1
        print(json.dumps({
            "collect": "ok",
            "area": area,
            "page": page,
            "raw": len(items),
            "kept": kept,
            "unique": len(collected),
            "totalPages": data.get("totalPages"),
            "total": data.get("total"),
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
        if kept == 0 and items:
            # city filter empty — still advance a bit then stop if persistent
            empty_streak += 1
            if empty_streak >= 3:
                break
        page += 1
        time.sleep(0.8)
    return list(collected.values())


async def main():
    all_rows: dict[str, dict] = {}
    # area 3 saves per-city files via merge at end (givatayim + ramat gan)
    by_area_files = {
        1: "telaviv_rent.json",
        3: "_area3_combined.json",
        4: "petachtikva_rent.json",
        78: "bneiarak_rent.json",
        10: "kiriatono_rent.json",
    }
    page = pick_rent_page()
    if not page:
        open_tab(f"https://www.yad2.co.il/realestate/rent/tel-aviv-area?area=1&minPrice={MIN_PRICE}")
        time.sleep(3)
        page = pick_rent_page()
    if not page:
        raise RuntimeError("no live yad2 rent tab")
    session = CdpSession(page)
    await session.connect()
    try:
        for area, fname in by_area_files.items():
            rows = await collect_area(area, session)
            if area == 3:
                by_city: dict[str, list] = {}
                for r in rows:
                    by_city.setdefault(r.get("city") or "?", []).append(r)
                for city, city_rows in by_city.items():
                    slug = {"גבעתיים": "givatayim", "רמת גן": "ramatgan"}.get(city)
                    if not slug:
                        continue
                    path = ROOT / f"{slug}_rent.json"
                    path.write_text(json.dumps(city_rows, ensure_ascii=False, indent=2))
                    print(json.dumps({"saved": str(path), "city": city, "n": len(city_rows)}), flush=True)
            else:
                path = ROOT / fname
                path.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
                print(json.dumps({"saved": str(path), "n": len(rows), "area": area}), flush=True)
            for r in rows:
                all_rows[r["token"]] = r
    finally:
        await session.close()

    import importlib.util
    spec = importlib.util.spec_from_file_location("sld", ROOT / "scrape_listing_details.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    master = mod.merge_master()
    by_city = {}
    for m in master:
        by_city[m["city"]] = by_city.get(m["city"], 0) + 1
    print(json.dumps({"master": len(master), "by_city": by_city}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
