#!/usr/bin/env python3
"""Geocode yad2 listing JSON (street/neighborhood/city → lat/lon).

Uses OpenStreetMap Nominatim with a persistent cache. Safe to re-run.

  python3 geocode.py --in ../sale/listing_details.json --out ../sale/listings_geo.json
  python3 geocode.py --in ../sale/listing_details.json --inplace --limit 50
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "yad2-research/1.0 (local listing geocoder; nominatim usage policy)"


def address_queries(row: dict) -> list[str]:
    city = (row.get("city") or "").strip()
    nb = (row.get("neighborhood") or "").strip()
    street = (row.get("street") or "").strip()
    parts = []
    if street and nb and city:
        parts.append(f"{street}, {nb}, {city}, ישראל")
    if street and city:
        parts.append(f"{street}, {city}, ישראל")
    if nb and city:
        parts.append(f"{nb}, {city}, ישראל")
    if city:
        parts.append(f"{city}, ישראל")
    # de-dupe
    seen, out = set(), []
    for q in parts:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def cache_key(row: dict) -> str:
    qs = address_queries(row)
    return qs[0] if qs else ""


def nominatim_search(query: str, timeout: int = 20) -> dict | None:
    params = {
        "q": query,
        "format": "json",
        "limit": "1",
        "countrycodes": "il",
        "addressdetails": "0",
    }
    url = NOMINATIM + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data:
        return None
    hit = data[0]
    return {
        "lat": float(hit["lat"]),
        "lon": float(hit["lon"]),
        "display_name": hit.get("display_name") or "",
        "query": query,
    }


def load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    tmp.replace(path)


def geocode_rows(
    rows: list[dict],
    cache: dict,
    delay: float = 1.05,
    limit: int | None = None,
    cache_path: Path | None = None,
    progress_path: Path | None = None,
    label: str = "",
) -> tuple[int, int]:
    hits = misses = 0
    n = 0
    total = len(rows) if limit is None else min(len(rows), limit)
    net_since_save = 0

    def heartbeat():
        if progress_path:
            progress_path.write_text(json.dumps({
                "label": label,
                "done": n,
                "total": total,
                "geocoded": hits,
                "missing": misses,
                "cache_keys": len(cache),
            }) + "\n")
        print(json.dumps({
            "geocode_progress": True,
            "label": label,
            "done": n,
            "total": total,
            "geocoded": hits,
            "missing": misses,
            "cache_keys": len(cache),
        }), flush=True)

    for row in rows:
        if limit is not None and n >= limit:
            break
        n += 1
        if row.get("lat") not in (None, "", 0) and row.get("lon") not in (None, "", 0):
            hits += 1
            if n % 200 == 0:
                heartbeat()
            continue
        queries = address_queries(row)
        if not queries:
            misses += 1
            continue
        found = None
        for q in queries:
            if q in cache:
                if cache[q]:
                    found = cache[q]
                    break
                continue
            try:
                found = nominatim_search(q)
            except Exception:
                found = None
            cache[q] = found
            net_since_save += 1
            time.sleep(delay)
            if found:
                break
        if found:
            row["lat"] = found["lat"]
            row["lon"] = found["lon"]
            row["geo_query"] = found.get("query") or queries[0]
            row["geo_display_name"] = found.get("display_name") or ""
            hits += 1
        else:
            row.setdefault("lat", None)
            row.setdefault("lon", None)
            misses += 1
        if net_since_save >= 20 and cache_path:
            save_cache(cache_path, cache)
            net_since_save = 0
            heartbeat()
        elif n % 50 == 0:
            heartbeat()
    if cache_path:
        save_cache(cache_path, cache)
    heartbeat()
    return hits, misses


def main() -> None:
    ap = argparse.ArgumentParser(description="Geocode yad2 listing JSON via Nominatim")
    ap.add_argument("--in", dest="src", required=True, type=Path)
    ap.add_argument("--out", dest="dst", type=Path)
    ap.add_argument("--inplace", action="store_true")
    ap.add_argument("--cache", type=Path, default=Path(__file__).resolve().parent / "geo_cache.json")
    ap.add_argument("--delay", type=float, default=1.05)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    rows = json.loads(args.src.read_text())
    if not isinstance(rows, list):
        raise SystemExit("expected a JSON array of listings")
    cache = load_cache(args.cache)
    hits, misses = geocode_rows(rows, cache, delay=args.delay, limit=args.limit, cache_path=args.cache)
    save_cache(args.cache, cache)
    dst = args.src if args.inplace else (args.dst or args.src.with_name(args.src.stem + ".geo.json"))
    dst.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"wrote": str(dst), "n": len(rows), "geocoded": hits, "missing": misses, "cache": str(args.cache)}))


if __name__ == "__main__":
    main()
