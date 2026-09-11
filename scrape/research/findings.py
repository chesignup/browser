#!/usr/bin/env python3
"""Summarize sale↔rent yield table into FINDINGS.md (deterministic, no LLM)."""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return s[i]


def fmt_pct(ratio: float) -> str:
    return f"{ratio * 100:.2f}%"


def analyze(rows: list[dict]) -> str:
    if not rows:
        return "No sale/rent pairs matched (need geocoded listings within 600 m with similar features).\n"

    ratios = [float(r["ratio"]) for r in rows]
    lines = []
    lines.append("# Sale vs nearby rent — findings")
    lines.append("")
    lines.append("Matching is **deterministic**: a pair counts only if both have coordinates,")
    lines.append("haversine ≤ 600 m, rooms ±0.5, size ±20%, and the same elevator / ממ״ד / parking.")
    lines.append("`ratio` = (highest matching monthly rent × 12) / sale price. Sorted high → low.")
    lines.append("")
    lines.append("## Scale")
    lines.append("")
    lines.append(f"- Sales that found at least one similar nearby rental: **{len(rows)}**")
    lines.append(f"- Gross yield (ratio): min {fmt_pct(min(ratios))}, median {fmt_pct(statistics.median(ratios))}, "
                 f"p90 {fmt_pct(pct(ratios, 90))}, max {fmt_pct(max(ratios))}")
    lines.append(f"- Mean yield: {fmt_pct(statistics.mean(ratios))}")
    sane = [x for x in ratios if 0.01 <= x <= 0.12]
    if sane:
        lines.append(
            f"- Plausible band (1–12% gross, typical IL): **{len(sane)}** sales, "
            f"median {fmt_pct(statistics.median(sane))}, p90 {fmt_pct(pct(sane, 90))}"
        )
        wild = len(rows) - len(sane)
        if wild:
            lines.append(
                f"- **{wild}** rows outside 1–12% (often a bad price: sale too low or rent not monthly). Treat top-of-list with suspicion."
            )
    lines.append("")

    lines.append("## By city (median yield, count)")
    lines.append("")
    by_city: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_city[r.get("city") or "?"].append(float(r["ratio"]))
    lines.append("| city | n | median yield | p90 | max |")
    lines.append("|------|--:|-------------:|----:|----:|")
    for city, vals in sorted(by_city.items(), key=lambda kv: -statistics.median(kv[1])):
        lines.append(
            f"| {city} | {len(vals)} | {fmt_pct(statistics.median(vals))} | "
            f"{fmt_pct(pct(vals, 90))} | {fmt_pct(max(vals))} |"
        )
    lines.append("")

    tama = Counter(int(r.get("tama_potential_pct") or 0) for r in rows)
    lines.append("## תמ״א potential (heuristic on ad text)")
    lines.append("")
    for k in sorted(tama):
        lines.append(f"- {k}%: {tama[k]} sales")
    lines.append("")

    lines.append("")

    def row_line(r: dict) -> str:
        addr = " / ".join(x for x in (r.get("street"), r.get("neighborhood"), r.get("city")) if x)
        return (
            "| {y} | {price} | {rent} | {dist}m | {rooms} | {area} | {tama} | {addr} | {link} | {rent_link} |".format(
                y=fmt_pct(float(r["ratio"])),
                price=r.get("sale_price"),
                rent=r.get("rent_monthly_used"),
                dist=r.get("rent_distance_m"),
                rooms=r.get("rooms") or "",
                area=r.get("sqm") or "",
                tama=r.get("tama_potential_pct"),
                addr=addr,
                link=r.get("link") or "",
                rent_link=r.get("rent_link") or "",
            )
        )

    hdr = (
        "| yield | price | rent/mo | dist | rooms | sqm | tama% | address | sale | rent |\n"
        "|------:|------:|--------:|-----:|------:|----:|------:|---------|------|------|"
    )
    lines.append("## Highest plausible yields (1–12% band)")
    lines.append("")
    lines.append(hdr)
    for r in [x for x in rows if 0.01 <= float(x["ratio"]) <= 0.12][:15]:
        lines.append(row_line(r))
    lines.append("")
    lines.append("## Highest raw yields (includes bad prices — do not use as-is)")
    lines.append("")
    lines.append(hdr)
    for r in rows[:8]:
        lines.append(row_line(r))
    lines.append("")
    lines.append("## How to read this")
    lines.append("")
    lines.append("- **~4%** is 8,000 ₪/mo × 12 / 2,300,000 ₪ — a typical “can rent cover the price?” check.")
    lines.append("- Using the **max** nearby similar rent **optimistic**; one expensive rental can lift many sales.")
    lines.append("- 600 m + amenity match can still mix streets; check the two links before acting.")
    lines.append("- No broker field in the scrape (`broker` column is empty).")
    lines.append("- תמ״א % is from Hebrew free text + elevator/ממ״ד, not a legal file.")
    lines.append("")
    return "\n".join(lines)


def main() -> Path:
    src = HERE / "sale_yield.json"
    rows = json.loads(src.read_text()) if src.exists() else []
    if not isinstance(rows, list):
        rows = []
    text = analyze(rows)
    out = HERE / "FINDINGS.md"
    out.write_text(text + "\n")
    print(text)
    print(f"\nWrote {out}", flush=True)
    return out


if __name__ == "__main__":
    main()
