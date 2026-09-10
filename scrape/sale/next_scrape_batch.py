#!/usr/bin/env python3
"""Build a browser_eval expression for the next pending batch."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yad2_listing_fields import gap_tokens

ROOT = Path("/root/work")
ap = argparse.ArgumentParser()
ap.add_argument("batch", nargs="?", type=int, default=40)
ap.add_argument("--gap-only", action="store_true", help="only tokens missing description/date")
args = ap.parse_args()
BATCH = args.batch

master = json.loads((ROOT / "master_listings.json").read_text())
master_by_token = {m["token"]: m for m in master if m.get("token")}
done_path = ROOT / "listing_details.json"
done = {}
if done_path.exists():
    rows = json.loads(done_path.read_text())
    done = {r["token"]: r for r in rows if r.get("token")}

if args.gap_only:
    pending = gap_tokens(done)
else:
    pending = [m["token"] for m in master if m["token"] not in done or done[m["token"]].get("error")]
batch = pending[:BATCH]
links = {t: master_by_token[t]["link"] for t in batch if t in master_by_token and master_by_token[t].get("link")}
js = (ROOT / "scrape_batch.js").read_text()
expr = (
    "window.__SCRAPE_TOKENS__ = " + json.dumps(batch) + ";\n"
    + "window.__SCRAPE_LINKS__ = " + json.dumps(links) + ";\n"
    + js
)
out = Path("/tmp/next_scrape_expr.js")
out.write_text(expr)
meta = {"batch_size": len(batch), "pending_before": len(pending), "tokens": batch, "expr_path": str(out), "expr_bytes": len(expr)}
Path("/tmp/next_scrape_meta.json").write_text(json.dumps(meta, ensure_ascii=False))
print(json.dumps(meta))
