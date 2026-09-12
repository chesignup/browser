FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir aiohttp

COPY scrape_marketplace.py merge_datasets.py entrypoint.sh /app/
RUN chmod +x /app/*.py /app/*.sh

ENV CDP_BASE=http://127.0.0.1:11222 \
    QUERY=macbook \
    MAX_ITEMS=50 \
    MAX_SCROLLS=10 \
    OUTPUT_DIR=/data/output \
    YAD2_PATH=/data/yad2/macbooks/macbook_listings.json

ENTRYPOINT ["/app/entrypoint.sh"]
