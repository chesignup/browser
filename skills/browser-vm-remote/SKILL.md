---
name: browser-vm-remote
description: >-
  Control the real Google Chrome running in the remote QEMU "chromebox" VM from
  this container, using the `gbrowser` command (guest CDP over a Tailscale SSH
  tunnel). Use to browse, navigate, click, hover, type, press keys, read
  HTML/accessibility tree, evaluate JS, and screenshot the SAME tab a human
  watches via the mobile viewer. Use whenever asked to operate/drive/automate the
  guest browser, or when a captcha needs human-in-the-loop.
disable-model-invocation: true
---

# browser-vm-remote — drive the remote guest Chrome via `gbrowser`

You run inside a container. The browser is a real headed Chrome in a separate
QEMU VM ("chromebox"), reached over Tailscale. A human can watch and take over the
SAME tab from a phone. You drive it with `gbrowser`.

## First: make sure you can reach it

```bash
gbrowser tunnel status      # 'alive' = ready
```

If not alive:
- `tailscale status` — if Tailscale is down, run `tailscale up` and open the URL.
- `gbrowser tunnel up` — establishes the CDP tunnel to the guest.
- If it still fails, the VM may be off; the human must run `qbrowser start` on the host.

## Controlling the browser

All control goes through `gbrowser ctl <verb>` (auto-ensures the tunnel + session):

| Goal | Command |
|------|---------|
| Go to a URL | `gbrowser ctl nav https://example.com` |
| List open tabs | `gbrowser ctl list` |
| Read page HTML | `gbrowser ctl html` (or `ctl html "div#main"`) |
| Accessibility tree | `gbrowser ctl snap` |
| Evaluate JS | `gbrowser ctl eval "document.title"` |
| Screenshot to file | `gbrowser ctl shot /tmp/shot.png` |
| Click an element | `gbrowser ctl click "button#submit"` |
| Click coordinates | `gbrowser ctl clickxy 640 400` |
| Hover an element / coords | `gbrowser ctl hover "a.menu"` / `ctl hoverxy 640 400` |
| Type into focused field | `gbrowser ctl type "hello"` |
| Press a key | `gbrowser ctl key Enter` (Tab, Escape, ArrowDown, Backspace, …) |

Prefer `ctl snap` or `ctl html "<selector>"` to discover selectors before acting.
Use `ctl shot /tmp/x.png` then read the image when you need to see the page.
Verify results after actions (re-`snap` or `eval location.href`).

## Human-in-the-loop (captcha, login, 2FA)

When a human is needed:
1. Run `gbrowser url` and tell the user to open the **mobile viewer**
   (`http://<guest>:6081/`) on their phone via Tailscale, and solve it there.
2. Wait for them to confirm.
3. Continue with `gbrowser ctl …`. You share the exact tab, so their manual
   actions (solved captcha, login) carry over.

## Notes

- You cannot manage VM power/snapshots from here — that's on the host
  (`qbrowser start|snapshot`). Ask the user if the VM appears down.
- `GUEST_HOST` (env) points at the guest's Tailscale IP/name.
