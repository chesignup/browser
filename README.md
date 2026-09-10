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
| `skills/` | Agent skills: `browser-vm`, `browser-vm-remote`, `yad2` |
| `scrape/` | Deterministic yad2 feed + detail scrape + watchdog |
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

Skill docs: `skills/yad2/SKILL.md` (interactive UI + bulk scrape + captcha/tab hygiene).

## Viewers

- Mobile (tab bar, tap/scroll): port **6081**
- Desktop noVNC: port **6080**

Same Chromium the agent/MCP drives.
