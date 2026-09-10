#!/usr/bin/env python3
"""Score תמ״א / urban-renewal potential 0–100 from listing text + amenities."""
from __future__ import annotations

import re

NEW_BUILD = re.compile(
    r"בניין\s*חדש|בנין\s*חדש|חדשה?\s*מקבלן|פרויקט\s*חדש|אכלוס\s*מיידי|"
    r"חדשה?\s*מהניילון|חדשה?\s*מהנילונים|בניין\s*בוטיק\s*חדש|גמור\s*ברמה",
    re.I,
)
TAMA_DONE = re.compile(
    r"לאחר\s*תמ[\"'״׳]?א|אחרי\s*תמ[\"'״׳]?א|תמ[\"'״׳]?א\s*38\s*הושלם|"
    r"כבר\s*בוצע|עבר\s*תמ[\"'״׳]?א",
    re.I,
)
TAMA_ACTIVE = re.compile(
    r"תמ[\"'״׳]?א\s*38|תמא\s*38|tama\s*38|התחדשות\s*עירונית|פינוי[-\s]*בינוי",
    re.I,
)
HAPPENING = re.compile(
    r"בביצוע|אושר(ה)?|היתר(\s*בנייה)?|בהליך|בהליכים|התחיל|"
    r"יצא\s*לפועל|בקרוב\s*מאוד|חתמ(ו|נו)|100\s*%|"
    r"תב\"ע\s*מאושרת|תב״ע\s*מאושרת",
    re.I,
)
POTENTIAL = re.compile(
    r"פוטנציאל|עתיד(י|ית)?|מתוכנן|בתהליך|תב\"ע|תב״ע|יזם|התארגנות",
    re.I,
)


def tama_potential_pct(row: dict) -> int:
    """0 = already new / TAMA done; 100 = clearly underway."""
    desc = row.get("description") or ""
    elev = bool(row.get("elevator"))
    mamad = bool(row.get("mamad"))

    if NEW_BUILD.search(desc) or TAMA_DONE.search(desc):
        return 0
    # User rule: elevator + ממ״ד is the signature of a building that already
    # went through renewal (or was built new). Treat as 0 unless the text
    # still talks about an active TAMA process (rare 2nd phase).
    if elev and mamad and not TAMA_ACTIVE.search(desc):
        return 0

    if TAMA_ACTIVE.search(desc) and HAPPENING.search(desc):
        return 100
    if TAMA_ACTIVE.search(desc) and POTENTIAL.search(desc):
        return 70
    if TAMA_ACTIVE.search(desc):
        return 55
    if POTENTIAL.search(desc) and not (elev and mamad):
        return 40
    if not elev and not mamad:
        return 25
    if elev and not mamad:
        return 15
    return 10
