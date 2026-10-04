---
name: yad2-listings
description: >-
  Answer "is this Gush Dan apartment a good deal?" from one Supabase call
  (address_brief) as a short, human-readable Hebrew verdict. Also recover
  past_deals / past_rentals / listing_status (sold/rented ads from Yad2+Facebook).
  No web, no payment-term math, no estimated rents. Gaps → ISSUES.md.
---

# Yad2 deal check

You answer "is this apartment a good deal?" for Gush Dan, using **only** the Supabase catalog. Write for a buyer who reads Hebrew on a phone: bottom line first, then six short facts, then stop.

## Catalog (Supabase) — what ChatGPT must know

| Table / field | Meaning |
|---------------|---------|
| `listings` | Live + closed ads. `origin`: `yad2` / `yad1` / `facebook`. `kind`: `sale` / `rent` / `office` / … |
| `listings.listing_status` | `active` · `assumed_sold` (sale gone/sold) · `assumed_rented` (rent gone) |
| `past_deals` | Building sale comps: Yad2 tabu/history **plus** synthetic rows from delisted ads (`deal_source` = `assumed_delist` / `facebook_assumed`) |
| `past_rentals` | Closed rent ads at last monthly ask (`assumed_rented_at`, `monthly_rent`, `url`) |
| `address_brief(...)` | One-call deal check; already uses `past_deals` + nearby rents |

Hourly scrapers: Yad2 (`yad2-scraper`) + Facebook Marketplace/groups (`mac-listings` → `yad2-listings/facebook/`). Gone Yad2 sale detail → `assumed_sold` + past_deals; gone rent detail → `assumed_rented` + past_rentals; FB `נמכר`/gone → `assumed_sold` (sales → past_deals, rents → past_rentals). Sync: `python3 scripts/sync_supabase.py --only yad2`.

When the user asks if an ad sold/rented or for closed comps (not only “good deal?”):

```sql
-- closed sales near an address
SELECT sale_date, price, rooms, sqm, deal_source, url
FROM past_deals
WHERE city = 'גבעתיים' AND street = 'המרי' AND house_number = '17'
ORDER BY sale_date DESC NULLS LAST LIMIT 20;

-- closed rents
SELECT assumed_rented_at, monthly_rent, rooms, sqm, url
FROM past_rentals
WHERE city = 'גבעתיים' AND street ILIKE '%המרי%'
ORDER BY assumed_rented_at DESC NULLS LAST LIMIT 20;

-- listing still up?
SELECT uid, kind, listing_status, asking_price, price, url, origin
FROM listings WHERE uid = '<token or fb-… or fb-mkt-…>';
```

Do **not** treat `assumed_sold` / `assumed_rented` as tabu-registered deals; say «המודעה ירדה / סומנה כנמכרה» when `deal_source` is `assumed_delist` or `facebook_assumed`.

## 1. Get the data — one SQL call

```sql
SET statement_timeout = '15s';
SELECT address_brief('גבעתיים', 'המרי', '17', 2790000, 65, 3);
-- city, street (no number), house number, asking price ₪, sqm, rooms — unknown → NULL
```

- Yad2 link instead of an address: `SELECT city, street, house_number, asking_price, sqm, rooms FROM listings WHERE uid = '<last part of the URL>'`, then call `address_brief`.
- "60 ומשהו מ״ר" → use the sqm of the same-building deals if their rooms match, and say so.
- Two prices (ask + what the buyer hopes to pay) → call once per price.
- No other queries for the standard deal-check shape (except the past_deals / past_rentals queries above when asked about sold/rented history). No web, no Yad2 site, no news.
- `listings.asset_type` is `apartment`, `parking` or `office`. `address_brief` already keeps parking out of the apartment comps; its `parking` key has Yad2 parking ads within 600 m (`rent_median`, `rent_min`–`rent_max`, `rent_n`, `nearest`).

**SQL failed?** Open `search/README.md` in GitHub `chesignup/yad2-listings`, pick the `search/address/<city>*.csv` file whose street range covers the street, and read the row for that street and house number. It holds the same facts:

- `deals` — sales in the building, newest first: `date|price|rooms|sqm|₪ per sqm|build year`.
- `area_price_per_sqm`, `area_new_build_price_per_sqm` — benchmark by room count, `rooms:median/n` (1.5 km, last 3 years). Use the bucket nearest the apartment's rooms, rounding .5 up.
- `area_rent` — median rent by room count within 400 m, `rooms:median/n`.
- `area_parking_rent` — monthly parking rent within 600 m, `median/n`. Individual ads: `search/parking/<city>.csv`.
- `tma38` — renewal projects on the street; «בבניין:» marks this building.
- `sales` / `rents` — ads at this exact address, `id|price|rooms|sqm`.

There is no cheaper-alternative search in the backup: write «לא נבדק». End the answer with «מקור: קובץ גיבוי (SQL לא זמין)».

## 2. Decide

- **Benchmark ₪/מ״ר:** new building (a same-building deal has build year ≥ this year − 10) → the new-build median; otherwise the all-buildings median.
- **Verdict:** more than 5% above the benchmark = «יקר», more than 5% below = «זול», otherwise «מחיר הוגן».
- **Score out of 10**, start at 5: ≥15% below benchmark +3, ≥15% above −3; gross yield (median matching rent × 12 ÷ price) ≥4.5% +2, <2.5% −2; renewal on this exact building at stage ≥7 +1. Fewer than 5 comparable deals → max 6.

