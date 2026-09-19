---
name: research-listings
description: >-
  Listings research container workspace (/root/work): Yad2 apartments, Mac
  (Yad2+Facebook), Chromebox via gbrowser. Office rentals under
  yad2-listings/offices/ (sqm + description). Before showing ANY listing to the
  user, live-check it on the source and persist listing_status. Facebook
  Marketplace covers goods and real estate (rent + sale).
---

# Research listings (mandatory live-check)

You are in the research container. Workspace: `/root/work` (host
`/home/s/opt/research-listings`).

## Before you recommend or display a listing

**Never** present a Yad2 or Facebook listing as a deal/bargain/candidate unless
you have **just** live-checked it on Chromebox and persisted status.

1. Run the helper (preferred):

```bash
# Mac / Facebook Marketplace item (updates mac-listings JSON + sqlite):
python3 /root/work/mac-listings/scripts/live_check_listing.py \
  'https://www.facebook.com/marketplace/item/<ID>/' --update

# Or numeric id:
python3 /root/work/mac-listings/scripts/live_check_listing.py <ID> --update

# Yad2 apartment or office URL/token (reports live_status; wire assumed_sold via scraper if sold):
python3 /root/work/mac-listings/scripts/live_check_listing.py \
  'https://www.yad2.co.il/realestate/item/.../<TOKEN>' --update
```

2. Read the JSON `live_status`:
   - `active` → OK to show; quote **live** price/title from the probe
   - `assumed_sold` → say sold/removed; do **not** pitch it as available
   - `inconclusive` → say the check failed (e.g. FB redirected to search); do **not**
     claim “still active from scrape alone”

3. If you only used dump/`listing_status=active` from the last scrape, that is
   **not** enough for a user-facing recommendation (the M4 Air `נמכר` case).

### Facebook redirect trap

Direct `…/marketplace/item/<id>/` often redirects to a Marketplace **search/results**
page. That is **not** a successful check. The helper retries URLs and clicks the
matching card. With `gbrowser` manually:

1. Prefer an existing Facebook tab (`gbrowser ctl list`).
2. `gbrowser ctl nav 'https://www.facebook.com/marketplace/item/<id>/'`
3. `gbrowser ctl eval 'location.href'` — must contain `/marketplace/item/<id>`
4. If it does not: search/click the card with that id, or re-run `live_check_listing.py`
5. Only then read title / `נמכר` / price and persist

## Data paths

| Kind | Path |
|------|------|
| Mac (Yad2+FB) | `mac-listings/data/comprehensive/comprehensive_macbooks.json` |
| Yad2 apartments | `yad2-listings/` (+ `AGENTS.md`) |
| **Office rentals** | `yad2-listings/offices/listings_geo.json` (sqm + description; TLV / BB / PT / RG / Givatayim) |
| FB office rentals | `yad2-listings/offices/facebook/` |
| FB real estate dumps | `yad2-listings/facebook/facebook_realestate_listings.json` |

## Office rentals (Yad2 commercial)

Rent-only משרדים (`dealType=1`, `property=12`). Skills: `yad2-scraper`, `yad2-listings`.

```bash
# On host / yad2-scraper container — refresh feed + descriptions:
cd /home/s/opt/yad2-scraper   # or /app in scraper container
python3 scripts/hourly_office_rent_upsert.py --areas 78,4,3,1 --max-detail 120
# Resume descriptions only:
python3 scripts/hourly_office_rent_upsert.py --detail-only --max-detail 500
```

When showing an office to the user: state **sqm** and **description**, and live-check first.

## Facebook real estate

Marketplace has **property rentals** and **property sales** categories, not only
goods. Scrape:

```bash
python3 /root/work/mac-listings/scripts/scrape_fb_realestate.py \
  --query 'תל אביב' --max-items 40
# or: --rent / --sale

# Office-only rentals → yad2-listings/offices/facebook/
python3 /root/work/mac-listings/scripts/scrape_fb_offices.py --max-items 25
```

Also: `facebook-marketplace` skill (`--category propertyrentals|propertysales`).

## Chromebox

Skill `browser-vm-remote` / `gbrowser tunnel status`.
