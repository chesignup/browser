---
name: mac-listings
description: >-
  Hourly MacBook listings from Yad2 + Facebook Marketplace via Chromebox CDP
  containers. Upserts into chesignup/mac-listings with origin column and change
  commits. Affirm each listing: still on item page → listing_status=active and
  refresh date_last_seen_active; gone/Sold → assumed_sold. Stale last_seen alone
  is not sold (e.g. FB item 1386667029544205 still live at ₪2200).
---

# Mac listings

Repo: https://github.com/chesignup/mac-listings  
Local: `/home/s/opt/mac-listings` (canonical; prefer over legacy `macbook-listings`)

```bash
cd /home/s/opt/mac-listings && docker-compose run --rm mac-listings-hourly
```

## Live status affirmation (sold vs active) — REQUIRED

Same rules as the `facebook-marketplace` and `yad2-listings` skills:

| Observation | Persist on the row |
|-------------|-------------------|
| Facebook/Yad2 item page still has details | `listing_status=active`, `date_last_seen_active=now`, clear `assumed_sold_*` |
| Item gone / Sold / נמכר | `listing_status=assumed_sold`, set `assumed_sold_at` / `assumed_sold_price` / reason; keep prior `date_last_seen_active` |
| Partial search miss only | Do **not** mark sold |

Dataset: `data/comprehensive/comprehensive_macbooks.json` → `python3 scripts/sync_sqlite.py`.
Facebook skill has a copy-paste reactivate snippet. After live Chromebox checks, always
write status — chat-only “still live” without updating the JSON/sqlite is incomplete.
