---
name: facebook-marketplace
description: >-
  Search and browse Facebook Marketplace using the authenticated Chrome session in Chromebox.
  Covers Mac/electronics AND real estate (property rentals + property sales). Extracts title,
  price, description, link, city, condition, specs, coordinates. After any live check: still
  on item page → listing_status=active; Sold/נמכר/gone → assumed_sold and update datasets.
  Direct item URLs often redirect to search — use live_check_listing.py (retries + card click).
---

# Facebook Marketplace Browsing & Scraping

Facebook Marketplace is authenticated-only. Chromebox holds the logged-in profile.
Categories include **goods** (MacBooks, etc.) and **real estate**
(`propertyrentals`, `propertysales`).

## Architecture

- Chrome in Chromebox (`100.92.122.70`) profile `/home/vmuser/chrome-profile`
- CDP: `http://127.0.0.1:11222` (host) / `http://100.92.122.70:9222` (Tailscale)

## Live-check BEFORE recommending (REQUIRED)

Dump/`listing_status=active` from the last scrape is **not** enough to pitch a deal.

```bash
# From research container or host with CDP:
python3 /home/s/opt/mac-listings/scripts/live_check_listing.py \
  'https://www.facebook.com/marketplace/item/<ID>/' --update
# or: live-check-listing <ID> --update
```

| `live_status` | Meaning |
|---------------|---------|
| `active` | Item page loaded; safe to show; JSON updated |
| `assumed_sold` | `נמכר` / gone; do not pitch as available |
| `inconclusive` | Redirected to search/results or CDP failure — say so; do not claim active |

### Redirect trap (why agents fail)

`gbrowser ctl nav '…/marketplace/item/<id>/'` often lands on a **search/results** page.
That is inconclusive. The helper retries alternate URLs and clicks the matching card.
Manually: `eval location.href` must contain `/marketplace/item/<id>` before reading details.

Sold badge is often `נמכר · <title>` on the item page (details/price can still render).

## Scrape goods (Mac)

```bash
python3 /home/s/opt/mac-listings/scrape/scrape_marketplace.py \
  --query macbook --max-items 40 --max-scrolls 8 \
  --output-dir /home/s/opt/mac-listings/data/facebook
```

Hourly: `cd /home/s/opt/mac-listings && docker-compose run --rm mac-listings-hourly`

## Scrape real estate (rent + sale)

```bash
# Both categories → yad2-listings/facebook/
python3 /home/s/opt/mac-listings/scripts/scrape_fb_realestate.py \
  --query 'תל אביב' --max-items 40

# Or category directly:
python3 /home/s/opt/mac-listings/scrape/scrape_marketplace.py \
  --category propertyrentals --query 'תל אביב' \
  --output-dir /home/s/opt/yad2-listings/facebook
python3 /home/s/opt/mac-listings/scrape/scrape_marketplace.py \
  --category propertysales --query 'תל אביב' \
  --output-dir /home/s/opt/yad2-listings/facebook
```

`listing_type` will be `rent` / `sale` / `macbook` / `marketplace_item`.
`origin` is always `facebook`.

## Scrape apartment groups (rent + sale, whole-place only)

Ramat Gan / Givatayim Facebook groups — skips roommates/שותפים and sublets/סאבלט.
Matches Yad2 rent/sale by street+house and attaches both links.

```bash
# → yad2-listings/facebook/groups/
python3 /home/s/opt/mac-listings/scripts/scrape_fb_groups_rentals.py \
  --cdp-base http://127.0.0.1:9222 --max-scrolls 8 --max-posts 40
```

Groups: `520940308003364`, `1424244737803677`.
Outputs: `facebook_group_listings.json` (+ rent/sale splits). Matched Yad2 rows get `facebook_links`.

## Scrape office rentals

```bash
# → yad2-listings/offices/facebook/ (filters title/description for משרד)
# Host:
python3 /home/s/opt/mac-listings/scripts/scrape_fb_offices.py --max-items 25
# Research container:
python3 /root/work/mac-listings/scripts/scrape_fb_offices.py --max-items 25
```

Default queries: משרד להשכרה in תל אביב / בני ברק / פתח תקווה / רמת גן / גבעתיים.
Yad2 commercial offices live in `yad2-listings/offices/` (see yad2-scraper skill).

## Persist status (Mac dataset)

Canonical: `/home/s/opt/mac-listings/data/comprehensive/comprehensive_macbooks.json`
(+ `python3 scripts/sync_sqlite.py`). Prefer `--update` on `live_check_listing.py`.

## Anti-ban

1. One Facebook tab; 2–3s between items  
2. Do not clear Chromebox Facebook cookies  
3. Captcha → mobile viewer / noVNC HITL  
