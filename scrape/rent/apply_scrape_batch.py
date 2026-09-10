#!/usr/bin/env python3
"""Apply rent scrape batch into listing_details / csv / md."""
from __future__ import annotations
import json, sys
from pathlib import Path
from scrape_listing_details import MASTER, load_details, merge_batch, merge_master, pending_tokens

ROOT = Path("/root/work/rent")


def main():
    if len(sys.argv) < 2:
        print("usage: apply_scrape_batch.py <batch.json|->", file=sys.stderr)
        sys.exit(2)
    src = sys.argv[1]
    raw = sys.stdin.read() if src == "-" else Path(src).read_text()
    payload = json.loads(raw)
    if isinstance(payload, str):
        payload = json.loads(payload)
    results = payload.get("results") or payload
    if not isinstance(results, list):
        print("bad payload", type(payload), file=sys.stderr)
        sys.exit(1)
    master = json.loads(MASTER.read_text()) if MASTER.exists() else merge_master()
    feed = {m["token"]: m for m in master}
    done = load_details()
    merge_batch(feed, done, results)
    pending = pending_tokens(master, done)
    print(json.dumps({
        "batch_ok": payload.get("ok"),
        "batch_errors": payload.get("errors"),
        "done": len([d for d in done.values() if not d.get("error")]),
        "errors_total": len([d for d in done.values() if d.get("error")]),
        "pending": len(pending),
        "total": len(master),
    }))


if __name__ == "__main__":
    main()
