# qemu-browser

Run a **real Google Chrome inside a QEMU/KVM VM**, watch & interact with it from a
LAN PC via **noVNC** (password-protected), and drive the *same tab* over **CDP**
with the `human_browser` control CLI. Built for agent control with human-in-the-loop
for captchas.

```
  LAN PC Chrome ──http──▶ host:6080 (noVNC, VNC password) ──▶ guest Xvfb :0 ──▶ Chrome
                                                                         ▲
  Cursor / you ──▶ ./qbrowser ctl … ──▶ SSH tunnel 127.0.0.1:11222 ─CDP──┘ (localhost only)
```

## Quick start

```bash
cd /home/s/opt/qemu-browser
./qbrowser setup 'YOUR_VNC_PASSWORD'   # one-time: downloads Ubuntu image, builds disk + seed
./qbrowser start                        # boots VM, opens CDP tunnel, attaches control
./qbrowser status                       # check VM / services / CDP / noVNC
./qbrowser url                          # noVNC URL to open on your LAN PC
```

First boot provisions the guest (installs Chrome, Xvfb, x11vnc, noVNC) via cloud-init
— allow a few minutes. `./qbrowser status` shows `CDP: alive` when ready.

## Control the browser

```bash
./qbrowser ctl nav https://example.com
./qbrowser ctl snap                     # accessibility tree
./qbrowser ctl click "a#login"
./qbrowser ctl type "hello"
./qbrowser ctl key Enter
./qbrowser ctl shot var/page.png
```

Full verb list: run `./qbrowser` with no args.

## View / captcha

Two viewers of the **same** tab (agent shares it, so state carries over):

- **Desktop (noVNC):** `http://<host-lan-ip>:6080/vnc.html` — enter the VNC password.
- **Mobile:** `http://<host-lan-ip>:6081/` — responsive; tap = click, drag = scroll,
  ⌨ for keyboard, URL bar to navigate. No password.

Use the LAN IP on the same network, or the guest's Tailscale IP from anywhere.

## Layout

| Path | Purpose |
|------|---------|
| `config.env` | ports, resources, screen size, image URL |
| `qbrowser` | main entrypoint (setup/start/stop/status/ssh/tunnel/ctl) |
| `cloud-init/user-data.tmpl` | guest provisioning (Chrome + Xvfb + x11vnc + noVNC + CDP) |
| `scripts/` | setup/run/stop/status/ssh/tunnel + seed-ISO builder |
| `var/` | runtime artifacts (disk, seed.iso, ssh key, vnc_pass) — git-ignored |

## Security

- **noVNC** is the only LAN-exposed port, behind a VNC password (set at `setup`).
  To keep it host-local, set `LAN_BIND="127.0.0.1"` in `config.env`.
- **CDP** is never port-forwarded by QEMU; it's reachable only on host
  `127.0.0.1:11222` through an SSH tunnel.
- SSH management is on host `127.0.0.1:2222` with a generated key in `var/`.

## Agent container (drive it from a Cursor CLI agent)

`agent-container/` builds a Docker container running the **Cursor CLI agent** in a
**tmux** session, on **Tailscale**, that drives the guest Chrome via `gbrowser`
(guest CDP over a Tailscale SSH tunnel). SSH in (`ssh -p 2223 root@<host>`), give it
tasks, and hand off to your phone for captchas. See `agent-container/README.md`.

## MCP server for ChatGPT (mcp-container/)

`mcp-container/` runs a **stateful MCP server** (Streamable HTTP) exposing the guest
Chrome as `browser_*` tools, with a **numbered accessibility-tree** snapshot and
persistent session (tab/refs) across calls. Exposed publicly on HTTPS:443 via
**Tailscale Funnel** with a bearer token, so you can add it as a **ChatGPT
developer-mode connector**. See `mcp-container/README.md`.

## Control layer

`./qbrowser ctl …` wraps the `human_browser` package at `/home/s/opt/browser`
(attaches to the tunneled CDP; input via native CDP, no Playwright needed).
The `browser-vm` Cursor skill documents how the agent should use it.
