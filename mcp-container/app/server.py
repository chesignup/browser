"""Human-browser MCP server (stateful, Streamable HTTP) for ChatGPT & other MCP clients.

Exposes a persistent browser session over the Model Context Protocol. State
(session id, vm id, current tab, and the ref->node map from the last snapshot)
persists across tool calls, so navigate -> snapshot -> click(ref) -> type ->
captcha -> continue behaves like one real browser.

Reads the page as a numbered accessibility tree (token-efficient) instead of raw
HTML. Serve at /mcp via Streamable HTTP; expose publicly (port 443, trusted cert)
with Tailscale Funnel for ChatGPT developer-mode connectors.
"""
from __future__ import annotations

import os
import secrets

from mcp.server.fastmcp import FastMCP, Image

from session import BrowserSession

MCP_PORT = int(os.environ.get("MCP_PORT", "8000"))
mcp = FastMCP("human-browser", host="0.0.0.0", port=MCP_PORT)
SESSION = BrowserSession()


# ------------------------------ tools ---------------------------------------

@mcp.tool()
async def browser_status() -> dict:
    """Return the current browser session state: browser_session_id, qemu_vm_id,
    chromium_target_id, current_tab_id, plus the current url and title."""
    async with SESSION.lock:
        return await SESSION.status()


@mcp.tool()
async def browser_navigate(url: str) -> dict:
    """Navigate the current tab to a URL (waits for load). Returns session state.
    After navigating, call browser_snapshot to see the page's actionable elements."""
    async with SESSION.lock:
        return await SESSION.navigate(url)


@mcp.tool()
async def browser_snapshot(interactive_only: bool = False) -> str:
    """Return a compact, capped accessibility snapshot as a numbered tree, e.g.
    '[12] button "Sign in"'. Use the [ref] numbers with browser_click /
    browser_type / browser_hover. Set interactive_only=true for just the
    clickable/typable controls (smallest output) — do this on large pages. Refs
    are valid until the next navigation/snapshot. To READ page content (listings,
    article text) use browser_read/browser_get_text, not a full snapshot."""
    async with SESSION.lock:
        return await SESSION.snapshot(interactive_only=interactive_only)


@mcp.tool()
async def browser_read(selector: str = "body") -> str:
    """Extract visible text (like Playwright inner_text) from elements matching a
    CSS selector (default 'body'); returns concatenated, truncated innerText.
    Prefer this over screenshots to read results/listings/article content
    token-efficiently, e.g. selector='[data-testid=feed-item]' or 'main'."""
    async with SESSION.lock:
        return await SESSION.read(selector)


@mcp.tool()
async def browser_click(ref: int) -> dict:
    """Click the element with the given [ref] from the latest browser_snapshot
    (real mouse click at the element's center; visible in the shared viewer)."""
    async with SESSION.lock:
        return await SESSION.click(ref)


@mcp.tool()
async def browser_type(text: str, ref: int | None = None, submit: bool = False) -> dict:
    """Type text. If ref is given, focus that element first (e.g. a textbox ref
    from browser_snapshot). Set submit=true to press Enter afterwards."""
    async with SESSION.lock:
        return await SESSION.type_text(text, ref=ref, submit=submit)


@mcp.tool()
async def browser_press_key(key: str) -> dict:
    """Press a single key (Enter, Tab, Escape, Backspace, ArrowDown, etc.)."""
    async with SESSION.lock:
        return await SESSION.press_key(key)


@mcp.tool()
async def browser_hover(ref: int) -> dict:
    """Hover the mouse over the element with the given [ref]."""
    async with SESSION.lock:
        return await SESSION.hover(ref)


@mcp.tool()
async def browser_click_xy(x: float, y: float) -> dict:
    """Click at absolute CSS pixel coordinates (fallback when no ref applies)."""
    async with SESSION.lock:
        return await SESSION.click_xy(x, y)


@mcp.tool()
async def browser_get_text(ref: int | None = None) -> str:
    """Return visible text of the element with [ref], or the whole page body text
    if ref is omitted (truncated). Prefer browser_snapshot for structure."""
    async with SESSION.lock:
        return await SESSION.get_text(ref)


@mcp.tool()
async def browser_eval(expression: str) -> str:
    """Evaluate a JavaScript expression in the page and return the value as text.
    Powerful escape hatch; prefer the structured tools when possible."""
    async with SESSION.lock:
        val = await SESSION.eval_js(expression)
        return str(val)


@mcp.tool()
async def browser_screenshot() -> Image:
    """Capture a PNG screenshot of the current tab."""
    async with SESSION.lock:
        return Image(data=await SESSION.screenshot(), format="png")


@mcp.tool()
async def browser_reload() -> dict:
    """Reload the current tab."""
    async with SESSION.lock:
        return await SESSION.reload()


@mcp.tool()
async def browser_tabs() -> list:
    """List open tabs (tab_id, title, url, current)."""
    async with SESSION.lock:
        return await SESSION.list_tabs()


@mcp.tool()
async def browser_select_tab(tab_id: str) -> dict:
    """Switch the active tab to the given tab_id (from browser_tabs)."""
    async with SESSION.lock:
        return await SESSION.select_tab(tab_id)


@mcp.tool()
async def browser_new_tab(url: str = "about:blank") -> dict:
    """Open a new tab (optionally at a URL) and make it the active tab."""
    async with SESSION.lock:
        return await SESSION.new_tab(url)


@mcp.tool()
async def browser_viewer_url() -> dict:
    """Return the human viewer URLs (mobile + noVNC). Use for human-in-the-loop:
    ask the user to open the mobile viewer to solve a captcha/login, then continue.
    The human shares the exact same tab."""
    return await SESSION.viewer_urls()


# ------------------------------ auth + app ----------------------------------

def build_app():
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class BearerAuth(BaseHTTPMiddleware):
        def __init__(self, app, token: str) -> None:
            super().__init__(app)
            self.token = token

        async def dispatch(self, request, call_next):
            if request.url.path.rstrip("/").endswith("mcp") or "/mcp" in request.url.path:
                if request.headers.get("authorization", "") != f"Bearer {self.token}":
                    return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app = mcp.streamable_http_app()
    if os.environ.get("MCP_NO_AUTH"):
        print("[mcp] WARNING: authentication DISABLED (MCP_NO_AUTH set).", flush=True)
        return app
    token = os.environ.get("MCP_BEARER_TOKEN")
    if not token:
        token = secrets.token_urlsafe(24)
    try:
        with open("/run/mcp_token", "w") as fh:
            fh.write(token)
    except OSError:
        pass
    print("=" * 60, flush=True)
    print(f"[mcp] Bearer token: {token}", flush=True)
    print("[mcp] In ChatGPT connector: Authentication=Token, paste the above.", flush=True)
    print("=" * 60, flush=True)
    app.add_middleware(BearerAuth, token=token)
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build_app(), host="0.0.0.0", port=MCP_PORT)