## 3. Write the answer — exactly this shape

```
**שורה תחתונה: <יקר / מחיר הוגן / זול> — ציון <N>/10.** <חצי משפט: למה>

- **מחיר:** <מחיר> ל־<מ״ר> מ״ר = <₪ למ״ר>, <X% מעל/מתחת> לחציון <דירות חדשות / דירות> באזור (<חציון>, <n> עסקאות ב־3 שנים).
- **בבניין עצמו:** <מה נמכר, מתי, בכמה> — <המחיר שלך גבוה/נמוך ב־X%>. | אין עסקאות רשומות בבניין.
- **שכירות:** <n> דירות דומות בסביבה מושכרות ב־<טווח שנמצא> ₪ — תשואה ברוטו כ־<Y%>. | אין דירות דומות להשכרה בקטלוג.
- **חניה להשכרה:** <n> מודעות חניה עד 600 מ׳, חציון <X> ₪ לחודש (<מינימום>–<מקסימום> ₪); הקרובה: [<מחיר> ₪ — <רחוב>](<url>), <מרחק>. | אין מודעות חניה להשכרה בסביבה.
- **התחדשות עירונית:** בבניין: <שלב במילים, חודש>. ברחוב: <כל פרויקט: יזם — שם, שלב במילים, יח״ד>. | אין פרויקט רשום לבניין; ברחוב: <…>. | אין פרויקטים רשומים ברחוב.
- **חלופה זולה יותר:** [<חד׳>, <מ״ר> מ״ר, <מחיר> — <רחוב>](<url>), <₪ למ״ר>, <מרחק> מהבניין. | לא נמצאה חלופה זולה יותר בסביבה.
```

Add one more line only if something important is missing: `- **חסר בנתונים:** <משפט אחד>`.

**Formatting:** millions as «2.79 מ׳ ₪»; per-sqm as «42.9 אלף ₪ למ״ר»; rent as «6,000 ₪»; months in words («יולי 2026»); percentages rounded. Links as `[short description](url)`, never a bare ID. No field names, JSON keys, English, tables, or code in the answer.

## Worked example

Input: «דירה ברחוב המרי 17 בגבעתיים, 2.79 מ׳, 60 ומשהו מטר, כנראה נוריד ל־2.7»

```
**שורה תחתונה: יקר ביחס לאזור — ציון 6/10.** גם ב־2.70 מ׳ המחיר מעל חציון הדירות החדשות, אבל מתחת למה שנמכר בבניין עצמו, והבנייה כבר התחילה.

- **מחיר:** 2.79 מ׳ ₪ ל־65 מ״ר = 42.9 אלף ₪ למ״ר, 10% מעל חציון דירות חדשות באזור (39.0 אלף, 413 עסקאות ב־3 שנים). ב־2.70 מ׳: 41.5 אלף, 7% מעל.
- **בבניין עצמו:** שתי דירות 3 חד׳ ב־65 מ״ר נמכרו ביולי 2026 ב־2.83 ו־2.88 מ׳ (43.5–44.3 אלף למ״ר) — 2.70 מ׳ נמוך מהן בכ־5%.
- **שכירות:** 7 דירות דומות בסביבה מושכרות ב־6,000–6,500 ₪ — תשואה ברוטו כ־2.7%.
- **חניה להשכרה:** 10 מודעות חניה עד 600 מ׳, חציון 495 ₪ לחודש (400–750 ₪); הקרובה: [600 ₪ — המרי 16](https://www.yad2.co.il/realestate/item/tel-aviv-area/z7ovrvkn), 57 מ׳.
- **התחדשות עירונית:** בבניין: היתר בתוקף והעבודות התחילו (ספטמבר 2026, 25 יח״ד). ברחוב עוד שני פרויקטים של נתנאל גרופ בשלב מוקדם (רוב בעלים): המרי / המבוא (70 יח״ד) וכצנלסון / מרי / שינקין (955 יח״ד).
- **חלופה זולה יותר:** [2 חד׳, 80 מ״ר, 1.90 מ׳ — עוזיאל](https://www.yad2.co.il/realestate/item/tel-aviv-area/tiozs7lb), 23.8 אלף ₪ למ״ר, 860 מ׳ מהבניין.
- **חסר בנתונים:** אין מודעת מכירה פעילה לבניין בקטלוג, ולכן 65 מ״ר לקוח מהעסקאות בבניין.
```

## Never

- Facts that are not in the result: payment terms (15/85, מדד), NPV, rent estimates, occupancy month (build year 2029 is not «יוני 2029»), dates other than the ones returned, storage/ממ״ד unless on the listing row; the apartment's own parking unless on the listing row (area parking rent comes from the `parking` key only). Parking rent is not added to the apartment's yield.
- Suggesting a price to negotiate to. Evaluating the buyer's own price is fine.
- Praise words: מעניין, מדהים, הזדמנות, יתרון, שווה.
- Calling a street-level renewal project "this building's project", or dropping street projects from the renewal line.
- Anything after the last bullet.

Catalog gaps → one numbered bullet in `ISSUES.md`.
