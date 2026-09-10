# Yad2 scrape pipeline

Deterministic CDP scrapers (host HTTP to yad2 is blocked). Run with the guest
Chrome CDP available at `127.0.0.1:11222` (host tunnel or inside the agent).

## Rent

```bash
cd scrape/rent
python3 ../yad2_cdp_tabs.py ensure rent
python3 collect_rent_feeds.py          # builds master_listings.json
python3 scrape_watchdog.py --workdir . --kind rent --batch 40
```

## Sale

```bash
cd scrape/sale
python3 ../yad2_cdp_tabs.py ensure sale
python3 collect_yad2_feeds.py
python3 scrape_watchdog.py --workdir . --kind sale --batch 40
```

Shared helpers: `yad2_listing_fields.py` (description / dates / views merge),
`../yad2_cdp_tabs.py`, skill copy under `skills/yad2/scripts/`.
Captcha: open the mobile viewer; watchdog polls the single scrape tab.

Host copy of live dumps: `/home/s/opt/yad2/watch-copy.sh` (also `scrape/watch-copy.sh`).
Copies `master_listings.json` + `listing_details.*` on every progress change.
