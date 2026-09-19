---
name: browser-vm-remote
description: >-
  Control Chromebox Chrome from the listings research container via gbrowser
  (CDP over Tailscale). Use for captcha HITL and live listing checks. On Yad2
  Radware/Press & Hold captcha: STOP probing — hand off to the human via the
  mobile viewer (http://100.92.122.70:6081/), wait, then resume the same tab.
  Before showing any Yad2/Facebook listing to the user, live-check and persist
  status (live-check-listing / live_check_listing.py). FB item URLs often
  redirect to search — inconclusive until /marketplace/item/<id> is in location.href.
---

# browser-vm-remote — drive chromebox via `gbrowser`

Workspace: `/root/work`. Chromebox: `100.92.122.70`.

## First: reachability

```bash
gbrowser tunnel status      # expect: alive
# if down: gbrowser tunnel up
```

## Commands

| Goal | Command |
|------|---------|
| Go to URL | `gbrowser ctl nav https://example.com` |
| List tabs | `gbrowser ctl list` |
| HTML | `gbrowser ctl html` |
| Accessibility tree | `gbrowser ctl snap` |
| Evaluate JS | `gbrowser ctl eval "document.title"` |
| Screenshot | `gbrowser ctl shot /tmp/shot.png` |
| Click | `gbrowser ctl click "…"` / `ctl clickxy 640 400` |

## Captcha → human-in-the-loop (MANDATORY)

Yad2 (and sometimes Facebook) shows Radware Bot Manager. Agents **cannot** clear
it by re-navigating, opening new tabs, or hammering `eval`.

### Detect

Any of these means captcha / bot wall:

- Title or body: `Press & Hold`, `Are you human`, `אני לא רובוט`, `Radware`
- URL: `validate.perfdrive`, `captcha`
- `gbrowser ctl eval` / nav fails with empty body or challenge HTML
- CDP returns captcha / connection closed mid-scrape after challenge

### Required agent behavior

1. **STOP** — do not `nav` again, do not open another Yad2 tab, do not retry in a loop.
2. Prefer **one** existing Yad2 (or Facebook) tab; leave it on the challenge page.
3. **Tell the user immediately** (chat message), with the viewer URL:

   > Yad2 is behind a captcha. Please open the Chromebox viewer and complete
   > Press & Hold / אני לא רובוט on the open tab:
   > **http://100.92.122.70:6081/**
   >
   > Reply here when done — I will resume the same tab.

4. Optional helpers (do not replace the user message):

```bash
gbrowser ctl list
gbrowser ctl eval '(document.title||"") + " | " + (location.href||"")'
# Screenshot for the user if useful:
gbrowser ctl shot /tmp/captcha.png
```

5. **Wait** for the user to confirm the captcha is cleared (or poll gently every
   ~30–60s with a single `eval` of `document.title` / body snippet — max a few
   times — while waiting on the user). Do **not** spam nav.
6. After clear: resume the **same** tab (`gbrowser ctl list` → that tab). Do not
   spawn a pile of new tabs (burns per-session quota → more captchas).

### Viewer

| Viewer | URL |
|--------|-----|
| Chromebox mobile / noVNC | **http://100.92.122.70:6081/** |

`gbrowser url` may print an alternate viewer hint; prefer `:6081` above.

### Do NOT

- Keep “re-probing” or reading the browser-vm skill in a loop without messaging the user
- Close the captcha tab and open a fresh Yad2 URL hoping it bypasses
- Claim the listing is available / sold while the session is captcha-blocked
  (status = **inconclusive**)

## Live-check every listing you show the user

**Required** (skill `research-listings`). Prefer:

```bash
live-check-listing 'https://www.facebook.com/marketplace/item/<ID>/' --update
# or: python3 /root/work/mac-listings/scripts/live_check_listing.py <ID> --update
```

### Facebook item pages

1. Prefer an existing `facebook.com` tab.
2. Navigate to the item URL.
3. `gbrowser ctl eval 'location.href'` — **must** include `/marketplace/item/<id>`.
4. If redirected to search/results: run `live-check-listing` (it retries + clicks the card),
   or find/click `a[href*="/marketplace/item/<id>"]` then re-check `location.href`.
5. Read title / `נמכר ·` / price; persist with `--update`.
6. Do **not** tell the user a listing is available from scrape dumps alone.

### After check — persist

| Observation | Persist |
|-------------|---------|
| Item page, for sale | `listing_status=active`, bump `date_last_seen_active` |
| `נמכר` / gone | `listing_status=assumed_sold` |
| Redirect / captcha / CDP down | inconclusive — leave status; say so |

## Notes

- Host-only: `qbrowser start|stop|snapshot`
- Skills: `research-listings`, `facebook-marketplace`, `mac-listings`, `yad2-listings`
