# Yad2 sale↔rent yield research

Runs **after** `watch-copy.sh` has both sale and rent dumps. Geocodes every
listing (Nominatim, cached), then matches each **sale** to nearby **rentals**
with similar rooms / size / elevator / ממ״ד / parking.

`ratio` = (highest matching monthly rent × 12) / sale price.
Sorted **highest ratio first**.

## Tools

```bash
# Geocode a JSON array of listings (adds lat, lon). Cache: geo_cache.json
python3 /home/s/opt/yad2/research/geocode.py \
  --in /home/s/opt/yad2/sale/listing_details.json \
  --out /home/s/opt/yad2/sale/listings_geo.json

# Full pipeline (geocode sale+rent, then yield table)
python3 /home/s/opt/yad2/research/run.py

# Match only (if listings_geo.json already exists)
python3 /home/s/opt/yad2/research/run.py --no-geocode
```

`watch-copy.sh` starts this automatically once both scrapes report `done+errors >= total`.

## Matching defaults

| Rule | Default |
|------|---------|
| Distance | ≤ 600 m (haversine) |
| Rooms | ± 0.5 |
| Size | ± 20% (min 15 m²) |
| Elevator / ממ״ד / parking | must match when both sides have the flag |
| Several rents fit | take **max** monthly rent |
| One rent, many sales | allowed (star edges) |

## Output columns (`research/sale_yield.csv`)

sale price, full yad2 link, sqm, rooms, תמ״א potential % (from description;
100 = clearly underway, 0 = already new / elevator+ממ״ד), ratio, city,
neighborhood, street, lat, lon, last seen, advertised, views, broker
(empty — yad2 dumps have no broker field), plus rent used / distance / match count.

תמ״א % is a heuristic on Hebrew free text, not a legal status.
