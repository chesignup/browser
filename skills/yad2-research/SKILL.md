---
name: yad2-research
description: >-
  Continue Yad2 Gush Dan sale-vs-rent yield research: geocoded listings,
  deterministic pairing (distance AND features), gross yield ratio, תמ״א
  heuristic, FINDINGS.md. Use when the user asks about yad2 research, rental
  yield, matching sales to rents, geocode, TAMA, or continuing the listings
  thread. Do not LLM-match ads; run the Python pipeline.
---

# Yad2 real-estate research (next thread)

Host dumps: `/home/s/opt/yad2/` (live) and git `data/yad2/` in
https://github.com/chesignup/browser

## What is already done

- Sale **3271/3271** and rent **3931/3931** detail scrapes (description, dates, views).
- Nominatim geocode cached in `research/geo_cache.json` (sale+rent `listings_geo.json`).
- Deterministic match: **haversine ≤ 600 m AND** rooms ±0.5, sqm ±20%, elevator/ממ״ד/parking equal.
- `ratio` = (max matching monthly rent × 12) / sale_price, sorted high → low.
- Table: `/home/s/opt/yad2/research/sale_yield.csv` (+ `.json`). Report: `FINDINGS.md`.

**Do not** compare listings in the model. Re-run:

```bash
python3 /home/s/opt/yad2/research/run.py --no-geocode   # match only
python3 /home/s/opt/yad2/research/run.py                # geocode + match
python3 /home/s/opt/yad2/research/findings.py
```

## How to read FINDINGS

- **~1709** sales have ≥1 similar nearby rent.
- **Median gross yield ~3.9%**; Tel Aviv a bit higher than PT/BB/Givatayim.
- **Ignore ratio ≫ 12%** (and the raw “top” list): bad prices (sale 10k–18k, or rent 3.65M which is a sale figure leaked into rent). Use the **1–12% band** (~1667 rows, median ~3.85%).
- תמ״א % is ad-text heuristic (100 = underway, 0 = new / elevator+ממ״ד).
- `broker` column is empty (not in scrape).
- One expensive rental can lift many sales (max-rent rule).

## Sensible next research (this skill)

1. Filter yield table: drop sale_price < 200k or rent_monthly > 30k (or similar caps).
2. Neighborhood-level medians; map (lat/lon already on rows).
3. TAMA 55–100% ∩ yield ≥ ~4.5% as a shortlist.
4. Re-geocode weak addresses (empty street).
5. After new scrapes: `watch-copy.sh` then `run.py`; then **repo-git-sync** skill to publish `data/yad2`.

## Stack reminders

- Chromebox: `qbrowser watch install` (systemd). LAN agent SSH: `ssh -p 2223 root@10.0.0.13` password `agent`.
- Pairing is geo **and** features, not one or the other.
- Cheap GitHub updates: skill `repo-git-sync`.
