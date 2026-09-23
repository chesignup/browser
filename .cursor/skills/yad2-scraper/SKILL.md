---
name: yad2-scraper
description: >-
  Hourly Yad2 Gush Dan apartment scrape tooling (CDP container) in chesignup/yad2-scraper.
  Publishes data to chesignup/yad2-listings. Sale max ₪5M (`MAX_PRICE`).
  Detail scrape collects past deals; marks listing_status=assumed_sold when detail page
  is gone or missing from a complete feed; reactivates to active on any live sighting.
  Also scrapes commercial office rentals (dealType=1, property=12) into yad2-listings/offices/.
  Yad1 contractor projects via `scripts/scrape_yad1_sale.py`. Past-deals backfill via
  `scripts/backfill_past_deals.py` (resume-safe; publish every N batches).
---

# Yad2 scraper

- Tooling: `/home/s/opt/yad2-scraper` → https://github.com/chesignup/yad2-scraper
- Data: `/home/s/opt/yad2-listings` → https://github.com/chesignup/yad2-listings
- ChatGPT search shards: `yad2-listings/search/{sale,rent,past_deals,yad1,facebook}/*.csv` (full URLs required in answers)

```bash
cd /home/s/opt/yad2-scraper && docker-compose run --rm yad2-scraper-hourly
```

## Past deals backfill

```bash
python3 -u scripts/backfill_past_deals.py --batch-size 12 --sleep 1.0 --publish-every-batches 15
```

Store: `data/past_deals/past_deals.json`. Publish also refreshes `yad2-listings/past_deals/by_city/`.
If the process spins at 100% CPU with no new log lines after a batch, kill and restart
(store load used to be O(n²); fixed in `pipeline/past_deals.py`).

## Yad1 (contractor / new projects)

```bash
python3 scripts/scrape_yad1_sale.py
```

Merges into sale dump + `sale/yad1_listings.json`; searchable via `search/yad1/*.csv`.
## Office rentals (commercial)

Rent-only offices (`dealType=1`, `property=12` משרדים). Separate from apartment rent/sale;
uses a dedicated commercial CDP tab so apartment hourly catch-up is not stolen.

```bash
cd /home/s/opt/yad2-scraper
python3 scripts/hourly_office_rent_upsert.py --areas 1,3,4,78 --max-detail 120
# areas: 1=תל אביב, 3=רמת גן/גבעתיים, 4=פתח תקווה, 78=בני ברק
```

- Collector: `scrape/collect_commercial_feeds.py`
- Publishes → `yad2-listings/offices/` (`listings_geo.json` includes **sqm** + **description**)
- Feed URL pattern: `/realestate/commercial/{region}?area=N&dealType=1&property=12`

## Sold / active affirmation

Code: `pipeline/assumed_sold.py`, wired from `scripts/hourly_sale_upsert.py` and
`scripts/backfill_past_deals.py`.

- **Mark sold:** detail API 404 / empty → `mark_token_assumed_sold(..., reason="detail_page_gone")`.
  Complete ≤₪5M feed miss → `mark_missing_as_assumed_sold` (never from tiny partial pages).
- **Mark rented:** each hour, stale active rent ads not in this feed are live-checked
  (`--max-rent-status`, default 40, oldest last-seen first). Item gone → `assumed_rented`
  at last ask. Seen in feed → `active`. Complete rent feed (≥2000 tokens) can mass-delist.
- **Reactivate:** any successful feed/detail sighting clears `assumed_sold_*` / `assumed_rented_*` and sets
  `listing_status=active` (`pipeline/store.py`).
- Live agent checks: gone sale page ⇒ assumed_sold; gone rent page ⇒ assumed_rented;
  still showing ⇒ active + refresh `date_last_seen_active`.

## Municipal TAMA 38 progress

Not Tel Aviv only. `SCRAPE_MODE=tma38_muni` / daily timer `yad2-scraper-tma38-muni.timer` (04:20) plus watchdog every ~12h.

| City | Source | Notes |
|------|--------|--------|
| Tel Aviv | ArcGIS IView2 layer **772** HTTP | `building_stage`; harvest upserts `muni:tlv:772:…` |
| Ramat Gan | Complot `site_id=3` | HTTP then **Chromebox CDP** `fetch` / `Network.loadNetworkResource` (never Yad2 tab) |
| Givatayim | Complot `site_id=98` | same CDP fallback |
| Petah Tikva | ArcGIS addresses + Complot `site_id=84` | GIS alone is not auto-applied; permit text is |
| Kiryat Ono | Bartech street JSON | permit tables need reCAPTCHA — street-only is not auto-applied |
| Bnei Brak | Complot `site_id=75` | same as Ramat Gan |

```bash
python3 -m municipal_progress.enrich --apply --re-evaluate
python3 -m municipal_progress.enrich --rebuild-history
```

Supabase: `tma38_projects` + listing-shaped `tma38_project_progress_history` (`yad2_id`, `street`, `house_number`, `lat`, `lon`). Auto-apply only exact/high **with structured status**. TASE `source_url`/`report_url` are not wiped.
