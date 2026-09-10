---
name: yad2
description: >-
  Search and browse yad2.co.il (Israel's largest classifieds board) by driving the
  real browser via the human-browser tools — real estate for rent/sale, vehicles,
  and second-hand goods (e.g. used MacBook/Mac laptops). Use whenever the user asks
  to find apartments to rent or buy in Israel, cars, or used items on yad2 / לוח יד2.
  Prefer the deterministic CDP scrape pipeline for bulk listing collection; navigate
  with UI clicks for interactive browsing; hand off captcha to a human viewer when
  the watchdog cannot clear it.
---

# Using yad2.co.il

yad2 (לוח יד2) is a Hebrew, right-to-left classifieds site with aggressive bot
protection. Host-side HTTP to yad2 is blocked — all data collection must run
**inside** the shared Chromium session (human-browser / CDP).

Two modes:

1. **Interactive browse** — human-browser MCP tools for filters, one-off reads.
2. **Bulk scrape (preferred for large jobs)** — deterministic CDP scripts + watchdog
   (see below). Do not drive thousands of listings via agent `browser_eval` loops.

## Golden rules (interactive)

- **Controls:** `browser_snapshot(interactive_only=true)` → act on `[ref]`. Full
  snapshots on yad2 are huge — avoid them.
- **Reading listings:** `browser_read` / `browser_get_text`, not screenshots.
- **Click, don't guess URLs** for exploratory UI work. Once a filtered results URL
  is proven in-session, reuse it for pagination/feed collection.
- **Re-snapshot** after every navigation/filter change.
- **Expect bot checks** — plan for human-in-the-loop via `browser_viewer_url`.

## Bot / captcha (Radware Bot Manager)

Protection is **Radware Bot Manager** (formerly ShieldSquare) in front of
AWS CloudFront, with **hCaptcha** on the ShieldSquare challenge page. The site
is Next.js SSR plus a PHP backend. Fingerprinting uses the `__uzm*` cookie
family (not PerimeterX alone). See
[avishaynaim/yad2-investigator](https://github.com/avishaynaim/yad2-investigator).

Signs: "Press & Hold", "אני לא רובוט", `validate.perfdrive`, title contains
Captcha/Radware/ShieldSquare, HTTP 403/429/503, short "access denied" HTML,
empty feed, or CDP evaluate timeouts on all tabs.

1. Prefer the **watchdog** (`scripts/scrape_watchdog.py`) — it keeps **one**
   scrape tab, polls until captcha clears, and resumes batches.
2. If still blocked: call `browser_viewer_url` and tell the user to open the
   **mobile viewer** (`http://<guest>:6081/`) and complete the check on that
   **single** tab. Solving the challenge mints a fresh Radware session.
3. Do not hammer reloads or open new tabs — extra navigations burn the
   per-session quota and spawn dozens of captcha tabs.
4. After captcha clears, resume the same scrape (pending tokens are persisted).
   Do not keep sending XHR on a flagged session; wait for the human solve.

### What triggers the bot (investigator findings)

Radware counts **requests per session** (the `__uzm*` cookie set), **not**
per IP and **not** per wall-clock rate. Slowing down inside a burned session
does not help. Fresh session = fresh quota. That is the main result from
the investigation repo.

| Cookie | Role |
|--------|------|
| `__uzma` | UUID session id |
| `__uzmb` | visit unix timestamp |
| `__uzmc` | visit count / sequence |
| `__uzmd` | last-seen timestamp |
| `__uzme` | device/browser classification hash |
| `__uzmf` | composite fingerprint |
| `uzmx` | cross-domain fingerprint |

**Triggers (do these and you get CAPTCHA):**

- **Missing `Sec-Fetch-*` headers** → instant CAPTCHA. Host `curl`/`requests`
  without a real browser fetch metadata is dead on arrival. Never scrape
  yad2 from the host or the agent container over plain HTTP.
- **~6–7 requests on the same Radware session** (HTML pages in the
  investigator’s tests) → session flagged. Remaining requests on those
  cookies fail until the session is replaced (new cookies / captcha solve).
- **Continuing after the first block** on the same cookies — abandon the
  rest of that batch; wait or rotate session.

**Does *not* trigger by itself:** TLS fingerprint alone, missing cookies,
missing Referer, random page order, or going faster vs slower *within* the
quota.

**How this maps onto our headed Chrome (not curl_cffi):**

- Stay inside the guest Chromium tab. Chrome sends `Sec-Fetch-*` and
  collects real `__uzm*` cookies. That is why in-page XHR works and host
  HTTP does not.
- The guest profile is **one long session**. Thousands of
  `/api/item/{token}` calls share the same `__uzm*` cookies, so captcha
  after a long scrape is expected — it is session quota, not “we were too
  fast.”
- **Warm up** on `https://www.yad2.co.il/` (or a real results page) before
  feed collect or the first detail batch, so cookies exist.
- **Between batches:** sleep **12–25s** (investigator cooldown). Inside a
  batch, **3–6s** between *page navigations*. Bursting 40 sync XHRs in one
  `evaluate` is convenient but spends quota; if captcha appears, drop
  `--batch` (try 10–20) and keep the inter-batch sleep.
- **One tab.** `PUT /json/new` and extra `Page.navigate` are extra billed
  requests on the same cookies.
- The JSON feed
  `GET https://www.yad2.co.il/api/pre-load/getFeedIndex/realestate/{rent|forsale}`
  is lighter than full HTML results pages. Prefer dehydratedState already
  in the live tab; if you must hit an API, do it as **same-origin XHR from
  the page** (`Sec-Fetch-Mode: cors`, `Sec-Fetch-Site: same-origin`), never
  from the host.
- After a block: stop the batch, poll that one tab, human solves captcha,
  then continue. A flagged session will not recover by waiting a few
  seconds without a new cookie set.

We do **not** copy the investigator’s host-side `curl_cffi` session
rotation. Guest Chrome + CDP is the allowed path; their findings only
tell us **when** Radware trips and **not to keep hammering** a burned
session.

### Tab hygiene (required)

Use `scripts/yad2_cdp_tabs.py` (or import from `/root/work/yad2_cdp_tabs.py`):

- **One tab per batch worker** — sale and rent each reuse a saved tab id in
  `/tmp/yad2_scrape_tab.json`.
- **Prune on start**: `python3 yad2_cdp_tabs.py ensure rent` closes all other
  pages; `GET /json/close/{pageId}` to close extras manually if needed.
- **Captcha wait = poll only** — never `PUT /json/new` in a loop; navigate the
  existing tab in-place on recovery (`Page.navigate`).
- **Feed collection** uses the same tab with `Page.navigate` per results page.

## Deterministic bulk scrape (sale / rent)

Host requests fail. Details are fetched **in-page** via sync XHR on a live yad2 tab:

```
GET https://www.yad2.co.il/api/item/{token}
GET https://gw.yad2.co.il/ad-seen-count/{token}
# fallback: https://gw.yad2.co.il/realestate-item/{token}
```

### Architecture

| Piece | Role |
|-------|------|
| CDP `http://127.0.0.1:11222` | Talk to Chromium (`/json`, WebSocket `Runtime.evaluate`) |
| Feed collect | Navigate results pages; parse Next.js `dehydratedState` feed |
| `scrape_batch.js` | In-page batch worker; set `window.__SCRAPE_TOKENS__` first |
| `cdp_scrape_batch.py` | One batch: pick live tab → eval scrape → write `/tmp/batch_result.json` → apply |
| `next_scrape_batch.py` / `apply_scrape_batch.py` | Pending tokens + merge into JSON/CSV/MD |
| `yad2_cdp_tabs.py` | Single-tab CDP hygiene: prune, ensure, navigate in-place |
| `yad2_listing_fields.py` | Overlay feed + details; pick description / dates |
| `backfill_listing_gaps.py` | Sync master from details; re-scrape description/date gaps |
| `scrape_watchdog.py` | Loop batches; recover hung tabs / captcha / timeouts |

### Feed collection (results pages)

Known area codes (discover via UI if stale):

| Area | Code | Region path |
|------|------|-------------|
| תל אביב | 1 | `tel-aviv-area` |
| רמת גן | 3 | `tel-aviv-area` (area 3 = Ramat Gan + Givatayim; filter by `address.city.text`) |
| גבעתיים | 3 | `tel-aviv-area` |
| פתח תקווה | 4 | `center-and-sharon` |
| בני ברק | 78 | `center-and-sharon` |
| קרית אונו (בקעת אונו) | 10 | `center-and-sharon` |

URL patterns:

- Sale: `https://www.yad2.co.il/realestate/forsale/{region}?area=N&minPrice=…&maxPrice=…&page=P`
- Rent (whole apartments, not roommates): `https://www.yad2.co.il/realestate/rent/{region}?area=N&minPrice=…&page=P`
  — use `/rent`, not partners/rooms. Filter city in dehydrated items (`address.city.text`).

Extract listings from `script` tags containing `dehydratedState` → query
`realestate-rent-feed` / `realestate-forsale-feed` → `private` + `agency`
(+ platinum/booster). Wait for `document.readyState === complete` and non-empty
feed before parsing (dehydrated exists too early on SPA navigations). Paginate
until empty / past `totalPages`.

### Detail scrape loop

```bash
# From the job workdir (e.g. /root/work or /root/work/rent):
python3 scripts/scrape_watchdog.py --batch 40 --kind rent
# or without watchdog, one batch:
python3 cdp_scrape_batch.py 40
```

Watchdog behavior (always prefer this for long runs):

1. Run `cdp_scrape_batch.py N`.
2. On success: continue until `pending=0`.
3. On **captcha**: print viewer URL hint; **poll the one scrape tab** until clear
   (or timeout → exit 3 for human).
4. On **timeout / hung tab**: `Page.navigate` the same tab to `{forsale|rent}` base
   URL; probe live hostname; retry. Only create a tab if none exist.
5. On empty JSON / apply failure: rebuild from `window.__SCRAPE_LAST__` if present;
   else navigate same tab + retry (bounded).
6. Never POST scrape results from the browser to the host (mixed-content / hangs).
7. Return the **full** scrape payload in the same CDP evaluate that ran the batch
   (a second pull of `__SCRAPE_JSON__` can be empty).

### Hard-won pitfalls

- Prefer **newest** non-captcha results tab; probe with short CDP timeout first.
- Sync XHR in batches of ~40 is fine; keep CDP evaluate timeout ≥300s.
- Price text `"לא צוין מחיר"` → fall back to feed price.
- Do not import `cdp_scrape_batch` as a library without `if __name__` guard
  (module used to auto-run `main()`).

### Outputs (typical)

- `master_listings.json` — **merged listing table** (feed + details). Must include
  `description`, `date_advertised`, `date_last_seen_active`, `views`, `link`.
  Do not ship feed-only rows as the “listings” file.
- `listing_details.json` / `.csv` — same enriched rows (source of truth for merge)
- `apartments_for_sale.md` or `apartments_for_rent.md`
- `scrape_progress.json` — `{done, errors, total, updated_at}`

### Mandatory `description` (free text of the ad)

Every listing JSON object must have `description`: the full Hebrew ad body.

Sources, in order:
1. API `info_text` (and `metaData.description` if present) from
   `GET /api/item/{token}` or `gw.yad2.co.il/realestate-item/{token}`
2. If still empty: the item page DOM
   `document.querySelector('[data-testid="property-description"]')?.innerText`
   (class `description-module-scss-module__wvz9Ha__description`).
   Example: `https://www.yad2.co.il/realestate/item/tel-aviv-area/f80qt89w`

Do not truncate in JSON. CSV/MD may shorten for table width only.

Also always set:
- `date_advertised` — `dates.createdAt` / `date_added`
- `date_last_seen_active` — ISO time of this successful scrape
- `views` — `ad-seen-count` when available

## Sale↔rent yield (deterministic; no LLM)

Do **not** match listings in the model. After dumps are copied, run:

`python3 /home/s/opt/yad2/research/run.py`

A pair is a match only if **both**:

1. **Geolocation:** both have Nominatim `lat`/`lon` and haversine ≤ 600 m
2. **Features:** rooms ±0.5, sqm ±20%, elevator / ממ״ד / parking equal

Then `ratio = max(monthly rent among matches) × 12 / sale_price`. Same JSON in → same CSV out (token-sorted, stable ties).

## Interactive workflow (small searches)

1. `browser_navigate("https://www.yad2.co.il")` → snapshot.
2. Dismiss cookie/app overlays.
3. Category via nav: `נדל"ן` · `רכב` · `מוצרים` / `יד שנייה`.
4. Set filters → `חיפוש` / `הצג תוצאות`.
5. Read with `browser_read("main")`; paginate via interactive snapshot.

### Locations (autocomplete)

Type Hebrew place name → snapshot → **click** the suggestion (do not only Enter).

## Task: apartments for RENT

- Category `נדל"ן` → `דירות להשכרה` (`/realestate/rent`).
- Whole apartment = rent category (not חדרים/שותפים).
- Filters: location, `חדרים`, `מחיר` (min–max monthly), `סוג הנכס` (דירה / …).
- Bulk: deterministic feed + detail scrape + **watchdog**.

## Task: apartments to BUY

- Same as rent but `/realestate/forsale`. Price = purchase price.

## Task: used Mac / MacBook · cars

- Second-hand: `מוצרים` → laptops / `macbook`. Cars: `רכב` → `מכוניות`.

## Hebrew glossary

מכירה = for sale · השכרה = for rent · חדרים = rooms · מחיר = price ·
סוג הנכס = property type · עיר/אזור = city/area · חיפוש = search ·
סינונים נוספים = additional filters · מיין לפי = sort by · הבא = next ·
דירה = apartment · דירת גן = garden apt · פנטהאוז = penthouse · סטודיו = studio ·
חניה = parking · מעלית = elevator · ממ"ד = safe room · מרפסת = balcony ·
מרוהטת = furnished · משופצת = renovated · יד שנייה = second-hand · יצרן = brand ·
מצב = condition · משומש = used · מחשב נייד = laptop · שותפים = roommates.

## Tips

- RTL/Hebrew a11y names — match glossary terms.
- Controls = interactive_only snapshot; reading = text extraction.
- If results look empty, confirm location chip selected and category (rent vs sale).
- For long scrapes: start watchdog, monitor `scrape_progress.json`; only intervene
  for captcha via the mobile viewer.
