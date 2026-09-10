# Scooped yad2 listings (host copy)

Canonical dumps from `cursor-agent` via `/home/s/opt/yad2/watch-copy.sh`.

- `sale/listing_details.json` / `master_listings.json` — for-sale ads (description, dates, views)
- `rent/listing_details.json` / `master_listings.json` — for-rent ads
- `*/listings_geo.json` — same rows plus Nominatim `lat`/`lon` when geocoded
- Yield matching is **not** done by an LLM: `scrape/research/match_yield.py` requires **geolocation distance AND feature similarity**.

Do not hand-match these in chat; run `python3 scrape/research/run.py --yad2 data/yad2`.
