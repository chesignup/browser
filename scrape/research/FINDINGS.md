# Sale vs nearby rent — findings

Matching is **deterministic**: a pair counts only if both have coordinates,
haversine ≤ 600 m, rooms ±0.5, size ±20%, and the same elevator / ממ״ד / parking.
`ratio` = (highest matching monthly rent × 12) / sale price. Sorted high → low.

## Scale

- Sales that found at least one similar nearby rental: **1709**
- Gross yield (ratio): min 2.88%, median 3.88%, p90 5.52%, max 7500.00%
- Mean yield: 41.18%
- Plausible band (1–12% gross, typical IL): **1667** sales, median 3.85%, p90 5.13%
- **42** rows outside 1–12% (often a bad price: sale too low or rent not monthly). Treat top-of-list with suspicion.

## By city (median yield, count)

| city | n | median yield | p90 | max |
|------|--:|-------------:|----:|----:|
| תל אביב יפו | 504 | 4.36% | 8.17% | 7500.00% |
| רמת גן | 334 | 3.86% | 4.80% | 6.96% |
| קרית אונו | 19 | 3.84% | 4.43% | 4.52% |
| פתח תקווה | 576 | 3.74% | 4.65% | 10.24% |
| בני ברק | 200 | 3.70% | 4.44% | 984.00% |
| גבעתיים | 76 | 3.59% | 4.17% | 5.83% |

## תמ״א potential (heuristic on ad text)

- 0%: 565 sales
- 10%: 7 sales
- 15%: 281 sales
- 25%: 339 sales
- 40%: 140 sales
- 55%: 162 sales
- 70%: 168 sales
- 100%: 47 sales


## Highest plausible yields (1–12% band)

| yield | price | rent/mo | dist | rooms | sqm | tama% | address | sale | rent |
|------:|------:|--------:|-----:|------:|----:|------:|---------|------|------|
| 11.76% | 1990000 | 19500 | 263m | 4.0 | 95 | 0 | אלוף דן לנר 4 / נווה אליעזר וכפר שלם מזרח / תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/hx25iwvg | https://www.yad2.co.il/realestate/item/tel-aviv-area/zb3aw9vx |
| 11.45% | 1100000 | 10500 | 125m | 2.5 | 70 | 25 | מטלון / נווה שאנן / תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/wpy8picn | https://www.yad2.co.il/realestate/item/tel-aviv-area/xjuq81cj |
| 10.63% | 790000 | 7000 | 363m | 3.0 | 68 | 0 | נווה שאנן / תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/2z9qoxij | https://www.yad2.co.il/realestate/item/tel-aviv-area/ocie0vza |
| 10.24% | 1640000 | 14000 | 236m | 4.0 | 80 | 55 | רמב"ם / עין גנים / פתח תקווה | https://www.yad2.co.il/realestate/item/center-and-sharon/1aq1cw0f | https://www.yad2.co.il/realestate/item/center-and-sharon/obdritu6 |
| 9.79% | 2390000 | 19500 | 263m | 4.0 | 94 | 0 | נווה ברבור, כפר שלם מערב / תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/tdl16bdq | https://www.yad2.co.il/realestate/item/tel-aviv-area/zb3aw9vx |
| 9.77% | 1720000 | 14000 | 453m | 4.0 | 80 | 55 | עין גנים / פתח תקווה | https://www.yad2.co.il/realestate/item/center-and-sharon/oo2a7r0s | https://www.yad2.co.il/realestate/item/center-and-sharon/obdritu6 |
| 9.66% | 2235000 | 18000 | 0m | 3.0 | 87 | 0 | תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/p11digyt | https://www.yad2.co.il/realestate/item/tel-aviv-area/9yol644c |
| 9.60% | 1750000 | 14000 | 545m | 3.5 | 87 | 70 | עין גנים 41 / עין גנים / פתח תקווה | https://www.yad2.co.il/realestate/item/center-and-sharon/oxz060k7 | https://www.yad2.co.il/realestate/item/center-and-sharon/obdritu6 |
| 9.55% | 1760000 | 14000 | 196m | 3.5 | 84 | 40 | יהודה הלוי / פתח תקווה | https://www.yad2.co.il/realestate/item/center-and-sharon/a675iga2 | https://www.yad2.co.il/realestate/item/center-and-sharon/obdritu6 |
| 9.39% | 1790000 | 14000 | 386m | 3.5 | 83 | 25 | פתח תקווה | https://www.yad2.co.il/realestate/item/center-and-sharon/gz7r5546 | https://www.yad2.co.il/realestate/item/center-and-sharon/obdritu6 |
| 9.23% | 1820000 | 14000 | 524m | 4.0 | 80 | 25 | ברקוביץ' / לב המושבה / מרכז העיר / פתח תקווה | https://www.yad2.co.il/realestate/item/center-and-sharon/i0xfzht2 | https://www.yad2.co.il/realestate/item/center-and-sharon/obdritu6 |
| 9.23% | 1820000 | 14000 | 386m | 4.0 | 90 | 25 | פתח תקווה | https://www.yad2.co.il/realestate/item/center-and-sharon/r2zf6vim | https://www.yad2.co.il/realestate/item/center-and-sharon/obdritu6 |
| 9.18% | 1700000 | 13000 | 327m | 3.0 | 75 | 15 | ליברמן / הצפון הישן - החלק הצפוני / תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/71exjbac | https://www.yad2.co.il/realestate/item/tel-aviv-area/ce3gf6d4 |
| 9.08% | 1850000 | 14000 | 164m | 4.0 | 95 | 55 | ליפה ויניצקי / המרכז השקט / מרכז העיר / פתח תקווה | https://www.yad2.co.il/realestate/item/center-and-sharon/o2bnd66s | https://www.yad2.co.il/realestate/item/center-and-sharon/obdritu6 |
| 9.03% | 1860000 | 14000 | 535m | 4.5 | 100 | 25 | רמב"ם 6 / לב המושבה / מרכז העיר / פתח תקווה | https://www.yad2.co.il/realestate/item/center-and-sharon/8on0ec3a | https://www.yad2.co.il/realestate/item/center-and-sharon/obdritu6 |

