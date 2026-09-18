#!/usr/bin/env python3
"""Deterministic Facebook Marketplace Scraper via Chromebox CDP.

Connects to the running Chrome instance (which holds an active, logged-in Facebook session),
searches Facebook Marketplace for any query (e.g. 'macbook', 'apartments', 'iphone'),
scrolls to collect item cards, and then visits listings to extract complete details:
- title, price, currency
- full description
- condition (e.g. משומש - כמו חדש)
- city / location
- post date / time
- attributes (product line, specs)
- latitude / longitude (when embedded)
- link, item ID, scrape timestamps
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime
import json
import logging
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fb_marketplace")

DEFAULT_CDP_BASE = os.environ.get("CDP_BASE", "http://127.0.0.1:11222")


class CDPConnection:
    def __init__(self, ws: aiohttp.ClientWebSocketResponse):
        self.ws = ws
        self._id = 0
        self._waiters: Dict[int, asyncio.Future] = {}
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        try:
            async for m in self.ws:
                if m.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(m.data)
                        mid = data.get("id")
                        if mid and mid in self._waiters:
                            fut = self._waiters.pop(mid)
                            if not fut.done():
                                fut.set_result(data)
                    except Exception as e:
                        log.debug("JSON parse issue in message: %s", e)
                elif m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    log.warning("CDP WebSocket closed or error: %s", m)
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning("CDP reader loop terminated: %s", e)

    async def call(self, method: str, params: Optional[dict] = None, timeout: float = 12.0) -> Any:
        if self.ws.closed:
            raise ConnectionError("CDP WebSocket is closed")
        if self._reader.done() and not self._reader.cancelled():
            exc = self._reader.exception()
            if exc:
                raise ConnectionError(f"CDP reader task failed: {exc}")

        self._id += 1
        mid = self._id
        fut = asyncio.get_event_loop().create_future()
        self._waiters[mid] = fut
        await self.ws.send_json({"id": mid, "method": method, "params": params or {}})
        try:
            data = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._waiters.pop(mid, None)
            raise TimeoutError(f"CDP call {method} (id={mid}) timed out after {timeout}s")

        if "error" in data:
            raise RuntimeError(data["error"])
        res = data.get("result", {})
        if "result" in res and "value" in res["result"]:
            return res["result"]["value"]
        return res

    async def close(self):
        self._reader.cancel()
        if not self.ws.closed:
            await self.ws.close()


async def get_or_create_page(session: aiohttp.ClientSession, cdp_base: str) -> dict:
    """Find an existing Facebook tab, else open a *new* tab (never steal Yad2)."""
    with urllib.request.urlopen(f"{cdp_base}/json/list", timeout=8) as r:
        targets = json.loads(r.read().decode())
    pages = [t for t in targets if t.get("type") == "page"]
    fb_page = next((p for p in pages if "facebook.com" in (p.get("url") or "")), None)
    if fb_page:
        return fb_page

    # Prefer Target.createTarget via browser websocket — /json/new often 500 via proxy.
    with urllib.request.urlopen(f"{cdp_base}/json/version", timeout=8) as r:
        ver = json.loads(r.read().decode())
    browser_ws = ver.get("webSocketDebuggerUrl") or ""
    browser_ws = re.sub(r"ws://[^/]+", cdp_base.replace("http://", "ws://"), browser_ws)
    try:
        async with session.ws_connect(browser_ws, max_msg_size=5_000_000) as ws:
            await ws.send_json(
                {
                    "id": 1,
                    "method": "Target.createTarget",
                    "params": {"url": "about:blank"},
                }
            )
            target_id = None
            while True:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=20)
                if msg.get("id") == 1:
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    target_id = (msg.get("result") or {}).get("targetId")
                    break
        if target_id:
            await asyncio.sleep(0.8)
            with urllib.request.urlopen(f"{cdp_base}/json/list", timeout=8) as r:
                targets = json.loads(r.read().decode())
            hit = next((t for t in targets if t.get("id") == target_id), None)
            if hit:
                return hit
    except Exception as e:
        log.warning("Target.createTarget failed (%s); trying /json/new", e)

    try:
        with urllib.request.urlopen(f"{cdp_base}/json/new?about:blank", timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        raise RuntimeError(
            "Could not open a dedicated Facebook Marketplace tab without "
            f"stealing an existing page: {e}"
        ) from e


JS_EXTRACT_CARDS = r"""
(() => {
  const main = document.querySelector('[role="main"]') || document.body;
  const links = Array.from(main.querySelectorAll('a[href*="/marketplace/item/"]'));
  const items = [];
  const seen = new Set();

  for (const a of links) {
    const m = a.href.match(/\/marketplace\/item\/(\d+)/);
    if (!m) continue;
    const id = m[1];
    if (seen.has(id)) continue;
    seen.add(id);

    const text = a.innerText.trim();
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);

    const isPrice = (s) => /^[0-9,]+\s*₪|₪\s*[0-9,]+|^₪[0-9,]+/.test(s);
    const priceIndices = [];
    lines.forEach((l, idx) => {
      if (isPrice(l)) priceIndices.push(idx);
    });

    let priceNum = null;
    let priceLine = '';
    let title = '';
    let city = '';

    if (priceIndices.length > 0) {
      priceLine = lines[priceIndices[0]];
      const mNum = priceLine.match(/[0-9,]+/);
      priceNum = mNum ? parseInt(mNum[0].replace(/,/g, ''), 10) : null;

      const lastPriceIdx = priceIndices[priceIndices.length - 1];
      if (lastPriceIdx + 1 < lines.length) {
        title = lines[lastPriceIdx + 1];
      }
      if (lastPriceIdx + 2 < lines.length) {
        city = lines[lastPriceIdx + 2];
      }
    } else {
      title = lines.find(l => l.length > 5) || '';
    }

    const img = a.querySelector('img');
    const imgSrc = img ? (img.currentSrc || img.src || '') : '';

    items.push({
      id: id,
      title: title,
      price: priceNum,
      price_raw: priceLine,
      city: city,
      link: 'https://www.facebook.com/marketplace/item/' + id + '/',
      image: imgSrc,
      raw_lines: lines
    });
  }

  return items;
})()
"""

JS_EXTRACT_ITEM_DETAILS = r"""
(() => {
  const main = document.querySelector('[role="main"]') || document.body;
  const h1 = main.querySelector('h1');
  const title = h1 ? h1.innerText.trim() : '';

  const fullText = main.innerText;
  const lines = fullText.split('\n').map(l => l.trim()).filter(Boolean);

  // Price line on item page: short line under title with ₪ and numbers
  const priceLine = lines.find(l => l.length < 30 && (/^[0-9,]+\s*₪|₪\s*[0-9,]+|^₪[0-9,]+/.test(l) || (/₪/.test(l) && /[0-9]/.test(l)))) || '';
  let price = null;
  if (priceLine) {
    const mNums = priceLine.match(/[0-9,]+/g);
    if (mNums && mNums.length > 0) {
      price = parseInt(mNums[0].replace(/,/g, ''), 10);
    }
  }

  // Posted & City
  const postedLine = lines.find(l => l.includes('פורסם') || l.includes('Listed')) || '';
  let city = '';
  if (postedLine) {
    const m = postedLine.match(/ב:\s*([^,·]+)/) || postedLine.match(/in\s*([^,·]+)/);
    if (m) city = m[1].trim();
  }
  if (!city) {
    const locLine = lines.find(l => l.includes('משוער') || l.includes('approximate'));
    if (locLine) city = locLine.split('·')[0].split(',')[0].trim();
  }

  // Condition
  let condition = '';
  const condIdx = lines.findIndex(l => l === 'מצב' || l === 'Condition');
  if (condIdx !== -1 && condIdx + 1 < lines.length) {
    condition = lines[condIdx + 1];
  }

  // Attributes map
  const attrs = {};
  const attrKeys = [
    'קו מוצרים', 'סוג מחשב נייד', 'מותג', 'דגם', 'מעבד', 'גודל מסך',
    'Brand', 'Model', 'Screen Size', 'Processor', 'RAM', 'Storage'
  ];
  for (let i = 0; i < lines.length - 1; i++) {
    const cleanKey = lines[i].replace(/[\u200e\u200f]/g, '').trim();
    if (attrKeys.includes(cleanKey)) {
      attrs[cleanKey] = lines[i + 1].replace(/[\u200e\u200f]/g, '').trim();
    }
  }

  // Description
  let description = '';
  const detailsIdx = lines.findIndex(l => l === 'פרטים' || l === 'Details');
  if (detailsIdx !== -1) {
    const dLines = [];
    for (let i = detailsIdx + 1; i < lines.length; i++) {
      const l = lines[i];
      const cleanL = l.replace(/[\u200e\u200f]/g, '').trim();
      if (attrKeys.includes(cleanL) || cleanL === 'מצב' || cleanL === 'Condition') {
        i++; // skip label and value
        continue;
      }
      if (l.includes('המיקום הוא משוער') || l.includes('Location is approximate') ||
          l.includes('פרטי המוכר') || l.includes('Seller information') ||
          l.includes('דיווח על הפריט') || l.includes('Report item')) {
        break;
      }
      dLines.push(l);
    }
    description = dLines.join('\n').trim();
  }

  // Coordinates from inline JSON scripts
  let lat = null, lon = null;
  for (const s of Array.from(document.querySelectorAll('script'))) {
    const t = s.innerText;
    if (t.includes('"latitude":') && t.includes('"longitude":')) {
      const mLat = t.match(/"latitude":\s*([\d\.-]+)/);
      const mLon = t.match(/"longitude":\s*([\d\.-]+)/);
      if (mLat && mLon) {
        lat = parseFloat(mLat[1]);
        lon = parseFloat(mLon[1]);
        break;
      }
    }
  }

  // Sold / unavailable signals (Hebrew Marketplace badge "נמכר" is authoritative)
  const head = ((h1 && h1.innerText) || title || '') + '\n' + lines.slice(0, 8).join('\n');
  const soldBadge = /נמכר\s*[·•|]/.test(title) || /^נמכר\b/.test(title.trim());
  const sold = soldBadge
    || /no longer available|isn['\u2019]?t available|listing not found|page not found|this listing is sold/i.test(head);
  const gone = sold || /content isn['\u2019]?t available|לא זמין יותר|המודעה לא/i.test(fullText.slice(0, 1500));
  const path = location.pathname || '';
  const itemId = (path.match(/\/marketplace\/item\/(\d+)/) || [])[1] || '';
  const isItemPage = !!itemId;
  const isSearchPage = /\/marketplace\/search\//.test(path)
    || (!isItemPage && /\/marketplace\//.test(path) && !/\/item\//.test(path));

  return {
    id: itemId,
    title: title.replace(/^נמכר\s*[·•|]\s*/, '').trim(),
    price,
    price_raw: priceLine,
    condition,
    city,
    posted: postedLine,
    attributes: attrs,
    description,
    latitude: lat,
    longitude: lon,
    link: window.location.href.split('?')[0],
    sold: !!sold,
    soldBadge: !!soldBadge,
    gone: !!gone,
    isItemPage,
    isSearchPage,
    href: location.href,
  };
})()
"""


PROPERTY_CATEGORIES = {
    "propertyrentals": "propertyrentals",
    "rent": "propertyrentals",
    "rental": "propertyrentals",
    "השכרה": "propertyrentals",
    "propertysales": "propertysales",
    "sale": "propertysales",
    "forsale": "propertysales",
    "מכירה": "propertysales",
}


def marketplace_search_url(query: str, category: str | None = None) -> str:
    """Build Marketplace URL for goods search or property category feeds."""
    cat = (category or "").strip().lower()
    cat = PROPERTY_CATEGORIES.get(cat, cat)
    q = urllib.parse.quote(query) if query else ""
    if cat in ("propertyrentals", "propertysales"):
        base = f"https://www.facebook.com/marketplace/category/{cat}"
        return f"{base}?query={q}" if q else base
    if cat and cat not in ("search", "all", ""):
        base = f"https://www.facebook.com/marketplace/category/{urllib.parse.quote(cat)}"
        return f"{base}?query={q}" if q else base
    return f"https://www.facebook.com/marketplace/search/?query={q or urllib.parse.quote('macbook')}"


def infer_listing_type(query: str, category: str | None) -> str:
    cat = PROPERTY_CATEGORIES.get((category or "").strip().lower(), (category or "").strip().lower())
    if cat == "propertyrentals":
        return "rent"
    if cat == "propertysales":
        return "sale"
    if re.search(r"mac|מקבוק", query or "", re.I):
        return "macbook"
    return "marketplace_item"


def enrich_specs(item: dict) -> dict:
    text = f"{item.get('title', '')} {item.get('description', '')}"
    title = item.get("title", "")

    # Price sanity check
    if isinstance(item.get("price"), (int, float)) and item["price"] > 50000:
        digits = re.findall(r"[1-9][0-9]{2,4}", str(item["price"]))
        if digits:
            item["price"] = int(digits[0])

    # Title cleanup if it was accidentally set to price
    if re.match(r"^[0-9,]+\s*₪", item.get("title", "").strip()):
        d_lines = [l.strip() for l in item.get("description", "").split("\n") if l.strip() and not re.match(r"^[0-9,]+\s*₪", l.strip())]
        if d_lines:
            item["title"] = d_lines[0][:50]
        elif item.get("series"):
            item["title"] = f"{item['series']} {item.get('processor', '')}".strip()

    # Series
    if not item.get("series"):
        if re.search(r"\bpro\b|\bפרו\b", title, re.I):
            item["series"] = "MacBook Pro"
        elif re.search(r"\bair\b|\bאייר\b", title, re.I):
            item["series"] = "MacBook Air"
        elif re.search(r"\bpro\b|\bפרו\b", text, re.I):
            item["series"] = "MacBook Pro"
        elif re.search(r"\bair\b|\bמקבוק\s+אייר\b", text, re.I):
            item["series"] = "MacBook Air"
        elif "mac" in item.get("title", "").lower():
            item["series"] = "MacBook"

    # Manufacturer
    if not item.get("manufacturer") and "mac" in text.lower():
        item["manufacturer"] = "Apple"

    # Processor
    if not item.get("processor"):
        m_proc = re.search(r"\b(M[1-4]\s*(?:Max|Pro|Ultra)?|i[3579](?:-\d+)?)\b", text, re.I)
        if m_proc:
            item["processor"] = m_proc.group(1).strip()

    # RAM
    if not item.get("ram"):
        m_ram = re.search(r"\b(\d{1,2})\s*(?:GB|ג['״]?יגה|גב)\s*(?:RAM|ראם|זכרון|זיכרון)?\b", text, re.I)
        if m_ram:
            item["ram"] = f"{m_ram.group(1)}GB"

    # Storage
    if not item.get("storage"):
        m_ssd = re.search(
            r"\b(\d{3,4}\s*(?:GB|ג['״]?יגה)|[12]\s*TB|[12]\s*טרה)\s*(?:SSD|אחסון|דיסק|כונן)?\b",
            text,
            re.I,
        )
        if m_ssd:
            s = m_ssd.group(1).upper().replace(" ", "").replace("ג'יגה", "GB").replace("גיגה", "GB")
            item["storage"] = s

    # Screen size
    if not item.get("screen_size"):
        m_screen = re.search(r'(\d{2}(?:\.\d)?)\s*(?:"|״|אינץ)', text)
        if m_screen:
            item["screen_size"] = m_screen.group(1)

    return item


async def _open_item_details(cdp: CDPConnection, item_id: str, item_url: str, item_delay: float) -> Optional[dict]:
    """Open Marketplace item page; recover when FB redirects to search/results."""
    candidates = [
        item_url,
        f"https://www.facebook.com/marketplace/item/{item_id}/",
        f"https://www.facebook.com/marketplace/item/{item_id}",
        f"https://www.facebook.com/marketplace/item/{item_id}/?ref=search",
    ]
    details = None
    for url in candidates:
        try:
            await cdp.call("Page.navigate", {"url": url}, timeout=10.0)
            await asyncio.sleep(item_delay)
            details_raw = await cdp.call(
                "Runtime.evaluate",
                {"expression": JS_EXTRACT_ITEM_DETAILS, "returnByValue": True},
                timeout=10.0,
            )
            if not isinstance(details_raw, dict) or details_raw.get("subtype"):
                continue
            if details_raw.get("isSearchPage") or not details_raw.get("isItemPage"):
                # Try clicking the card for this id if present on the results page
                click = f"""(() => {{
                  const a = Array.from(document.querySelectorAll('a[href*="/marketplace/item/{item_id}"]'))[0];
                  if (a) {{ a.click(); return true; }}
                  return false;
                }})()"""
                clicked = await cdp.call("Runtime.evaluate", {"expression": click, "returnByValue": True})
                if clicked:
                    await asyncio.sleep(item_delay)
                    details_raw = await cdp.call(
                        "Runtime.evaluate",
                        {"expression": JS_EXTRACT_ITEM_DETAILS, "returnByValue": True},
                        timeout=10.0,
                    )
            if isinstance(details_raw, dict) and details_raw.get("isItemPage"):
                return details_raw
            details = details_raw if isinstance(details_raw, dict) else details
        except Exception as err:
            log.warning("  navigate/extract %s via %s failed: %s", item_id, url, err)
    return details


async def run_marketplace_scrape(
    query: str,
    output_dir: Path,
    max_items: int = 50,
    max_scrolls: int = 8,
    item_delay: float = 2.0,
    cdp_base: str = DEFAULT_CDP_BASE,
    category: str | None = None,
) -> List[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    listing_type = infer_listing_type(query, category)
    slug_bits = [category or "", query or listing_type]
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", "_".join(slug_bits)).strip("_").lower() or "items"

    async with aiohttp.ClientSession() as http_session:
        target = await get_or_create_page(http_session, cdp_base)
        ws_url = target["webSocketDebuggerUrl"]
        log.info("Connecting to Chrome CDP page: %s (%s)", target.get("id"), ws_url)

        async with http_session.ws_connect(ws_url, max_msg_size=0) as ws:
            cdp = CDPConnection(ws)
            try:
                # 1. Search / category feed
                search_url = marketplace_search_url(query, category)
                log.info("Navigating to Facebook Marketplace: %s", search_url)
                await cdp.call("Page.navigate", {"url": search_url})
                await asyncio.sleep(4.0)

                # 2. Scroll to load cards
                collected_cards: Dict[str, dict] = {}
                log.info("Collecting feed cards (up to %d scrolls, target: %d items)...", max_scrolls, max_items)
                for s in range(max_scrolls):
                    cards = await cdp.call("Runtime.evaluate", {"expression": JS_EXTRACT_CARDS, "returnByValue": True})
                    if isinstance(cards, list):
                        for c in cards:
                            cid = c.get("id")
                            if cid and cid not in collected_cards:
                                collected_cards[cid] = c
                    log.info("  Scroll %d/%d: %d unique cards collected so far", s + 1, max_scrolls, len(collected_cards))
                    if len(collected_cards) >= max_items:
                        break
                    await cdp.call("Runtime.evaluate", {"expression": "window.scrollTo(0, document.body.scrollHeight)"})
                    await asyncio.sleep(2.0)

                feed_list = list(collected_cards.values())[:max_items]
                feed_path = output_dir / f"facebook_{slug}_feed.json"
                feed_path.write_text(json.dumps(feed_list, ensure_ascii=False, indent=2), encoding="utf-8")
                log.info("Saved %d feed items to %s", len(feed_list), feed_path)

                # 3. Visit each item to extract complete details
                detailed_records: List[dict] = []
                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                log.info("Extracting full details for %d listings...", len(feed_list))

                for idx, feed_item in enumerate(feed_list):
                    item_id = feed_item["id"]
                    item_url = feed_item["link"]
                    log.info("[%d/%d] Fetching item %s: %s", idx + 1, len(feed_list), item_id, feed_item.get("title", "")[:40])

                    details = await _open_item_details(cdp, item_id, item_url, item_delay)
                    if details and details.get("isSearchPage") and not details.get("isItemPage"):
                        log.warning("  Item %s: still on search/results after recovery — skipping detail", item_id)

                    sold = bool(details and details.get("isItemPage") and (details.get("sold") or details.get("gone")))
                    rec = {
                        "listing_id": item_id,
                        "token": item_id,
                        "origin": "facebook",
                        "listing_type": listing_type,
                        "link": item_url,
                        "title": (details and details.get("title")) or feed_item.get("title") or "",
                        "price": (details and details.get("price")) if (details and details.get("price") is not None) else feed_item.get("price"),
                        "price_raw": (details and details.get("price_raw")) or feed_item.get("price_raw") or "",
                        "city": (details and details.get("city")) or feed_item.get("city") or "",
                        "condition": (details and details.get("condition")) or "",
                        "description": (details and details.get("description")) or "",
                        "date_advertised": (details and details.get("posted")) or "",
                        "date_last_seen_active": now_iso if not sold else None,
                        "listing_status": "assumed_sold" if sold else "active",
                        "assumed_sold_reason": (
                            "facebook_sold_badge" if details and details.get("sold") else "detail_page_gone"
                        ) if sold else None,
                        "latitude": details.get("latitude") if details else None,
                        "longitude": details.get("longitude") if details else None,
                        "series": (details and details.get("attributes", {}).get("קו מוצרים")) or "",
                        "manufacturer": "Apple" if listing_type == "macbook" else "",
                        "processor": (details and details.get("attributes", {}).get("מעבד")) or "",
                        "ram": (details and details.get("attributes", {}).get("RAM")) or "",
                        "storage": (details and details.get("attributes", {}).get("Storage")) or "",
                        "screen_size": (details and details.get("attributes", {}).get("גודל מסך")) or "",
                        "views": None,
                        "ad_number": None,
                        "error": None if (details and details.get("isItemPage")) else "facebook_redirect_non_item",
                        "gone": sold,
                        "category": category or "",
                    }
                    if sold:
                        # Keep last real active sighting; do not refresh last_seen on sold page
                        rec.pop("date_last_seen_active", None)
                    rec = enrich_specs(rec)
                    detailed_records.append(rec)

                    # Incremental save every 2 items or on completion
                    if (idx + 1) % 2 == 0 or idx == len(feed_list) - 1:
                        _save_outputs(detailed_records, output_dir, slug)

                log.info("Successfully scraped %d detailed Facebook listings for '%s'", len(detailed_records), query)
                return detailed_records

            finally:
                await cdp.close()


def _save_outputs(records: List[dict], output_dir: Path, slug: str):
    # 1. JSON
    json_path = output_dir / f"facebook_{slug}_listings.json"
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. CSV
    csv_path = output_dir / f"facebook_{slug}_listings.csv"
    fields = [
        "origin", "listing_type", "listing_id", "title", "price", "price_raw",
        "city", "condition", "series", "manufacturer", "processor",
        "ram", "storage", "screen_size", "description", "date_advertised",
        "date_last_seen_active", "latitude", "longitude", "link"
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)

    # 3. Markdown
    md_path = output_dir / f"facebook_{slug}.md"
    lines = [
        f"# Facebook Marketplace: {slug.upper()}",
        "",
        f"Scraped **{len(records)}** listings on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        "",
        "| Price | Title | Series | Processor | RAM | Storage | City | Condition | Link |",
        "|------:|-------|--------|-----------|-----|---------|------|-----------|------|",
    ]
    for r in records:
        p = f"{r.get('price'):,}&nbsp;₪" if r.get("price") else (r.get("price_raw") or "-")
        t = (r.get("title") or "-")[:45].replace("|", "/")
        series = r.get("series") or "-"
        proc = r.get("processor") or "-"
        ram = r.get("ram") or "-"
        ssd = r.get("storage") or "-"
        c = (r.get("city") or "-").replace("|", "/")
        cond = (r.get("condition") or "-").replace("|", "/")
        link = f"[view]({r.get('link')})" if r.get("link") else "-"
        lines.append(f"| {p} | {t} | {series} | {proc} | {ram} | {ssd} | {c} | {cond} | {link} |")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Scrape Facebook Marketplace via Chromebox CDP")
    parser.add_argument("--query", default="macbook", help="Search query (e.g. 'macbook', 'תל אביב')")
    parser.add_argument(
        "--category",
        default="",
        help="Marketplace category: propertyrentals|propertysales|search (default search)",
    )
    parser.add_argument("--output-dir", default="/home/s/opt/yad2/facebook", help="Output directory")
    parser.add_argument("--max-items", type=int, default=30, help="Maximum items to scrape")
    parser.add_argument("--max-scrolls", type=int, default=8, help="Maximum feed scrolls")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between item visits (seconds)")
    parser.add_argument("--cdp-base", default=DEFAULT_CDP_BASE, help="CDP base URL (default http://127.0.0.1:11222)")
    args = parser.parse_args()

    asyncio.run(run_marketplace_scrape(
        query=args.query,
        output_dir=Path(args.output_dir),
        max_items=args.max_items,
        max_scrolls=args.max_scrolls,
        item_delay=args.delay,
        cdp_base=args.cdp_base,
        category=args.category or None,
    ))


if __name__ == "__main__":
    main()
