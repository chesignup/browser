# Deploy from scratch (Ubuntu 22.04 / 24.04)

One script. Run on a fresh server with sudo, KVM available, and internet.

## 1. Get the repo

```bash
git clone https://github.com/chesignup/browser.git ~/browser
cd ~/browser
```

## 2. Bootstrap

```bash
sudo ./deploy/bootstrap.sh
# optional overrides:
# sudo VNC_PASS='secret' MCP_BEARER_TOKEN='secret' ROOT_PASSWORD='agent' ./deploy/bootstrap.sh
```

What it does:

- Installs QEMU/KVM, Docker, Python deps, UFW rules (6080/6081 LAN, 2223 agent SSH)
- Adds your user to `kvm` + `docker`, grants `/dev/kvm` ACL
- Sets up and starts the chromebox VM (`qbrowser setup` + `start` + snapshot)
- Builds and starts `cursor-agent` and `mcp-human-browser` containers
- Prints LAN URLs, SSH, and the MCP bearer token

## 3. One-time interactive Tailscale / Cursor

```bash
cd ~/browser/qemu-browser && ./qbrowser tailscale up          # guest
docker exec -it cursor-agent tailscale up                    # agent
docker exec -it mcp-human-browser bash -lc 'tailscale up && mcp-expose'  # MCP + Funnel URL
ssh -p 2223 root@$(hostname -I | awk '{print $1}')           # Cursor login if needed
# password: agent   then:  NO_OPEN_BROWSER=1 cursor-agent login
```

Update `GUEST_HOST` in both compose files to the guest Tailscale IP if the bootstrap
could not detect it, then `docker compose up -d` again in each container dir.

## 4. Day-to-day

| What | How |
|------|-----|
| VM status | `~/browser/qemu-browser/qbrowser status` |
| Snapshot revert | `./qbrowser snapshot revert` |
| Mobile viewer | `http://<host-or-guest-ts>:6081/` |
| noVNC | `http://<host>:6080/vnc.html` |
| Agent (LAN) | `ssh -p 2223 root@<host>` |
| Agent (WAN) | `ssh root@cursor-agent` (Tailscale) |
| Yad2 scrape | Inside agent: `python3 scrape/rent/scrape_watchdog.py --workdir scrape/rent --kind rent --batch 40` |
| ChatGPT plugin | Funnel URL from `mcp-expose` + bearer token (Token auth) |

## Layout

```
browser/
  human_browser/       CDP control CLI (human-browser)
  qemu-browser/        QEMU chromebox + guest viewer
  agent-container/     Cursor CLI + Tailscale + tmux
  mcp-container/       Stateful MCP for ChatGPT
  skills/              browser-vm, browser-vm-remote, yad2 (+ watchdog scripts)
  scrape/rent|sale/    Deterministic CDP scrape pipeline
  deploy/bootstrap.sh  This installer
```

## Notes

- Log out/in (or `newgrp docker`) after bootstrap so group membership applies.
- Funnel needs MagicDNS + HTTPS + Funnel ACL enabled in the Tailscale admin console.
- Do not commit real VNC/MCP/root passwords; set them via env at bootstrap time.