## Highest raw yields (includes bad prices — do not use as-is)

| yield | price | rent/mo | dist | rooms | sqm | tama% | address | sale | rent |
|------:|------:|--------:|-----:|------:|----:|------:|---------|------|------|
| 7500.00% | 568000 | 3550000 | 0m | 3.0 | 77 | 0 | תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/ueyptifu | https://www.yad2.co.il/realestate/item/tel-aviv-area/0ncnu9yg |
| 7333.33% | 18000 | 110000 | 0m | 5.0 | 230 | 0 | הגוש הגדול, רמת אביב החדשה, נופי ים / תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/lp4a9krb | https://www.yad2.co.il/realestate/item/tel-aviv-area/ep9k14dg |
| 3840.00% | 10000 | 32000 | 487m | 5.0 | 150 | 0 | קרליבך / גני שרונה, קרית הממשלה / תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/jdgw96du | https://www.yad2.co.il/realestate/item/tel-aviv-area/iq08tfpo |
| 2622.75% | 1670000 | 3650000 | 0m | 2.5 | 53 | 55 | תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/m01c0u3p | https://www.yad2.co.il/realestate/item/tel-aviv-area/wxhvuuq6 |
| 2446.93% | 1790000 | 3650000 | 0m | 3.0 | 65 | 70 | נווה גולן, יפו ג' / תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/c59u6sj4 | https://www.yad2.co.il/realestate/item/tel-aviv-area/wxhvuuq6 |
| 2446.93% | 1790000 | 3650000 | 0m | 3.0 | 60 | 55 | נווה גולן, יפו ג' / תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/kucnfh1w | https://www.yad2.co.il/realestate/item/tel-aviv-area/wxhvuuq6 |
| 2367.57% | 1850000 | 3650000 | 0m | 3.0 | 60 | 55 | תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/amf2n2q9 | https://www.yad2.co.il/realestate/item/tel-aviv-area/wxhvuuq6 |
| 2317.46% | 1890000 | 3650000 | 0m | 3.0 | 55 | 100 | תל אביב יפו | https://www.yad2.co.il/realestate/item/tel-aviv-area/xyl2owqv | https://www.yad2.co.il/realestate/item/tel-aviv-area/wxhvuuq6 |

## How to read this

- **~4%** is 8,000 ₪/mo × 12 / 2,300,000 ₪ — a typical “can rent cover the price?” check.
- Using the **max** nearby similar rent **optimistic**; one expensive rental can lift many sales.
- 600 m + amenity match can still mix streets; check the two links before acting.
- No broker field in the scrape (`broker` column is empty).
- תמ״א % is from Hebrew free text + elevator/ממ״ד, not a legal file.

