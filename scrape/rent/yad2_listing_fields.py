#!/usr/bin/env python3
"""Shared listing field merge helpers (sale + rent)."""
from __future__ import annotations

DETAIL_OVERLAY_KEYS = (
    "description",
    "date_advertised",
    "date_last_seen_active",
    "views",
    "listing_id",
    "ad_number",
    "elevator",
    "mamad",
    "parking",
    "parking_raw",
    "tama38",
    "rented_for",
)

REQUIRED_LISTING_KEYS = ("description", "date_advertised", "date_last_seen_active")


def pick_description_from_api(api: dict) -> str:
    if not api:
        return ""
    for key in ("info_text", "description", "dom_description"):
        val = api.get(key)
        if val and str(val).strip():
            return str(val).strip()
    meta = api.get("metaData")
    if isinstance(meta, dict):
        val = meta.get("description")
        if val and str(val).strip():
            return str(val).strip()
    in_prop = api.get("inProperty")
    if isinstance(in_prop, dict):
        val = in_prop.get("description")
        if val and str(val).strip():
            return str(val).strip()
    return ""


def pick_date_advertised(api: dict) -> str:
    if not api:
        return ""
    for key in ("date_added", "date", "createdAt"):
        val = api.get(key)
        if val and str(val).strip():
            return str(val).strip()
    dates = api.get("dates")
    if isinstance(dates, dict):
        val = dates.get("createdAt")
        if val and str(val).strip():
            return str(val).strip()
    val = api.get("date_raw")
    if val and str(val).strip():
        return str(val).strip()
    dates = api.get("dates")
    if isinstance(dates, dict):
        val = dates.get("updatedAt")
        if val and str(val).strip():
            return str(val).strip()
    return ""


def overlay_details_on_feed(feed_items: list[dict], details_by_token: dict[str, dict]) -> list[dict]:
    by_token = {m["token"]: dict(m) for m in feed_items if m.get("token")}
    for token, detail in details_by_token.items():
        if token not in by_token:
            continue
        row = by_token[token]
        if detail.get("error"):
            row["error"] = detail["error"]
            continue
        for key in DETAIL_OVERLAY_KEYS:
            if key in detail:
                row[key] = detail[key]
        for key in ("price", "rooms", "sqm"):
            val = detail.get(key)
            if val not in (None, "", 0):
                row[key] = val
        if "listing_id" not in row or not row.get("listing_id"):
            row["listing_id"] = token
    for row in by_token.values():
        row.setdefault("description", "")
        row.setdefault("date_advertised", "")
        row.setdefault("date_last_seen_active", "")
        row.setdefault("views", None)
        if "listing_id" not in row or not row.get("listing_id"):
            row["listing_id"] = row.get("token")
    return sorted(
        by_token.values(),
        key=lambda x: (x.get("city") or "", x.get("price") or 0, x.get("token") or ""),
    )


def gap_tokens(details_by_token: dict[str, dict]) -> list[str]:
    gaps: list[str] = []
    for token, row in details_by_token.items():
        if row.get("error"):
            continue
        if not (row.get("description") or "").strip():
            gaps.append(token)
        elif not (row.get("date_advertised") or "").strip():
            gaps.append(token)
    return gaps
