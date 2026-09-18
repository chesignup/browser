---
name: yad2-scraper
description: >-
  Hourly Yad2 Gush Dan apartment scrape tooling (CDP container) in chesignup/yad2-scraper.
  Publishes data to chesignup/yad2-listings. Sale max ₪2.8M (catalog often ≤₪5M catch-up).
  Detail scrape collects past deals; marks listing_status=assumed_sold when detail page
  is gone or missing from a complete feed; reactivates to active on any live sighting.
---

# Yad2 scraper

- Tooling: `/home/s/opt/yad2-scraper` → https://github.com/chesignup/yad2-scraper
- Data: `/home/s/opt/yad2-listings` → https://github.com/chesignup/yad2-listings

```bash
cd /home/s/opt/yad2-scraper && docker-compose run --rm yad2-scraper-hourly
```

## Sold / active affirmation

Code: `pipeline/assumed_sold.py`, wired from `scripts/hourly_sale_upsert.py` and
`scripts/backfill_past_deals.py`.

- **Mark sold:** detail API 404 / empty → `mark_token_assumed_sold(..., reason="detail_page_gone")`.
  Complete ≤₪5M feed miss → `mark_missing_as_assumed_sold` (never from tiny partial pages).
- **Reactivate:** any successful feed/detail sighting clears `assumed_sold_*` and sets
  `listing_status=active` (`pipeline/store.py`).
- Live agent checks: same semantics as the `yad2-listings` skill — gone page ⇒ sold;
  still showing ⇒ active + refresh `date_last_seen_active`.
