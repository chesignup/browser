---
name: human-browser
description: "Human-like browser automation for cloud agents. Prefers Playwright Chromium; falls back to Carbonyl in tmux with CDP on port 1112. Read and verify pages over CDP (websockets, suppress_origin=True). Drive Carbonyl with real tmux keyboard and mouse input."
environments: [cloud]
---

# Human Browser

Use this skill when you need to browse, inspect, or manually test a web page like a human would — with real keyboard/mouse input and CDP-based verification.

## Backend selection

1. **Playwright first** — launches Chromium with a real desktop Chrome user agent and `--remote-debugging-port=1112`.
2. **Carbonyl fallback** — terminal Chromium in a tmux split pane with the same user agent and CDP port.

Install once per environment:

```bash
cd /workspace   # or wherever this repo lives
pip install -e .
python -m playwright install chromium
```

## Prerequisites

Run this check before starting:

```bash
human-browser status || true
command -v human-browser
command -v tmux
echo "tmux session: ${TMUX:-not in tmux}"
```

- **Playwright path:** works without tmux.
- **Carbonyl path:** requires an active tmux session (`$TMUX` must be set). If missing, tell the user to run inside tmux or use `--backend playwright`.

## Start a session

```bash
human-browser start https://example.com
```

Force a backend when needed:

```bash
human-browser start https://example.com --backend playwright
human-browser start https://example.com --backend carbonyl
```

Confirm CDP is alive:

```bash
human-browser status
curl -s http://127.0.0.1:1112/json/version | head -5
```

## Read and verify (always CDP)

Use these commands to inspect page state. They connect over CDP WebSocket with `suppress_origin=True`.

```bash
human-browser list
human-browser eval "document.title"
human-browser eval "document.body.innerText.slice(0, 2000)"
human-browser html
human-browser html "main"
human-browser snap
human-browser shot /tmp/verify.png
human-browser nav https://other.example
```

Typical verification flow:

```bash
human-browser eval "document.title"
human-browser snap
human-browser eval "document.querySelector('h1')?.textContent"
```

## Human input

### Playwright backend

Keyboard and mouse go through Playwright connected over CDP:

```bash
human-browser type "search query"
human-browser key Enter
human-browser clickxy 300 200
human-browser click "button[type=submit]"
```

### Carbonyl backend

**Do not** use CDP `Input.*` events on Carbonyl. Drive the visible terminal browser with tmux-backed input:

```bash
human-browser type "search query"
human-browser key Enter
human-browser clickxy 40 12
human-browser click "a"
```

`click` resolves element coordinates via CDP, then sends a real tmux mouse click to the Carbonyl pane.

## Stop

```bash
human-browser stop
```

## Agent workflow

1. `human-browser start <url>`
2. `human-browser status` — note `backend` and `cdp_alive`
3. Verify expected state with `eval`, `snap`, or `shot`
4. Interact with `type`, `key`, `click`, or `clickxy`
5. Re-verify after each meaningful action
6. `human-browser stop` when finished

## Constants

| Setting | Value |
|---------|-------|
| CDP port | `1112` |
| User agent | Desktop Chrome on Linux x86_64 |
| Carbonyl flags | `--user-agent=…` `--remote-debugging-port=1112` |
| CDP connect | WebSocket, `suppress_origin=True` |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Carbonyl backend requires tmux` | Run inside tmux or `--backend playwright` |
| CDP not alive on 1112 | `human-browser stop` then start again |
| Playwright missing | `pip install -e . && python -m playwright install chromium` |
| Carbonyl missing | `human-browser start --backend carbonyl` auto-installs to `~/.local/share/human-browser/carbonyl` |

## Implementation reference

- CLI: `human-browser` (`human_browser/cli.py`)
- CDP client: `human_browser/cdp.py`
- Backends: `human_browser/backends.py`
- tmux input: `human_browser/tmux_input.py`
