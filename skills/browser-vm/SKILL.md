---
name: browser-vm
description: >-
  Control the real Google Chrome running inside the QEMU "chromebox" VM at
  /home/s/opt/qemu-browser. Use to browse, navigate, click, hover, type, press
  keys, read HTML/accessibility tree, evaluate JS, and screenshot the SAME tab a
  human watches via noVNC. Use whenever the user asks to operate, drive, or
  automate the VM browser / chromebox / shared Chrome tab, or when a captcha
  needs human-in-the-loop.
disable-model-invocation: true
---

# browser-vm — drive the Chrome inside the QEMU VM

The VM runs a real headed Google Chrome on Xvfb. A human watches and can take over
the SAME tab through noVNC (password-protected) from a LAN PC. You drive that exact
tab over the Chrome DevTools Protocol (CDP) via an SSH tunnel, using the
`qbrowser` wrapper around the `human_browser` CLI.

Project root: `/home/s/opt/qemu-browser` — run `./qbrowser` from there (or use the
absolute path). All commands below assume that directory.

## First: make sure it's up

```bash
cd /home/s/opt/qemu-browser
./qbrowser status
```

Interpret status:
- `VM: stopped` → run `./qbrowser start` (first boot provisions Chrome; wait a few min).
- `VM: running` but `CDP tunnel: down` → run `./qbrowser tunnel up`.
- `CDP: alive` → you're ready to control.

Never run `./qbrowser setup` unless the VM was never built (it downloads the image).
Never run `./qbrowser stop`/`restart` unless the user asks — it kills the human's view.

## Controlling the browser

All control goes through `./qbrowser ctl <verb>`. It auto-ensures the tunnel and an
attached session. The verbs:

| Goal | Command |
|------|---------|
| Go to a URL | `./qbrowser ctl nav https://example.com` |
| List open tabs | `./qbrowser ctl list` |
| Read page HTML | `./qbrowser ctl html` (or `ctl html "div#main"`) |
| Accessibility tree (good for "what's on screen") | `./qbrowser ctl snap` |
| Evaluate JS, get value | `./qbrowser ctl eval "document.title"` |
| Screenshot to a file | `./qbrowser ctl shot /home/s/opt/qemu-browser/var/shot.png` |
| Click an element | `./qbrowser ctl click "button#submit"` |
| Click coordinates | `./qbrowser ctl clickxy 640 400` |
| Hover an element | `./qbrowser ctl hover "a.menu"` |
| Hover coordinates | `./qbrowser ctl hoverxy 640 400` |
| Type text (into focused field) | `./qbrowser ctl type "hello world"` |
| Press a key | `./qbrowser ctl key Enter` (Tab, Escape, ArrowDown, Backspace, …) |

Typical fill-a-form flow: `nav` → `click` the input → `type` → `key Tab` → `click` submit.

## Reading state before acting

Prefer `ctl snap` (accessibility tree) or `ctl html "<selector>"` to discover
selectors/positions before clicking, rather than guessing. Use `ctl shot <path>`
then Read the PNG when you need to *see* the page. Verify results after actions
(re-`snap` or `eval` the URL/title).

## Snapshots (clean-state revert)

A single live snapshot named `clean` (RAM + disk) can be captured and restored:

```bash
./qbrowser snapshot save      # (re)capture current state as the one baseline
./qbrowser snapshot revert    # instantly restore the VM to that baseline
./qbrowser snapshot status    # show the stored snapshot
```

Only one snapshot is kept; `save` overwrites it. `revert` restores RAM+disk in
seconds and auto-rebuilds the CDP tunnel. Use `revert` to reset the guest to a
known-good state between tasks. Do not `save` unless you intend to move the
baseline forward.

## Human-in-the-loop (captcha, login, 2FA)

When you hit a captcha, login wall, or anything needing a human:
1. Tell the user to open a viewer and solve it manually (run `./qbrowser url`):
   - **Phone / mobile:** `http://<ip>:6081/` — mobile-friendly (tap = click, drag =
     scroll, ⌨ button for keyboard, URL bar). No password.
   - **Desktop:** `http://<ip>:6080/vnc.html` — noVNC, needs the VNC password.
   Use the LAN IP on the same network, or the Tailscale IP from off-LAN.
2. Wait for the user to confirm they finished.
3. Continue driving with `ctl` verbs. You share the exact tab, so their manual
   actions (solved captcha, logged-in session) carry over seamlessly.

## Notes

- CDP is localhost-only on the host (`127.0.0.1:11222` via SSH tunnel, see
  `config.env`); it is never exposed to the LAN. Only noVNC is on the LAN, behind a
  VNC password.
- If a `ctl` command errors with CDP not reachable, run `./qbrowser status`; if the
  VM is still provisioning, wait and retry.
- Config (ports, screen size, resources) lives in `config.env`.
