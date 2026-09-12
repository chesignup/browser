# browser

Real Chromium in a QEMU guest, driven over CDP, watched from a phone/PC, and
operable by a Cursor agent or ChatGPT (MCP).

## Pieces

| Path | Role |
|------|------|
| `human_browser/` | Host CLI: attach / nav / click / type / snap over CDP |
| `qemu-browser/` | Ubuntu cloud VM + Chrome + noVNC + mobile tab viewer |
| `agent-container/` | Cursor CLI in tmux + Tailscale + `gbrowser` |
| `mcp-container/` | Stateful MCP (`browser_*` tools) for ChatGPT plugins |
| `skills/` | Agent skills: `browser-vm`, `yad2`, `yad2-research`, `repo-git-sync` |
| `scrape/` | Deterministic yad2 feed + detail scrape + geocode/yield |
| `data/yad2/` | Scooped listings + `research/FINDINGS.md` |
| `deploy/bootstrap.sh` | Fresh Ubuntu installer |

## Quick start (existing machine)

```bash
cd qemu-browser && ./qbrowser setup 'vnc-pass' && ./qbrowser start
cd ../agent-container && BROWSER_ROOT=.. docker compose up -d --build
# SSH: ssh -p 2223 root@<host>   password: agent
```

Fresh server: see [DEPLOY.md](DEPLOY.md).

## Yad2 scraping

Prefer the deterministic pipeline (host HTTP is bot-blocked):

```bash
# inside the agent, with CDP tunnel up:
python3 skills/yad2/scripts/yad2_cdp_tabs.py ensure rent
python3 scrape/rent/scrape_watchdog.py --workdir scrape/rent --kind rent --batch 40
```

Skill docs: `skills/yad2/SKILL.md` (scrape) and `skills/yad2-research/SKILL.md` (yield pairing).
GitHub updates: `skills/repo-git-sync/SKILL.md`.

## Viewers

- **Remote Web Browser & DevTools (Recommended):** port **9222** (`http://<tailscale-ip>:9222/` or `http://<host-lan>:9222/`) — interactive Chrome tab strip, Omnibox address bar, real-time CDP screencast, mouse/touch/keyboard, and direct integration with native desktop `chrome://inspect`.
- Mobile viewer: port **6081**
- Desktop noVNC: port **6080**

Same Chromium the agent/MCP drives.
