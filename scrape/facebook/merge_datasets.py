#!/usr/bin/env python3
"""Merge Yad2 and Facebook Marketplace datasets into a comprehensive dataset.

Adds an 'origin' column ('yad2' or 'facebook') and standardizes schema:
- origin
- listing_type
- listing_id
- title
- price
- price_raw
- city
- condition
- series
- manufacturer
- processor
- ram
- storage
- screen_size
- description
- date_advertised
- date_last_seen_active
- latitude
- longitude
- link
- views
- ad_number
- error
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import logging
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("merge_datasets")

STANDARD_FIELDS = [
    "origin",
    "listing_type",
    "listing_id",
    "title",
    "price",
    "price_raw",
    "city",
    "condition",
    "series",
    "manufacturer",
    "processor",
    "ram",
    "storage",
    "screen_size",
    "description",
    "date_advertised",
    "date_last_seen_active",
    "latitude",
    "longitude",
    "link",
    "views",
    "ad_number",
    "error",
]


def enrich_specs(item: Dict[str, Any]) -> Dict[str, Any]:
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
        else:
            item["series"] = "MacBook"

    # Manufacturer
    if not item.get("manufacturer"):
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
        m_screen = re.search(r"(\d{2}(?:\.\d)?)\s*(?:\"|״|אינץ)", text)
        if m_screen:
            item["screen_size"] = m_screen.group(1)

    return item


def load_yad2_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        log.warning("Yad2 dataset not found at %s", path)
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    records = []
    for row in data:
        rec = {
            "origin": "yad2",
            "listing_type": row.get("listing_type", "macbook"),
            "listing_id": str(row.get("listing_id") or row.get("token") or ""),
            "title": row.get("title", ""),
            "price": row.get("price"),
            "price_raw": f"{row.get('price'):,} ₪" if row.get("price") else "",
            "city": row.get("city", ""),
            "condition": row.get("condition", ""),
            "series": row.get("series", ""),
            "manufacturer": row.get("manufacturer") or "Apple",
            "processor": row.get("processor", ""),
            "ram": row.get("ram", ""),
            "storage": row.get("storage", ""),
            "screen_size": str(row.get("screen_size", "") or ""),
            "description": row.get("description", ""),
            "date_advertised": row.get("date_advertised", ""),
            "date_last_seen_active": row.get("date_last_seen_active", ""),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "link": row.get("link", ""),
            "views": row.get("views"),
            "ad_number": row.get("ad_number"),
            "error": row.get("error"),
        }
        rec = enrich_specs(rec)
        records.append(rec)
    log.info("Loaded %d Yad2 listings from %s", len(records), path)
    return records


def load_facebook_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        log.warning("Facebook dataset not found at %s", path)
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    records = []
    for row in data:
        rec = {
            "origin": "facebook",
            "listing_type": row.get("listing_type", "macbook"),
            "listing_id": str(row.get("listing_id") or row.get("id") or ""),
            "title": row.get("title", ""),
            "price": row.get("price"),
            "price_raw": row.get("price_raw", ""),
            "city": row.get("city", ""),
            "condition": row.get("condition", ""),
            "series": row.get("series", ""),
            "manufacturer": row.get("manufacturer") or "Apple",
            "processor": row.get("processor", ""),
            "ram": row.get("ram", ""),
            "storage": row.get("storage", ""),
            "screen_size": str(row.get("screen_size", "") or ""),
            "description": row.get("description", ""),
            "date_advertised": row.get("date_advertised", ""),
            "date_last_seen_active": row.get("date_last_seen_active", ""),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "link": row.get("link", ""),
            "views": row.get("views"),
            "ad_number": row.get("ad_number"),
            "error": row.get("error"),
        }
        rec = enrich_specs(rec)
        records.append(rec)
    log.info("Loaded %d Facebook listings from %s", len(records), path)
    return records


def generate_markdown_report(records: List[Dict[str, Any]], title: str = "Comprehensive Mac Dataset (Yad2 + Facebook Marketplace)") -> str:
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    yad2_recs = [r for r in records if r["origin"] == "yad2"]
    fb_recs = [r for r in records if r["origin"] == "facebook"]

    prices = [r["price"] for r in records if isinstance(r.get("price"), (int, float)) and r["price"] > 0]
    avg_price = int(sum(prices) / len(prices)) if prices else 0
    median_price = int(statistics.median(prices)) if prices else 0

    yad2_prices = [r["price"] for r in yad2_recs if isinstance(r.get("price"), (int, float)) and r["price"] > 0]
    fb_prices = [r["price"] for r in fb_recs if isinstance(r.get("price"), (int, float)) and r["price"] > 0]

    y_avg = int(sum(yad2_prices) / len(yad2_prices)) if yad2_prices else 0
    f_avg = int(sum(fb_prices) / len(fb_prices)) if fb_prices else 0

    lines = [
        f"# {title}",
        "",
        f"Generated on **{now_str}**.",
        "",
        "## Summary Metrics",
        "",
        f"- **Total Listings:** {len(records)}",
        f"  - **Yad2:** {len(yad2_recs)} listings (Average price: {y_avg:,} ₪)",
        f"  - **Facebook Marketplace:** {len(fb_recs)} listings (Average price: {f_avg:,} ₪)",
        f"- **Combined Price Range:** {min(prices):,} ₪ – {max(prices):,} ₪" if prices else "- **Combined Price Range:** N/A",
        f"- **Combined Median Price:** {median_price:,} ₪",
        f"- **Combined Average Price:** {avg_price:,} ₪",
        "",
        "## All Listings (Sorted by Price Ascending)",
        "",
        "| Origin | Price | Title | Series | Processor | RAM | Storage | City | Condition | Link |",
        "|:------:|------:|:------|:-------|:----------|:----|:--------|:-----|:----------|:----:|",
    ]

    sorted_recs = sorted(records, key=lambda r: (r.get("price") is None, r.get("price") or 0))
    for r in sorted_recs:
        origin_badge = "**Facebook**" if r["origin"] == "facebook" else "Yad2"
        p = f"{r.get('price'):,}&nbsp;₪" if r.get("price") else (r.get("price_raw") or "-")
        t = (r.get("title") or "-")[:45].replace("|", "/")
        series = r.get("series") or "-"
        proc = r.get("processor") or "-"
        ram = r.get("ram") or "-"
        ssd = r.get("storage") or "-"
        c = (r.get("city") or "-").replace("|", "/")
        cond = (r.get("condition") or "-").replace("|", "/")
        link = f"[view]({r.get('link')})" if r.get("link") else "-"
        lines.append(f"| {origin_badge} | {p} | {t} | {series} | {proc} | {ram} | {ssd} | {c} | {cond} | {link} |")

    lines.append("")
    return "\n".join(lines)


def merge(yad2_file: Path, facebook_file: Path, output_dir: Path, dataset_basename: str = "comprehensive_macbooks"):
    output_dir.mkdir(parents=True, exist_ok=True)

    yad2_records = load_yad2_records(yad2_file)
    fb_records = load_facebook_records(facebook_file)

    combined = yad2_records + fb_records
    log.info("Merged total: %d records (%d Yad2, %d Facebook)", len(combined), len(yad2_records), len(fb_records))

    # 1. JSON
    json_path = output_dir / f"{dataset_basename}.json"
    json_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Saved JSON dataset to %s", json_path)

    # 2. CSV
    csv_path = output_dir / f"{dataset_basename}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=STANDARD_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(combined)
    log.info("Saved CSV dataset to %s", csv_path)

    # 3. Markdown
    md_path = output_dir / f"{dataset_basename.upper()}.md"
    report_text = generate_markdown_report(combined)
    md_path.write_text(report_text, encoding="utf-8")
    log.info("Saved Markdown report to %s", md_path)

    return combined


def main():
    parser = argparse.ArgumentParser(description="Merge Yad2 and Facebook Mac datasets")
    parser.add_argument("--yad2", default="/home/s/opt/yad2/macbooks/macbook_listings.json", help="Yad2 JSON path")
    parser.add_argument("--facebook", default="/home/s/opt/yad2/facebook/facebook_macbook_listings.json", help="Facebook JSON path")
    parser.add_argument("--output-dir", default="/home/s/opt/yad2/macbooks", help="Output directory")
    parser.add_argument("--dataset-basename", default="comprehensive_macbooks", help="Base filename")
    args = parser.parse_args()

    merge(
        yad2_file=Path(args.yad2),
        facebook_file=Path(args.facebook),
        output_dir=Path(args.output_dir),
        dataset_basename=args.dataset_basename,
    )


if __name__ == "__main__":
    main()
