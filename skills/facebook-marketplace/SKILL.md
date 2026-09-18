---
name: facebook-marketplace
description: >-
  Search and browse Facebook Marketplace using the authenticated Chrome session in Chromebox.
  Search deals for Mac laptops, apartments, electronics, vehicles, and second-hand items.
  Extracts complete listing details: title, price, description, link, location/city, condition,
  specs/attributes, and coordinates. Supports both interactive browsing and deterministic scraping.
  After any live check: if the item page still shows details, mark active (never treat stale
  date_last_seen alone as sold); if the ad is gone or explicitly Sold, mark assumed_sold and
  update mac-listings / datasets.
---

# Facebook Marketplace Browsing & Scraping

Facebook Marketplace provides classified listings for electronics, computers (e.g. MacBooks),
real estate, vehicles, and goods. Facebook requires authentication to browse marketplace feeds.
The Chromebox environment (`qemu-browser`) contains an active, logged-in Facebook profile with
persisted session cookies (`c_user`, `xs`, `datr`).

## Architecture & Session Access

1. **Authenticated Chrome Browser:**
   - Runs inside Chromebox (`100.92.122.70` / QEMU guest) with profile `/home/vmuser/chrome-profile`.
   - Facebook login state is preserved across reboots via QEMU snapshot `clean`.
2. **CDP Connection Endpoint:**
   - Host tunnel: `http://127.0.0.1:11222`
   - Tailscale IP: `http://100.92.122.70:9222`
   - Web screencast & tab manager: `http://100.92.122.70:9222/` or `http://10.0.0.13:9222/`

---

## Capabilities & Collected Fields

The Facebook Marketplace scraper and browsing tools extract:
- **`title`**: Listing headline (e.g. `MacBook Air 15" M4 2025`)
- **`price`** & **`price_raw`**: Numeric integer price (in ₪ or currency) and raw string (e.g. `3,200 ₪`)
- **`city`**: Extracted city or region (e.g. `תל אביב - יפו`, `חיפה`)
- **`condition`**: Item condition (e.g. `משומש - כמו חדש`, `חדש`, `משומש - במצב טוב`)
- **`description`**: Full seller description text (multiline)
- **`link`**: Canonical URL (`https://www.facebook.com/marketplace/item/<id>/`)
- **`date_advertised`**: Relative or absolute posting date (e.g. `פורסם לפני 16 שעות ב: תל אביב`)
- **`date_last_seen_active`**: ISO UTC timestamp when scraped
- **`latitude` / `longitude`**: Embedded geolocation coordinates
- **`series` / `processor` / `ram` / `storage` / `screen_size`**: Structured device attributes and regex heuristics
- **`origin`**: Fixed value `"facebook"` for unified cross-platform datasets

---

## How to Run

### 1. Deterministic Scraper via CLI
Run directly on the host using the local CDP bridge:

```bash
python3 /home/s/opt/browser/scrape/facebook/scrape_marketplace.py \
  --query "macbook" \
  --max-items 40 \
  --max-scrolls 8 \
  --output-dir /home/s/opt/yad2/facebook
```

Options:
- `--query`: Search query (e.g. `macbook`, `apartments`, `iphone 16`, `thinkpad`)
- `--max-items`: Target number of listings to extract (default: 30)
- `--max-scrolls`: Number of infinite-scroll iterations on search page (default: 8)
- `--delay`: Seconds between item page visits (default: 2.2s; keep >= 2.0s to avoid rate limiting)
- `--cdp-base`: CDP endpoint (default: `http://127.0.0.1:11222`)

### 2. Deterministic Scraper via Docker Container
Run the dedicated scraper container:

```bash
docker run --rm --net=host \
  -e QUERY="macbook" \
  -e MAX_ITEMS=50 \
  -e CDP_BASE="http://127.0.0.1:11222" \
  -v /home/s/opt/yad2:/data/yad2 \
  -v /home/s/opt/browser/data:/data/output \
  fb-marketplace-scraper
```

The container automatically:
1. Executes `scrape_marketplace.py` to collect the specified listings.
2. Runs `merge_datasets.py` to merge with `/data/yad2/macbooks/macbook_listings.json`.
3. Emits `comprehensive_macbooks.json`, `comprehensive_macbooks.csv`, and `COMPREHENSIVE_MACBOOKS.md`.

