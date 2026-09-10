# Agent container

A Docker container that runs the **Cursor CLI agent** in a **tmux** session, joined
to **Tailscale**, able to drive the QEMU guest's Chrome via `gbrowser` (guest CDP
over a Tailscale SSH tunnel). SSH in and give the agent tasks; hand off to your
phone for captchas.

```
you ──ssh──▶ container (tmux 'agent' → cursor-agent)
                        └─ gbrowser ctl … ─ssh/Tailscale▶ guest Chrome CDP (9222)
phone ──Tailscale──▶ http://<guest>:6081/  (same tab, for captcha)
```

## Build & run

```bash
cd /home/s/opt/qemu-browser/agent-container
docker-compose build
docker-compose up -d
docker-compose logs agent | tail   # see readiness banner
```

> This host has the standalone `docker-compose` (not the `docker compose` plugin).

The tmux `agent` session **auto-runs the Cursor CLI agent** (`agent-run` keeps it
running and respawns it), pre-configured with:
- the **human-browser MCP** (`~/.cursor/mcp.json` → `browser_navigate`,
  `browser_snapshot`, `browser_click`, `browser_type`, … 16 tools, stateful,
  accessibility-tree refs), and
- the `gbrowser` CLI + `browser-vm-remote` skill.

## First-time setup (interactive, once; persisted via volumes)

SSH into the container — you land directly in the running agent:

```bash
ssh -p 2223 root@<host-lan-ip>        # password: 'agent' (change ROOT_PASSWORD)
```

One-time prompts (all persist):
- **Cursor login:** if not already logged in, run `NO_OPEN_BROWSER=1 cursor-agent login`
  (open the printed URL). `cursor-agent status` should show your account.
- **Workspace trust:** press `a` when asked to trust `/root/work`.
- **Tailscale (needed for the browser tools to reach the guest):** open a second
  tmux window with `Ctrl-b c`, run `tailscale up`, approve the node, then `Ctrl-b d`
  back. Reach the container itself by its tailnet IP afterwards.

Then just talk to the agent, e.g. *"open example.com, snapshot the page, and click
the first link."* It calls the `browser_*` MCP tools (or `gbrowser`) under the hood,
driving the same tab you can watch on your phone (`http://<guest>:6081/`).

## Reach it from anywhere

- **LAN:** `ssh -p 2223 root@<host-lan-ip>`
- **Tailscale:** `ssh root@<container-tailscale-ip>` (after `tailscale up`)

Detach from tmux with `Ctrl-b d` (the agent keeps running).

## Config (docker-compose.yml)

- `GUEST_HOST` — guest Tailscale IP/name (default `100.92.122.70`).
- `ROOT_PASSWORD` — SSH password for the container.
- `AUTHORIZED_KEYS` — optional; your pubkey for key-based SSH.
- Volumes persist Tailscale + Cursor login across restarts.

## Captcha / human-in-the-loop

When the agent needs a human, it prints the viewer URL (`gbrowser url`). Open
`http://<guest>:6081/` on your phone (via Tailscale), solve it, tell the agent to
continue — it shares the exact same tab.
