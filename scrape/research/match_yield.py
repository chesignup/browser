#!/usr/bin/env python3
"""Match sale listings to nearby similar rentals; compute gross yield ratio.

Ratio = (max matching monthly rent × 12) / sale price.

A rental may match many sales. Among rentals that match one sale, the
highest monthly rent is used.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from tama import tama_potential_pct

EARTH_M = 6371000.0


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(a))


def _num(v):
    if v in (None, "", False):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bool(v):
    if v is None:
        return None
    return bool(v)


def amenity_ok(sale: dict, rent: dict) -> bool:
    for key in ("elevator", "mamad", "parking"):
        s, r = _bool(sale.get(key)), _bool(rent.get(key))
        if s is None or r is None:
            continue
        if s != r:
            return False
    return True


def rooms_ok(sale: dict, rent: dict, tol: float) -> bool:
    a, b = _num(sale.get("rooms")), _num(rent.get("rooms"))
    if a is None or b is None:
        return False
    return abs(a - b) <= tol + 1e-9


def sqm_ok(sale: dict, rent: dict, rel: float, abs_m: float) -> bool:
    a, b = _num(sale.get("sqm")), _num(rent.get("sqm"))
    if a is None or b is None or a <= 0 or b <= 0:
        return False
    return abs(a - b) <= max(abs_m, rel * a)


def coords(row: dict) -> tuple[float, float] | None:
    lat, lon = _num(row.get("lat")), _num(row.get("lon"))
    if lat is None or lon is None:
        return None
    return lat, lon


def load_kind(folder: Path) -> list[dict]:
    details_p = folder / "listing_details.json"
    master_p = folder / "master_listings.json"
    geo_p = folder / "listings_geo.json"
    details = json.loads(details_p.read_text()) if details_p.exists() else []
    master = json.loads(master_p.read_text()) if master_p.exists() else []
    geo_rows = json.loads(geo_p.read_text()) if geo_p.exists() else []
    if not isinstance(details, list):
        details = list(details.values()) if isinstance(details, dict) else []
    if not isinstance(master, list):
        master = []
    if not isinstance(geo_rows, list):
        geo_rows = []
    m_by = {r["token"]: r for r in master if r.get("token")}
    g_by = {r["token"]: r for r in geo_rows if r.get("token")}
    out = []
    seen = set()
    for d in details:
        tok = d.get("token")
        if not tok:
            continue
        row = dict(m_by.get(tok) or {})
        row.update(d)
        if not row.get("price"):
            row["price"] = (m_by.get(tok) or {}).get("price") or 0
        g = g_by.get(tok) or {}
        if g.get("lat") not in (None, "") and g.get("lon") not in (None, ""):
            row["lat"], row["lon"] = g["lat"], g["lon"]
            if g.get("geo_query"):
                row["geo_query"] = g["geo_query"]
        out.append(row)
        seen.add(tok)
    for tok, m in m_by.items():
        if tok not in seen:
            row = dict(m)
            g = g_by.get(tok) or {}
            if g.get("lat") not in (None, ""):
                row["lat"], row["lon"] = g.get("lat"), g.get("lon")
            out.append(row)
    return out


def match_rows(
    sales: list[dict],
    rents: list[dict],
    radius_m: float = 600,
    rooms_tol: float = 0.5,
    sqm_rel: float = 0.20,
    sqm_abs: float = 15,
) -> list[dict]:
    rent_idx = []
    for r in rents:
        c = coords(r)
        price = _num(r.get("price")) or 0
        if not c or price <= 0:
            continue
        rent_idx.append((r, c[0], c[1], price))

    table = []
    for s in sales:
        sale_price = _num(s.get("price")) or 0
        sc = coords(s)
        if sale_price <= 0 or not sc:
            continue
        matches = []
        for r, rlat, rlon, rprice in rent_idx:
            if not amenity_ok(s, r) or not rooms_ok(s, r, rooms_tol) or not sqm_ok(s, r, sqm_rel, sqm_abs):
                continue
            dist = haversine_m(sc[0], sc[1], rlat, rlon)
            if dist > radius_m:
                continue
            matches.append((rprice, dist, r))
        if not matches:
            continue
        matches.sort(key=lambda x: (-x[0], x[1]))
        best_rent, best_dist, best = matches[0]
        ratio = (best_rent * 12.0) / sale_price
        table.append({
            "sale_price": int(sale_price),
            "link": s.get("link") or "",
            "sqm": s.get("sqm"),
            "rooms": s.get("rooms"),
            "tama_potential_pct": tama_potential_pct(s),
            "ratio": round(ratio, 6),
            "city": s.get("city") or "",
            "neighborhood": s.get("neighborhood") or "",
            "street": s.get("street") or "",
            "lat": sc[0],
            "lon": sc[1],
            "date_last_seen_active": s.get("date_last_seen_active") or "",
            "date_advertised": s.get("date_advertised") or "",
            "views": s.get("views") if s.get("views") not in (None, "") else "",
            "broker": "",
            "rent_monthly_used": int(best_rent),
            "rent_link": best.get("link") or "",
            "rent_token": best.get("token") or "",
            "rent_distance_m": int(best_dist),
            "n_rent_matches": len(matches),
            "sale_token": s.get("token") or "",
            "elevator": s.get("elevator"),
            "mamad": s.get("mamad"),
            "parking": s.get("parking"),
        })
    table.sort(key=lambda r: r["ratio"], reverse=True)
    return table


COLUMNS = [
    "sale_price", "link", "sqm", "rooms", "tama_potential_pct", "ratio",
    "city", "neighborhood", "street", "lat", "lon",
    "date_last_seen_active", "date_advertised", "views", "broker",
    "rent_monthly_used", "rent_link", "rent_distance_m", "n_rent_matches",
]


def write_table(rows: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "sale_yield.json"
    csv_path = out_dir / "sale_yield.csv"
    md_path = out_dir / "sale_yield.md"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    lines = [
        "# Sale listings ranked by gross rental yield",
        "",
        "`ratio` = (max similar nearby monthly rent × 12) / sale price. Highest first.",
        "",
        "| ratio | price | rooms | sqm | tama% | city | neighborhood | street | rent/mo | dist_m | n | link |",
        "|------:|------:|------:|----:|------:|------|--------------|--------|--------:|-------:|--:|------|",
    ]
    for r in rows[:500]:
        lines.append(
            "| {ratio:.4f} | {sale_price} | {rooms} | {sqm} | {tama_potential_pct} | {city} | {neighborhood} | {street} | {rent_monthly_used} | {rent_distance_m} | {n_rent_matches} | {link} |".format(**{**r, "rooms": r.get("rooms") or "", "sqm": r.get("sqm") or ""})
        )
    md_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sale", type=Path, required=True)
    ap.add_argument("--rent", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--radius-m", type=float, default=600)
    ap.add_argument("--rooms-tol", type=float, default=0.5)
    ap.add_argument("--sqm-rel", type=float, default=0.20)
    args = ap.parse_args()
    sales = json.loads(args.sale.read_text())
    rents = json.loads(args.rent.read_text())
    table = match_rows(sales, rents, radius_m=args.radius_m, rooms_tol=args.rooms_tol, sqm_rel=args.sqm_rel)
    write_table(table, args.out)
    print(json.dumps({"rows": len(table), "out": str(args.out), "top_ratio": table[0]["ratio"] if table else None}))


if __name__ == "__main__":
    main()
