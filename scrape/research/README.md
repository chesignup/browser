# Yad2 sale↔rent yield research

**No LLM.** Geocode + match are Python scripts so the agent does not spend
tokens comparing ads.

A sale/rent pair matches only if **both** hold:

1. **Geolocation** — both listings have `lat`/`lon`; haversine distance ≤ 600 m
2. **Features** — rooms ±0.5, size ±20% (min 15 m²), elevator / ממ״ד / parking equal

Then `ratio` = (highest matching monthly rent × 12) / sale price.
Ties: higher rent, then closer, then rent token. Table: highest ratio, then sale token.

## Tools

```bash
python3 geocode.py --in ../sale/listing_details.json --out ../sale/listings_geo.json
python3 run.py                  # geocode then match
python3 run.py --no-geocode     # match only
```

`watch-copy.sh` starts `run.py` when both scrapes report complete.

## Output

`sale_yield.csv` / `.json` / `.md` — sale price, yad2 link, sqm, rooms, tama %,
ratio, city, neighborhood, street, lat, lon, dates, views, broker (empty).
