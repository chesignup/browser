---
name: mac-listings
description: >-
  Hourly MacBook listings from Yad2 + Facebook Marketplace via Chromebox CDP.
  Upserts into chesignup/mac-listings. Affirm listings live before recommending:
  live_check_listing.py --update. Stale last_seen alone is not sold. Facebook
  also has property rentals/sales (scrape_fb_realestate.py → yad2-listings/facebook).
---

# Mac listings

Repo: https://github.com/chesignup/mac-listings (canonical).  
Deprecated: `macbook-listings`.

```bash
cd /home/s/opt/mac-listings && docker-compose run --rm mac-listings-hourly
```

## Live-check before showing a deal

```bash
python3 scripts/live_check_listing.py 'https://www.facebook.com/marketplace/item/<ID>/' --update
```

Do not pitch a row as available from scrape/`active` alone. FB may redirect item
URLs to search — the helper recovers; `inconclusive` means do not claim live.

## Facebook real estate (same CDP scraper)

```bash
python3 scripts/scrape_fb_realestate.py --query 'תל אביב' --max-items 40
```

Writes `yad2-listings/facebook/facebook_realestate_listings.json`.
