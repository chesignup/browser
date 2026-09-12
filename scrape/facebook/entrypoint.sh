#!/bin/bash
set -e

QUERY="${QUERY:-macbook}"
MAX_ITEMS="${MAX_ITEMS:-50}"
MAX_SCROLLS="${MAX_SCROLLS:-10}"
CDP_BASE="${CDP_BASE:-http://127.0.0.1:11222}"
OUTPUT_DIR="${OUTPUT_DIR:-/data/output}"
YAD2_PATH="${YAD2_PATH:-/data/yad2/macbooks/macbook_listings.json}"

echo "=================================================="
echo "Facebook Marketplace Deterministic Scraper Starting"
echo "  Query:       $QUERY"
echo "  Max items:   $MAX_ITEMS"
echo "  Max scrolls: $MAX_SCROLLS"
echo "  CDP Base:    $CDP_BASE"
echo "  Output Dir:  $OUTPUT_DIR"
echo "  Yad2 Source: $YAD2_PATH"
echo "=================================================="

mkdir -p "$OUTPUT_DIR/facebook" "$OUTPUT_DIR/macbooks"

echo "[1/2] Scraping Facebook Marketplace for: $QUERY..."
python3 /app/scrape_marketplace.py \
  --query "$QUERY" \
  --max-items "$MAX_ITEMS" \
  --max-scrolls "$MAX_SCROLLS" \
  --output-dir "$OUTPUT_DIR/facebook" \
  --cdp-base "$CDP_BASE"

echo "[2/2] Merging with Yad2 Mac dataset..."
if [ -f "$YAD2_PATH" ]; then
  python3 /app/merge_datasets.py \
    --yad2 "$YAD2_PATH" \
    --facebook "$OUTPUT_DIR/facebook/facebook_${QUERY}_listings.json" \
    --output-dir "$OUTPUT_DIR/macbooks" \
    --dataset-basename "comprehensive_macbooks"
    
  # Also copy to Yad2 directory if available
  if [ -d "/data/yad2/macbooks" ]; then
    cp -fv "$OUTPUT_DIR/macbooks/comprehensive_macbooks"* "/data/yad2/macbooks/" 2>/dev/null || true
    cp -fv "$OUTPUT_DIR/macbooks/COMPREHENSIVE_MACBOOKS.md" "/data/yad2/macbooks/" 2>/dev/null || true
  fi
else
  echo "Warning: Yad2 dataset not found at $YAD2_PATH, skipping merge."
fi

echo "=================================================="
echo "Scraping & Merge Complete!"
echo "=================================================="