### 3. Merging with Yad2 Datasets
To merge existing Facebook data with Yad2 data into a unified dataset:

```bash
python3 /home/s/opt/browser/scrape/facebook/merge_datasets.py \
  --yad2 /home/s/opt/yad2/macbooks/macbook_listings.json \
  --facebook /home/s/opt/yad2/facebook/facebook_macbook_listings.json \
  --output-dir /home/s/opt/yad2/macbooks \
  --dataset-basename "comprehensive_macbooks"
```

The resulting files:
- `comprehensive_macbooks.json`
- `comprehensive_macbooks.csv`
- `COMPREHENSIVE_MACBOOKS.md`

All rows contain an `origin` column with either `"yad2"` or `"facebook"`.

---

## Live status affirmation (sold vs active) — REQUIRED

Stale `date_last_seen_active` / missing from a **partial** search scroll is **not** sold.
Only a live item-page check (or an explicit Marketplace “Sold” state) decides status.

When you open a listing URL on Chromebox (`gbrowser` / CDP) and report on it, you **must**
also persist status into `mac-listings` (and any merged Facebook dump you maintain):

| Live observation | Action |
|------------------|--------|
| Item page loads with title/price/details (still for sale) | `listing_status=active`; set `date_last_seen_active` to now (UTC ISO); clear `assumed_sold_at` / `assumed_sold_price` / `assumed_sold_reason`; upsert price/title if changed |
| Page shows Sold / נמכר / listing removed / marketplace “no longer available” | `listing_status=assumed_sold`; set `assumed_sold_at` now; `assumed_sold_price` = last ask; `assumed_sold_reason=detail_page_gone` or `explicit_sold`; **do not** overwrite `date_last_seen_active` (keep last real sighting) |
| Captcha / login wall / CDP down | Do **not** change status; say check was inconclusive |

Canonical Mac dataset: `/home/s/opt/mac-listings/data/comprehensive/comprehensive_macbooks.json`
(+ sqlite via `python3 scripts/sync_sqlite.py` in that repo). Match rows by
`listing_id` / Marketplace item id in the URL (`…/marketplace/item/<id>/`).

Example (still live → reactivate; was wrongly treated as sold because last_seen was old):

```bash
# After confirming https://www.facebook.com/marketplace/item/1386667029544205/ still shows details:
python3 - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import json
path = Path("/home/s/opt/mac-listings/data/comprehensive/comprehensive_macbooks.json")
rows = json.loads(path.read_text())
now = datetime.now(timezone.utc).isoformat()
needle = "1386667029544205"
for r in rows:
    if str(r.get("listing_id")) == needle or needle in str(r.get("link") or ""):
        r["listing_status"] = "active"
        r["date_last_seen_active"] = now
        for k in ("assumed_sold_at", "assumed_sold_price", "assumed_sold_reason"):
            r[k] = None
        print("reactivated", r.get("title"), r.get("price"))
        break
else:
    raise SystemExit("listing not found")
path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
PY
cd /home/s/opt/mac-listings && python3 scripts/sync_sqlite.py
```

Hourly scrapers must follow the same rule: **affirm** listings (detail page or complete
feed). Never mark Facebook/Yad2 Mac rows sold solely because they were absent from a short
`--max-items` / partial scroll.

## Best Practices & Anti-Ban Rules

1. **Single Tab Reuse:** Never open 20 parallel tabs on Facebook. Navigate the single tab sequentially with a 2-3 second pause between items.
2. **Infinite Scroll:** Scroll search results with `window.scrollTo(0, document.body.scrollHeight)` and wait 2.5s between scrolls.
3. **Session Cookies:** Do not delete `/home/vmuser/chrome-profile` or clear Facebook cookies. The session was established cleanly.
4. **Interactive Inspection:** If a captcha or login check ever appears, view live screencast at `http://100.92.122.70:9222/` or noVNC at `http://100.92.122.70:6080/vnc.html`.
5. **Status writes:** After any live Marketplace check, update `listing_status` / `date_last_seen_active` as above — a chat-only “still live” report without a dataset write is incomplete.
