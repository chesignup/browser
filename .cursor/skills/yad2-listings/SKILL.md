---
name: yad2-listings
description: >-
  Yad2 Gush Dan apartment listing data only (JSON/CSV/MD) in chesignup/yad2-listings.
  Includes past_deals, searchable search/*.csv shards, and AGENTS.md for ChatGPT.
  Scraping lives in chesignup/yad2-scraper. When a live check finds an ad gone or
  sold, mark listing_status=assumed_sold; if still up, mark active and refresh
  date_last_seen_active (stale last_seen alone is not sold). Also holds office
  rentals under offices/ (sqm + description; Yad2 commercial + Facebook).
---

# Yad2 listings (data)

Repo: https://github.com/chesignup/yad2-listings  
Local: `/home/s/opt/yad2-listings`

Scraper: https://github.com/chesignup/yad2-scraper

- Lookup: `python3 scripts/lookup_listing.py TOKEN` or `--street גולומב`
- Past deals: `past_deals/` + enriched `past_deals_verdict`
- Agents: read `AGENTS.md`
- **Offices (rent):** `offices/listings_geo.json` — sqm + description; cities TLV / BB / PT / RG / Givatayim
  - FB: `offices/facebook/facebook_office_rentals.json`
  - Refresh: `yad2-scraper/scripts/hourly_office_rent_upsert.py`

## Live status affirmation (sold vs active) — REQUIRED

`listing_status=assumed_sold` means the ad is **gone from Yad2** (detail 404 /
`detail_page_gone`, explicit sold, or missing from a **complete** ≤₪5M feed) — not
“absent from a partial hourly page.”

When you verify a listing live (Chromebox / `gbrowser` / browser):

| Live observation | Persist |
|------------------|---------|
| Item page still shows the apartment (active ad) | `listing_status=active`; bump `date_last_seen_active` to now; clear `assumed_sold_*`. Prefer scraper re-upsert; for one-off agent checks use `sale/manual_overrides.json` via `scripts/upsert_manual_override.py` with `--set listing_status=active` and `--set date_last_seen_active=…` only if scrape cannot run |
| Page 404 / removed / “מודעה לא קיימת” / sold | Mark assumed sold: scraper path is `pipeline.assumed_sold.mark_token_assumed_sold` (reason `detail_page_gone` or `explicit_sold`). Sets `assumed_sold_at` / `assumed_sold_price` and may add `deal_source=assumed_delist` past_deal. Do **not** claim sold from stale `date_last_seen_active` alone |
| CDP/captcha failure | Leave status unchanged; report inconclusive |

Do **not** tell the user an ad is sold unless `listing_status=assumed_sold` **or** you
just confirmed the detail page is gone/sold live.
