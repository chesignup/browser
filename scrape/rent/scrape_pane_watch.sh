#!/usr/bin/env bash
# Refresh scrape dashboard every 30s (for tmux pane).
set -euo pipefail
ROOT="/root/work/rent"
while true; do
  clear
  python3 "$ROOT/scrape_pane.py" 2>/dev/null || echo "scrape_pane.py failed"
  echo
  echo "(refresh every 30s — Ctrl+C to stop pane only)"
  sleep 30
done
