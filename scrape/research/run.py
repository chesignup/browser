#!/usr/bin/env python3
"""Geocode sale+rent dumps, then build the sale yield table.

  python3 run.py
  python3 run.py --yad2 /home/s/opt/yad2 --no-geocode   # match only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from geocode import geocode_rows, load_cache, save_cache  # noqa: E402
from match_yield import load_kind, match_rows, write_table  # noqa: E402


def enrich_folder(folder: Path, cache: dict, cache_path: Path, delay: float, limit: int | None) -> Path:
    rows = load_kind(folder)
    hits, misses = geocode_rows(rows, cache, delay=delay, limit=limit, cache_path=cache_path)
    save_cache(cache_path, cache)
    out = folder / "listings_geo.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"folder": str(folder), "geocoded": hits, "missing": misses, "wrote": str(out)}), flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yad2", type=Path, default=HERE.parent)
    ap.add_argument("--no-geocode", action="store_true")
    ap.add_argument("--limit", type=int, help="geocode at most N listings per side (debug)")
    ap.add_argument("--delay", type=float, default=1.05)
    ap.add_argument("--radius-m", type=float, default=600)
    args = ap.parse_args()
    yad2: Path = args.yad2
    cache_path = HERE / "geo_cache.json"
    cache = load_cache(cache_path)
    sale_dir, rent_dir = yad2 / "sale", yad2 / "rent"
    if args.no_geocode:
        sales = load_kind(sale_dir)
        rents = load_kind(rent_dir)
    else:
        enrich_folder(sale_dir, cache, cache_path, args.delay, args.limit)
        enrich_folder(rent_dir, cache, cache_path, args.delay, args.limit)
        sales = json.loads((sale_dir / "listings_geo.json").read_text())
        rents = json.loads((rent_dir / "listings_geo.json").read_text())
    table = match_rows(sales, rents, radius_m=args.radius_m)
    out = yad2 / "research"
    write_table(table, out)
    print(json.dumps({
        "yield_rows": len(table),
        "csv": str(out / "sale_yield.csv"),
        "top_ratio": table[0]["ratio"] if table else None,
        "top_link": table[0]["link"] if table else None,
    }), flush=True)


if __name__ == "__main__":
    main()
