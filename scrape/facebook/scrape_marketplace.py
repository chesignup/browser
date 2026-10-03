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
    """Finds an existing Facebook tab or reuses/creates a page."""
    with urllib.request.urlopen(f"{cdp_base}/json") as r:
        targets = json.loads(r.read().decode())
    pages = [t for t in targets if t.get("type") == "page"]
    fb_page = next((p for p in pages if "facebook.com" in p.get("url", "")), None)
    if fb_page:
        return fb_page
    if pages:
        return pages[0]
    with urllib.request.urlopen(f"{cdp_base}/json/new") as r:
        return json.loads(r.read().decode())


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

  return {
    id: (window.location.pathname.match(/\/item\/(\d+)/) || [])[1] || '',
    title,
    price,
    price_raw: priceLine,
    condition,
    city,
    posted: postedLine,
    attributes: attrs,
    description,
    latitude: lat,
    longitude: lon,
    link: window.location.href.split('?')[0]
  };
})()
"""


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


async def run_marketplace_scrape(
    query: str,
    output_dir: Path,
    max_items: int = 50,
    max_scrolls: int = 8,
    item_delay: float = 2.0,
    cdp_base: str = DEFAULT_CDP_BASE,
) -> List[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", query).strip("_").lower() or "items"

    async with aiohttp.ClientSession() as http_session:
        target = await get_or_create_page(http_session, cdp_base)
        ws_url = target["webSocketDebuggerUrl"]
        log.info("Connecting to Chrome CDP page: %s (%s)", target.get("id"), ws_url)

        async with http_session.ws_connect(ws_url, max_msg_size=0) as ws:
            cdp = CDPConnection(ws)
            try:
                # 1. Search Query
                search_url = f"https://www.facebook.com/marketplace/search/?query={urllib.parse.quote(query)}"
                log.info("Navigating to Facebook Marketplace search: %s", search_url)
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

                    details = None
                    try:
                        await cdp.call("Page.navigate", {"url": item_url}, timeout=10.0)
                        await asyncio.sleep(item_delay)
                        details_raw = await cdp.call(
                            "Runtime.evaluate",
                            {"expression": JS_EXTRACT_ITEM_DETAILS, "returnByValue": True},
                            timeout=10.0,
                        )
                        if isinstance(details_raw, dict) and not details_raw.get("subtype"):
                            details = details_raw
                    except Exception as err:
                        log.warning("  Failed to extract item %s: %s", item_id, err)

                    rec = {
                        "listing_id": item_id,
                        "token": item_id,
                        "origin": "facebook",
                        "listing_type": "macbook" if "mac" in query.lower() else "marketplace_item",
                        "link": item_url,
                        "title": (details and details.get("title")) or feed_item.get("title") or "",
                        "price": (details and details.get("price")) if (details and details.get("price") is not None) else feed_item.get("price"),
                        "price_raw": (details and details.get("price_raw")) or feed_item.get("price_raw") or "",
                        "city": (details and details.get("city")) or feed_item.get("city") or "",
                        "condition": (details and details.get("condition")) or "",
                        "description": (details and details.get("description")) or "",
                        "date_advertised": (details and details.get("posted")) or "",
                        "date_last_seen_active": now_iso,
                        "latitude": details.get("latitude") if details else None,
                        "longitude": details.get("longitude") if details else None,
                        "series": (details and details.get("attributes", {}).get("קו מוצרים")) or "",
                        "manufacturer": "Apple" if "mac" in query.lower() else "",
                        "processor": (details and details.get("attributes", {}).get("מעבד")) or "",
                        "ram": (details and details.get("attributes", {}).get("RAM")) or "",
                        "storage": (details and details.get("attributes", {}).get("Storage")) or "",
                        "screen_size": (details and details.get("attributes", {}).get("גודל מסך")) or "",
                        "views": None,
                        "ad_number": None,
                        "error": None,
                    }
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
    parser.add_argument("--query", default="macbook", help="Search query (e.g. 'macbook', 'apartments')")
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
    ))


if __name__ == "__main__":
    main()
