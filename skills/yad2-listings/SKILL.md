---
name: yad2-listings
description: >-
  Query Gush Dan Yad2 apartments via Supabase Postgres (listings, past_deals,
  tase_projects, tma38_projects (תמ״א / פינוי-בינוי; tma38_progress 1–10),
  For a listing or street, answer in Hebrew: rent range, yield, nearby ₪/m²,
  TASE/תמ״א 38, and a 1–10 bargain score table (10 = best deal).
  Scraping lives in chesignup/yad2-scraper. Gone sale → assumed_sold; gone rent →
  assumed_rented. Stale last_seen is not sold/rented.
---

# Yad2 listings — Supabase first

Repo: https://github.com/chesignup/yad2-listings  
Local: `/home/s/opt/yad2-listings`  
Scraper: https://github.com/chesignup/yad2-scraper

**Always query the connected Supabase Postgres (`public`).** Do not GitHub-search the multi-MB JSON dumps. Do not browse yad2.co.il / Nadlan / Google as a substitute. Do not conclude a listing is missing because GitHub search failed.

Refresh: `python3 /home/s/opt/yad2-listings/scripts/sync_supabase.py`  
Connection: `/home/s/opt/.env` (`host`, `port`, `database`, `user`, `p`).

Local fallback if SQL is down: `python3 scripts/lookup_listing.py TOKEN` or `--street גולומב`.

## Tables

| Table | PK | Contents |
|-------|----|----------|
| `listings` | `uid` | `kind` in sale / rent / office / yad1 / facebook. Yad2 item id = `uid`. Facebook: `fb-…`; matched Yad2 in `yad2_uid`. |
| `past_deals` | `deal_id` | Completed sales. `price_per_sqm`, `lat`/`lon`, `source_listing_url`. |
| `past_rentals` | `uid` | Delisted rent ads. `monthly_rent` = last ask (assumed closed). |
| `tma38_projects` | `id` | תמ״א / פינוי-בינוי (Maya + developer sites). `source_url` = company page; `progress_url` = latest TASE/muni doc; `tma38_progress` 1–10 (10=construction started). View `tase_projects` is the same table. |
| `tma38_project_progress_history` | `id` | Listing-shaped snapshot: `yad2_id` (= `listings.uid`), `street`, `house_number`, `lat`/`lon`, `tma38_progress`. One row per matching listing×project; unmatched projects have `yad2_id` null. |
| `tase_companies` | `id` | Public developers. |
| `manual_overrides` | `listing_uid` | Broker overlay (`payload` jsonb). Wins on conflict. |
| `mac_listings` | `uid` | MacBooks only. |

Useful `listings` columns: `city`, `street`, `house_number`, `rooms`, `sqm`, `floor`, `asking_price`, `price`, `monthly_rent`, `gross_yield`, `lat`, `lon`, `elevator`, `parking`, `mamad`, `new_building`, `tama38`, `tama38_probability`, `urban_renewal_likelihood`, `urban_renewal_stage`, `investment_score`, `past_deals_verdict`, `asking_vs_past_deals_discount_pct`, `url`, `listing_status`.

Distance: `haversine_m(lat1, lon1, lat2, lon2)` meters. Ignore city borders (תל אביב ↔ רמת גן ↔ גבעתיים ↔ בני ברק ↔ פתח תקווה).

URL → uid: `https://www.yad2.co.il/realestate/item/{region}/{uid}`

---

## Required answer format (listing or street)

When the user asks about a **listing**, **token**, **Yad2 URL**, or a **street**, run SQL first, then answer **in Hebrew**. This is for **every** sale listing / **every** street — not a one-off enrichment.

Always load **all** `tma38_projects` on that street (and within 400 m if geo exists). Do not stop at one famous developer. `source_url` is the company project page; `progress_url` is the latest TASE/muni/status link.

1. Four short Hebrew bullets (one line each):
   - **שכירות:** טווח חודשי ממודעות השכרה קרובות (פעילות **וגם** `assumed_rented` / `past_rentals`).
   - **תשואה:** `monthly_rent * 12 / asking_price` לפי אמצע טווח השכירות אם אין `gross_yield`.
   - **עסקה:** כן / מעורב / לא — לפי ציון המבצע.
   - **התחדשות עירונית / תמ״א 38:** כמה פרויקטים נמצאו ברחוב (ועד 400 מ׳). ציין יזם + `tma38_progress` (1–10, **10=הריסה/חפירה/בנייה החלה**, 9=היתר הוצא/טרום בנייה) + `tma38_progress_label` + `source_url`. אם אפס שורות: **אין ב־tma38_projects**.

2. **טבלת דירות** — שורה לכל דירת **מכירה** על הרחוב/החיפוש:

| קישור | מחיר | מ״ר | ₪/מ״ר | ₪/מ״ר עסקאות קרובות | שכירות ₪/חודש | תשואה | תמ״א 38 | ציון |

בתא **תמ״א 38** של כל דירה: פרויקט(ים) שמתאימים **לאותה דירה** (אותו רחוב, או ≤400 מ׳) — שם + יזם + ציון התקדמות + קישור `source_url`. אם כמה, קצר (עד 3) עם קישורים.

3. **טבלת פרויקטי התחדשות ברחוב** — חובה בכל שאילתת רחוב/דירה. שורה לכל שורת `tma38_projects` שמתאימה לרחוב (לא רק דוגמה אחת):

| פרויקט | יזם | רחוב | מס׳ | התקדמות 1–10 | משמעות הציון | קישור פרויקט | קישור התקדמות | סטטוס |

Column meaning (same data; Hebrew headers in the answer):

| Column | How to fill |
|--------|-------------|
| **קישור** | `listings.url` (full https). |
| **מחיר** | Asking `asking_price` or `price`. |
| **מ״ר** | `sqm`. |
| **₪/מ״ר** | `price / sqm` for this listing. |
| **₪/מ״ר עסקאות קרובות** | Median `past_deals.price_per_sqm` within **1.5 km**, similar size (rooms ±1, sqm ±25% if enough rows; else all geo-near). Quote n= count. |
| **שכירות ₪/חודש** | Min–max from nearby **rent** `listings` (any `listing_status`, including `assumed_rented`) **plus** `past_rentals.monthly_rent`, same geo + similar rooms/sqm. Note if only inactive. |
| **תשואה** | Midpoint rent × 12 / ask, as percent (e.g. 3.8%). |
| **תמ״א 38** | All matching `tma38_projects` for **this listing’s street** (ILIKE on `trim(street)`) **or** `haversine_m` ≤ 400 m: company + `tma38_progress` + `source_url`. Not a single hardcoded project. |
| **ציון** | Integer **1–10** (10 = העסקה הכי טובה). See rubric below. |

Optional extra columns: עיר, רחוב, חדרים.

Do not use the old English city\|street\|rooms\|sqm\|price\|url\|note-only table for these questions.

### Bargain score (1–10, 10 = best)

Start at **5**. Then:

- Ask ₪/m² vs nearby sold median: **−15% or cheaper → +3**; −8% to −15% → **+2**; −3% to −8% → **+1**; +3% to +8% → **−1**; +8% to +15% → **−2**; **+15% or more expensive → −3**.
- Gross yield: **≥4.5% → +2**; 3.5–4.5% → **+1**; **&lt;2.5% → −2**.
- `tase_projects` hit on same street / ≤400 m with a real approval stage → **+1** (do not add if only a weak name match).
- Clamp to 1–10. If comps or rent range is missing, cap at **6** and say which input is missing.

Never invent Nadlan/gov sale rows. If `lat`/`lon` is null, match by street + bordering cities and say so.

---

## SQL

Listing:

```sql
SELECT uid, kind, city, street, rooms, sqm, asking_price, monthly_rent, gross_yield,
       lat, lon, tama38_probability, urban_renewal_stage, url, listing_status
FROM listings WHERE uid = 'TOKEN';
```

Street (sales):

```sql
SELECT uid, city, street, rooms, sqm, asking_price, url, lat, lon, listing_status,
       tama38_probability, urban_renewal_stage, gross_yield
FROM listings
WHERE kind IN ('sale', 'yad1') AND street ILIKE '%גולומב%'
  AND COALESCE(listing_status, 'active') IN ('active', '');
```

Nearby sold ₪/m²:

```sql
SELECT p.price_per_sqm, p.rooms, p.sqm, p.sale_date, p.source_listing_url,
       haversine_m(s.lat, s.lon, p.lat, p.lon) AS distance_m
FROM listings s
JOIN past_deals p ON p.lat IS NOT NULL AND p.lon IS NOT NULL
WHERE s.uid = 'TOKEN' AND s.lat IS NOT NULL
  AND haversine_m(s.lat, s.lon, p.lat, p.lon) <= 1500
ORDER BY distance_m
LIMIT 40;
```

Nearby rents (live + gone):

```sql
SELECT r.uid, r.listing_status, r.rooms, r.sqm, r.monthly_rent, r.price, r.url,
       haversine_m(s.lat, s.lon, r.lat, r.lon) AS distance_m
FROM listings s
JOIN listings r ON r.kind = 'rent' AND r.lat IS NOT NULL
WHERE s.uid = 'TOKEN' AND s.lat IS NOT NULL
  AND haversine_m(s.lat, s.lon, r.lat, r.lon) <= 1500
UNION ALL
SELECT p.uid, 'assumed_rented', p.rooms, p.sqm, p.monthly_rent, p.monthly_rent, p.url,
       haversine_m(s.lat, s.lon, p.lat, p.lon)
FROM listings s
JOIN past_rentals p ON p.lat IS NOT NULL
WHERE s.uid = 'TOKEN' AND s.lat IS NOT NULL
  AND haversine_m(s.lat, s.lon, p.lat, p.lon) <= 1500;
```

תמ״א / TASE:

```sql
SELECT t.company_name, t.project_name, t.city, t.street, t.house_number,
       t.tma38_progress, t.source_url, t.progress_url, t.status_text,
       haversine_m(s.lat, s.lon, t.lat, t.lon) AS distance_m
FROM listings s
JOIN tma38_projects t ON char_length(trim(coalesce(t.street,''))) >= 3
WHERE s.uid = 'TOKEN'
  AND (
    t.street ILIKE '%' || trim(s.street) || '%'
    OR trim(s.street) ILIKE '%' || t.street || '%'
    OR (s.lat IS NOT NULL AND t.lat IS NOT NULL
        AND haversine_m(s.lat, s.lon, t.lat, t.lon) <= 400)
  );

SELECT company_name, project_name, street, house_number, tma38_progress,
       source_url, progress_url, status_text
FROM tma38_projects
WHERE street ILIKE '%STREET%'
ORDER BY tma38_progress DESC NULLS LAST;
```

Macs only: `SELECT title, price, city, condition, url FROM mac_listings WHERE listing_status = 'active';` — not this table.

## Live status

- `assumed_sold` — sale ad gone; last ask is the assumed close (`deal_source=assumed_delist`).
- `assumed_rented` — rent ad gone; last ask is closed rent (`past_rentals`).
- Stale last_seen alone is **not** sold or rented.

## Git dumps (not the catalog)

Scraper overwrite: `sale/` `rent/` `offices/` `past_deals/by_city/` `past_rentals/` `enriched/by_city/`. Broker notes only in `sale/manual_overrides.json`.
