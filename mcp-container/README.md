# human-browser MCP container

A **stateful** MCP server (Streamable HTTP) that exposes the QEMU guest's Chrome as
browser tools for **ChatGPT** (developer-mode connector) or any MCP client. It keeps
one persistent CDP session — `browser_session_id`, `qemu_vm_id`,
`chromium_target_id`, `current_tab_id`, and the `ref → DOM node` map — so
`navigate → snapshot → click → type → captcha → human → continue` behaves like one
real browser, not isolated HTTP calls.

Reads pages as a **numbered accessibility tree** (token-efficient), e.g.:

```
[12] button "Sign in"
[13] textbox "Email"
[14] textbox "Password"
[15] link "Forgot password?"
```

then `browser_click(ref=12)` / `browser_type(text="me@x.com", ref=13)`.

## Tools

`browser_status`, `browser_navigate`, `browser_snapshot`, `browser_click`,
`browser_type`, `browser_press_key`, `browser_hover`, `browser_click_xy`,
`browser_get_text`, `browser_eval`, `browser_screenshot`, `browser_reload`,
`browser_tabs`, `browser_select_tab`, `browser_new_tab`, `browser_viewer_url`.

## How it connects

```
ChatGPT ──HTTPS 443 (Tailscale Funnel, trusted cert)──▶ MCP server :8000 (/mcp)
                                                            │ persistent CDP session
                                        SSH tunnel over Tailscale ▼
                                              guest Chrome CDP 127.0.0.1:9222
human (captcha) ──Tailscale──▶ http://<guest>:6081/  (same tab)
```

## Build & run

```bash
cd /home/s/opt/qemu-browser/mcp-container
docker-compose build
docker-compose up -d
docker-compose logs mcp | tail        # shows the generated bearer token
```

## One-time setup (interactive; persisted)

```bash
docker exec -it mcp-human-browser tailscale up     # approve the node (reach guest + Funnel)
docker exec -it mcp-human-browser mcp-expose       # public HTTPS via Funnel; prints the URL
```

`mcp-expose` prints your public endpoint, e.g. `https://mcp-human-browser.<tailnet>.ts.net/mcp`.

## Add to ChatGPT (Developer mode)

1. ChatGPT → **Settings → Connectors / Apps → Developer mode** (Plus/Pro/Business/Enterprise/Edu).
2. Create a custom connector:
   - **URL:** the `https://…ts.net/mcp` from `mcp-expose`
   - **Authentication:** **Token** → paste the bearer token (from the logs / `docker exec mcp-human-browser cat /run/mcp_token`).
3. The 16 `browser_*` tools register automatically. Try: *"navigate to example.com, snapshot, and click the first link."*

> If your ChatGPT build only offers **None/OAuth** (no static Token), set
> `MCP_NO_AUTH=1` in `docker-compose.yml` and re-create — but then anyone with the
> Funnel URL can drive the browser, so keep the URL private.

## Security

- The endpoint is **public** (Funnel). It is protected by a **bearer token** by
  default (generated if `MCP_BEARER_TOKEN` unset). Treat it like a password.
- The token gate covers the `/mcp` path; the guest CDP itself stays private (only
  reached via the container's SSH tunnel over Tailscale).
- `browser_eval` executes arbitrary JS in the page — powerful; the token is your
  protection.

## Config (docker-compose.yml)

- `GUEST_HOST` — guest Tailscale IP/name (default `100.92.122.70`).
- `MCP_BEARER_TOKEN` — set your own, else auto-generated.
- `MCP_NO_AUTH=1` — disable auth (not recommended).
- Volumes mount `human_browser` and the guest SSH key; Tailscale state persists.

## Local test (no ChatGPT)

```bash
docker exec -i mcp-human-browser python - <<'PY'
import asyncio
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession
T=open('/run/mcp_token').read().strip()
async def m():
  async with streamablehttp_client('http://127.0.0.1:8000/mcp',headers={'Authorization':f'Bearer {T}'}) as (r,w,_):
    async with ClientSession(r,w) as s:
      await s.initialize(); print([t.name for t in (await s.list_tools()).tools])
asyncio.run(m())
PY
```
