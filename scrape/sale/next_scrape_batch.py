#!/usr/bin/env python3
"""Build a browser_eval expression for the next pending batch."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/root/work")
BATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 40

master = json.loads((ROOT / "master_listings.json").read_text())
done_path = ROOT / "listing_details.json"
done = {}
if done_path.exists():
    rows = json.loads(done_path.read_text())
    done = {r["token"]: r for r in rows if r.get("token")}

pending = [m["token"] for m in master if m["token"] not in done or done[m["token"]].get("error")]
batch = pending[:BATCH]
js = (ROOT / "scrape_batch.js").read_text()
# strip block comment header to shrink a bit
expr = "window.__SCRAPE_TOKENS__ = " + json.dumps(batch) + ";\n" + js
out = Path("/tmp/next_scrape_expr.js")
out.write_text(expr)
meta = {"batch_size": len(batch), "pending_before": len(pending), "tokens": batch, "expr_path": str(out), "expr_bytes": len(expr)}
Path("/tmp/next_scrape_meta.json").write_text(json.dumps(meta, ensure_ascii=False))
print(json.dumps(meta))
