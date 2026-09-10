#!/usr/bin/env python3
"""Rent listing-detail helpers (mirrors sale scrape_listing_details)."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yad2_listing_fields import (
    overlay_details_on_feed,
    pick_date_advertised,
    pick_description_from_api,
)

ROOT = Path("/root/work/rent")
MASTER = ROOT / "master_listings.json"
DETAILS = ROOT / "listing_details.json"
DETAILS_CSV = ROOT / "listing_details.csv"
TABLE_MD = ROOT / "apartments_for_rent.md"
PROGRESS = ROOT / "scrape_progress.json"
NOW_ISO = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

FEED_FILES = [
    ("givatayim_rent.json", "גבעתיים"),
    ("ramatgan_rent.json", "רמת גן"),
    ("telaviv_rent.json", "תל אביב יפו"),
    ("petachtikva_rent.json", "פתח תקווה"),
    ("bneiarak_rent.json", "בני ברק"),
    ("kiriatono_rent.json", "קרית אונו"),
]

CITY_REGION = {
    "גבעתיים": "tel-aviv-area",
    "רמת גן": "tel-aviv-area",
    "תל אביב יפו": "tel-aviv-area",
    "פתח תקווה": "center-and-sharon",
    "בני ברק": "center-and-sharon",
    "קרית אונו": "center-and-sharon",
}

MIN_PRICE = 6000
EXCLUDE_TYPES = {"חניה", "מחסן", "מגרשים", "בניין מגורים", "כללי"}


def build_feed_skeleton() -> list[dict]:
    seen: dict[str, dict] = {}
    for fname, expected_city in FEED_FILES:
        path = ROOT / fname
        if not path.exists():
            continue
        rows = json.loads(path.read_text())
        for row in rows:
            token = row.get("token")
            if not token:
                continue
            city = row.get("city") or expected_city
            if city != expected_city:
                continue
            ptype = (row.get("type") or row.get("property_type") or "").strip()
            if ptype in EXCLUDE_TYPES:
                continue
            price = row.get("price") or 0
            if price and price < MIN_PRICE:
                continue
            region = CITY_REGION.get(city, "tel-aviv-area")
            seen[token] = {
                "token": token,
                "city": city,
                "neighborhood": row.get("neighborhood") or "",
                "street": (row.get("street") or "").strip(),
                "floor": row.get("floor"),
                "price": price,
                "property_type": ptype,
                "rooms": row.get("rooms"),
                "sqm": row.get("sqm"),
                "tags": row.get("tags") or [],
                "region": region,
                "link": f"https://www.yad2.co.il/realestate/item/{region}/{token}",
                "listing_type": "rent",
                "description": "",
                "date_advertised": "",
                "date_last_seen_active": "",
                "views": None,
                "listing_id": token,
            }
    return sorted(seen.values(), key=lambda x: (x["city"], x["price"] or 0, x["token"]))


def merge_master() -> list[dict]:
    items = overlay_details_on_feed(build_feed_skeleton(), load_details())
    MASTER.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    return items


def amenity_map(items_v2: list | None) -> dict:
    out = {}
    for it in items_v2 or []:
        key = it.get("key")
        if key is not None:
            out[key] = bool(it.get("value"))
    return out


def _parse_price(api_price, feed_price):
    if isinstance(api_price, (int, float)) and api_price:
        return int(api_price)
    if isinstance(api_price, str):
        if "לא צוין" in api_price or not api_price.strip():
            return feed_price or 0
        digits = re.sub(r"[^\d]", "", api_price)
        if digits:
            return int(digits)
    return feed_price or 0


def _num(info_bar, key):
    for it in info_bar or []:
        if it.get("key") == key:
            t = it.get("titleWithoutLabel") or it.get("title") or ""
            m = re.search(r"[\d.]+", str(t))
            return float(m.group()) if m else None
    return None


def parse_api_item(token: str, feed: dict, api: dict, views: int | None) -> dict:
    am = amenity_map(api.get("additional_info_items_v2"))
    desc = pick_description_from_api(api)
    parking_raw = api.get("parking")
    if parking_raw in (None, "", "ללא", "אין", 0, "0"):
        parking = False
    else:
        parking = True
    elevator = am.get("elevator")
    mamad = am.get("shelter")
    if mamad is None:
        mamad = bool(api.get("shelter"))
    date_advertised = pick_date_advertised(api)
    return {
        **feed,
        "listing_id": token,
        "ad_number": api.get("ad_number") or api.get("adNumber"),
        "description": desc,
        "price": _parse_price(api.get("price"), feed.get("price")),
        "rooms": _num(api.get("info_bar_items"), "rooms") or feed.get("rooms"),
        "sqm": api.get("square_meters") or feed.get("sqm"),
        "elevator": elevator,
        "mamad": mamad,
        "parking": parking,
        "parking_raw": parking_raw,
        "tama38": False,
        "rented_for": None,
        "views": views,
        "date_advertised": date_advertised,
        "date_last_seen_active": NOW_ISO,
        "error": None,
    }


def load_details() -> dict[str, dict]:
    if DETAILS.exists():
        data = json.loads(DETAILS.read_text())
        if isinstance(data, list):
            return {d["token"]: d for d in data if d.get("token")}
        return data
    return {}


def _yn(v):
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return ""


def save_details(by_token: dict[str, dict]) -> None:
    rows = sorted(by_token.values(), key=lambda x: (x.get("city") or "", x.get("price") or 0, x.get("token") or ""))
    DETAILS.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    fieldnames = [
        "listing_type", "link", "sqm", "rooms", "description", "price",
        "elevator", "mamad", "parking", "views",
        "date_advertised", "date_last_seen_active", "listing_id",
        "city", "neighborhood", "street", "floor", "property_type", "ad_number", "error",
    ]
    with DETAILS_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            row = dict(r)
            row["listing_id"] = r.get("listing_id") or r.get("token")
            w.writerow(row)
    lines = [
        "# Apartments for rent ≥ ₪6,000 / month (near Ramat Gan)",
        "",
        f"Scraped: {NOW_ISO}  ",
        f"Total with details: {len(rows)}",
        "",
        "| type | city | price | rooms | sqm | elevator | ממ\"ד | חניה | views | advertised | last_seen | listing_id | link | description |",
        "|---|---|---:|---:|---:|---|---|---|---:|---|---|---|---|---|",
    ]
    for r in rows:
        desc = (r.get("description") or "").replace("|", "/").replace("\n", " ")
        if len(desc) > 120:
            desc = desc[:117] + "..."
        lines.append(
            "| {type} | {city} | {price} | {rooms} | {sqm} | {elev} | {mamad} | {park} | {views} | {adv} | {seen} | {lid} | {link} | {desc} |".format(
                type=r.get("listing_type") or "rent",
                city=r.get("city") or "",
                price=r.get("price") or "",
                rooms=r.get("rooms") if r.get("rooms") is not None else "",
                sqm=r.get("sqm") if r.get("sqm") is not None else "",
                elev=_yn(r.get("elevator")),
                mamad=_yn(r.get("mamad")),
                park=_yn(r.get("parking")),
                views=r.get("views") if r.get("views") is not None else "",
                adv=(r.get("date_advertised") or "")[:19],
                seen=(r.get("date_last_seen_active") or "")[:19],
                lid=r.get("listing_id") or r.get("token") or "",
                link=r.get("link") or "",
                desc=desc,
            )
        )
    TABLE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    master_items = overlay_details_on_feed(build_feed_skeleton(), by_token)
    MASTER.write_text(json.dumps(master_items, ensure_ascii=False, indent=2))


def pending_tokens(master: list[dict], done: dict[str, dict]) -> list[str]:
    return [m["token"] for m in master if m["token"] not in done or done[m["token"]].get("error")]


def merge_batch(feed_by_token: dict, done: dict, batch_results: list[dict]) -> dict:
    for item in batch_results:
        token = item.get("token")
        if not token:
            continue
        feed = feed_by_token.get(token, {"token": token, "listing_type": "rent"})
        if item.get("error"):
            done[token] = {**feed, "listing_id": token, "error": item["error"], "date_last_seen_active": NOW_ISO}
            continue
        done[token] = parse_api_item(token, feed, item.get("api") or {}, item.get("views"))
    save_details(done)
    PROGRESS.write_text(json.dumps({
        "done": len([d for d in done.values() if not d.get("error")]),
        "errors": len([d for d in done.values() if d.get("error")]),
        "total": len(feed_by_token),
        "updated_at": NOW_ISO,
    }, ensure_ascii=False, indent=2))
    return done


if __name__ == "__main__":
    master = merge_master()
    print(json.dumps({"master": len(master)}, ensure_ascii=False))
