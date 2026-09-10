"""Stateful browser session for the human-browser MCP server.

Holds ONE persistent CDP connection to the guest Chrome and remembers state
across tool calls (session id, vm id, current target/tab, and the ref->DOM-node
map produced by the last accessibility snapshot). This is what makes a sequence
like navigate -> snapshot -> click(ref) -> type -> ... behave like a real browser
instead of independent HTTP calls.

Reaches the guest CDP via an SSH tunnel (over Tailscale) to 127.0.0.1:<CDP_PORT>.
Reuses human_browser.cdp.CDPClient for the low-level protocol + input helpers.
"""
from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import time
import uuid
from typing import Any

from human_browser.cdp import CDPClient

def _ws_open(ws: Any) -> bool:
    """True if a websockets connection is open, across library versions."""
    if ws is None:
        return False
    state = getattr(ws, "state", None)
    if state is not None:  # websockets >= 12 asyncio client exposes .state
        return getattr(state, "name", "") == "OPEN"
    return bool(getattr(ws, "open", False)) and not getattr(ws, "closed", True)


GUEST_HOST = os.environ.get("GUEST_HOST", "100.92.122.70")
GUEST_USER = os.environ.get("GUEST_USER", "vmuser")
GUEST_KEY = os.environ.get("GUEST_KEY", "/root/.ssh/guest_key")
GUEST_CDP = int(os.environ.get("GUEST_CDP", "9222"))
CDP_PORT = int(os.environ.get("CDP_PORT", "11222"))
QEMU_VM_ID = os.environ.get("QEMU_VM_ID", "chromebox")
VIEWER_PORT = os.environ.get("VIEWER_PORT", "6081")
NOVNC_PORT = os.environ.get("NOVNC_PORT", "6080")

# Roles worth surfacing in the accessibility snapshot (token-efficient).
_INTERACTIVE = {
    "button", "link", "textbox", "searchbox", "checkbox", "radio", "combobox",
    "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "switch", "slider",
    "option", "listbox", "spinbutton", "textarea",
}
_NAMED_CONTEXT = {
    "heading", "img", "image", "StaticText", "list", "listitem", "cell",
    "columnheader", "rowheader", "article", "navigation", "dialog", "alert",
    "form", "table", "region", "banner", "contentinfo", "main",
}


class BrowserSession:
    def __init__(self) -> None:
        self.session_id = uuid.uuid4().hex[:12]
        self.vm_id = QEMU_VM_ID
        self.client: CDPClient | None = None
        self.target_id: str | None = None
        self.refs: dict[int, int] = {}          # ref -> backendDOMNodeId
        self.ref_meta: dict[int, dict] = {}       # ref -> {role,name}
        self.lock = asyncio.Lock()

    # ---- connectivity -------------------------------------------------------

    def _tunnel_up(self) -> bool:
        fwd = f"127.0.0.1:{CDP_PORT}:127.0.0.1:{GUEST_CDP}"
        try:
            subprocess.run(["pgrep", "-f", f"ssh.*-L {fwd}"],
                           check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            pass
        cmd = [
            "ssh", "-i", GUEST_KEY,
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=15", "-o", "ConnectTimeout=8",
            "-N", "-f", "-L", fwd, f"{GUEST_USER}@{GUEST_HOST}",
        ]
        return subprocess.run(cmd, capture_output=True).returncode == 0

    def _cdp_alive(self) -> bool:
        import urllib.request
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=4)
            return True
        except Exception:
            return False

    async def ensure(self) -> None:
        """Ensure the tunnel is up and we have a live CDP connection to a tab."""
        if not self._cdp_alive():
            self._tunnel_up()
            for _ in range(15):
                if self._cdp_alive():
                    break
                await asyncio.sleep(1)
            if not self._cdp_alive():
                raise RuntimeError(
                    f"Guest CDP not reachable via {GUEST_HOST}. Is the VM up and "
                    f"Tailscale connected in this container? (run: tailscale up)"
                )
        # Reuse existing connection if still open.
        if self.client and _ws_open(self.client._ws):
            return
        client = CDPClient(CDP_PORT)
        try:
            target = client.find_page(self.target_id) if self.target_id else client.find_page()
        except Exception:
            target = client.find_page()
        await client.connect(target)
        self.client = client
        self.target_id = target.id
        for domain in ("Page.enable", "DOM.enable", "Runtime.enable", "Accessibility.enable"):
            try:
                await client.send(domain)
            except Exception:
                pass

    async def _send(self, method: str, params: dict | None = None) -> Any:
        assert self.client is not None
        return await self.client.send(method, params)

    # ---- state --------------------------------------------------------------

    async def status(self) -> dict:
        await self.ensure()
        url = title = ""
        try:
            url = await self.client.evaluate("location.href")
            title = await self.client.evaluate("document.title")
        except Exception:
            pass
        return {
            "browser_session_id": self.session_id,
            "qemu_vm_id": self.vm_id,
            "chromium_target_id": self.target_id,
            "current_tab_id": self.target_id,
            "url": url,
            "title": title,
            "guest_host": GUEST_HOST,
        }

    async def viewer_urls(self) -> dict:
        return {
            "mobile_viewer": f"http://{GUEST_HOST}:{VIEWER_PORT}/",
            "novnc": f"http://{GUEST_HOST}:{NOVNC_PORT}/vnc.html",
            "note": "Open on a device on the same Tailscale tailnet to view/solve captcha; the agent shares the same tab.",
        }

    # ---- navigation ---------------------------------------------------------

    async def navigate(self, url: str) -> dict:
        await self.ensure()
        await self.client.navigate(url)
        self.refs.clear()
        self.ref_meta.clear()
        return await self.status()

    async def reload(self) -> dict:
        await self.ensure()
        await self._send("Page.reload")
        await asyncio.sleep(1.0)
        self.refs.clear()
        return await self.status()

    # ---- accessibility snapshot with refs -----------------------------------

    async def snapshot(
        self,
        interactive_only: bool = False,
        max_nodes: int = 250,
        max_chars: int = 6000,
    ) -> str:
        """Compact accessibility snapshot with [ref] numbers. Set
        interactive_only=True for just clickable/typable controls (smallest);
        output is capped so it never floods the context. For reading page content
        (listings, article text) use read()/get_text instead of a full snapshot."""
        await self.ensure()
        result = await self._send("Accessibility.getFullAXTree")
        nodes = result.get("nodes", [])
        by_id = {n["nodeId"]: n for n in nodes}
        self.refs.clear()
        self.ref_meta.clear()

        emit_roles = set(_INTERACTIVE) | {"link"}
        if not interactive_only:
            emit_roles |= {"heading", "dialog", "alert", "tab", "navigation"}

        lines: list[str] = []
        ref = [0]
        count = [0]

        def role_of(n):
            return (n.get("role") or {}).get("value", "") or ""

        def name_of(n):
            return (n.get("name") or {}).get("value", "") or ""

        def walk(node_id: str, depth: int):
            if count[0] >= max_nodes:
                return
            n = by_id.get(node_id)
            if not n:
                return
            role = role_of(n)
            name = name_of(n).strip().replace("\n", " ")
            if len(name) > 80:
                name = name[:77] + "…"
            emit = (not n.get("ignored", False)) and role in emit_roles and (
                role in _INTERACTIVE or role == "link" or bool(name)
            )
            if emit:
                count[0] += 1
                backend = n.get("backendDOMNodeId")
                if backend is not None:
                    ref[0] += 1
                    r = ref[0]
                    self.refs[r] = backend
                    self.ref_meta[r] = {"role": role, "name": name}
                    prefix = f"[{r}] "
                else:
                    prefix = ""
                label = f'"{name}"' if name else ""
                lines.append("  " * min(depth, 10) + f"{prefix}{role} {label}".rstrip())
            child_depth = depth + 1 if emit else depth
            for cid in n.get("childIds", []):
                walk(cid, child_depth)

        if nodes:
            walk(nodes[0]["nodeId"], 0)

        body = "\n".join(lines) if lines else "(no actionable elements; use read()/get_text for page text)"
        note = ""
        if len(body) > max_chars:
            body = body[:max_chars]
            note = ("\n… (truncated; use browser_snapshot with interactive_only=true, "
                    "or browser_read(selector) to extract text)")
        mode = ", interactive_only" if interactive_only else ""
        return f"# a11y snapshot ({len(self.refs)} refs{mode})\n{body}{note}"

    async def read(self, selector: str | None = None, max_chars: int = 6000) -> str:
        """Extract visible text like Playwright's inner_text. selector is a CSS
        selector (default 'body'); returns concatenated innerText of matches,
        truncated to max_chars."""
        await self.ensure()
        sel = selector or "body"
        import json as _json
        expr = (
            "(()=>{try{const els=[...document.querySelectorAll(" + _json.dumps(sel) + ")];"
            "if(!els.length)return '(no elements match: '+" + _json.dumps(sel) + "+')';"
            "return els.map(e=>(e.innerText||e.textContent||'').trim()).filter(Boolean)"
            ".join('\\n---\\n');}catch(e){return 'error: '+e.message;}})()"
        )
        val = await self.client.evaluate(expr)
        text = str(val or "")
        if len(text) > max_chars:
            text = text[:max_chars] + "\n… (truncated)"
        return text

    # ---- actions by ref -----------------------------------------------------

    def _resolve(self, ref: int) -> int:
        if ref not in self.refs:
            raise RuntimeError(
                f"Unknown ref {ref}. Call browser_snapshot again to refresh refs."
            )
        return self.refs[ref]

    async def _center(self, backend_id: int) -> tuple[float, float]:
        try:
            await self._send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend_id})
        except Exception:
            pass
        box = await self._send("DOM.getBoxModel", {"backendNodeId": backend_id})
        c = box["model"]["content"]
        return (c[0] + c[4]) / 2, (c[1] + c[5]) / 2

    async def click(self, ref: int) -> dict:
        await self.ensure()
        backend = self._resolve(ref)
        try:
            x, y = await self._center(backend)
            await self.client.click_xy(x, y)
            where = f"({x:.0f},{y:.0f})"
        except Exception:
            # Fallback: JS click via resolved node.
            node = await self._send("DOM.resolveNode", {"backendNodeId": backend})
            obj = node["object"]["objectId"]
            await self._send("Runtime.callFunctionOn", {
                "objectId": obj,
                "functionDeclaration": "function(){this.click();}",
            })
            where = "js-click"
        meta = self.ref_meta.get(ref, {})
        return {"clicked_ref": ref, "target": meta, "at": where}

    async def hover(self, ref: int) -> dict:
        await self.ensure()
        backend = self._resolve(ref)
        x, y = await self._center(backend)
        await self.client.move_mouse(x, y)
        return {"hovered_ref": ref, "at": f"({x:.0f},{y:.0f})"}

    async def type_text(self, text: str, ref: int | None = None, submit: bool = False) -> dict:
        await self.ensure()
        if ref is not None:
            backend = self._resolve(ref)
            try:
                await self._send("DOM.focus", {"backendNodeId": backend})
            except Exception:
                x, y = await self._center(backend)
                await self.client.click_xy(x, y)
        await self.client.type_text(text)
        if submit:
            await self.client.press_key("Enter")
        return {"typed": text, "ref": ref, "submitted": submit}

    async def press_key(self, key: str) -> dict:
        await self.ensure()
        await self.client.press_key(key)
        return {"key": key}

    async def click_xy(self, x: float, y: float) -> dict:
        await self.ensure()
        await self.client.click_xy(x, y)
        return {"clicked_at": [x, y]}

    async def get_text(self, ref: int | None = None) -> str:
        await self.ensure()
        if ref is None:
            return await self.client.evaluate("document.body.innerText.slice(0,8000)")
        backend = self._resolve(ref)
        node = await self._send("DOM.resolveNode", {"backendNodeId": backend})
        obj = node["object"]["objectId"]
        res = await self._send("Runtime.callFunctionOn", {
            "objectId": obj,
            "functionDeclaration": "function(){return this.innerText||this.value||'';}",
            "returnByValue": True,
        })
        return res.get("result", {}).get("value", "")

    async def eval_js(self, expression: str) -> Any:
        await self.ensure()
        return await self.client.evaluate(expression)

    async def screenshot(self) -> bytes:
        await self.ensure()
        result = await self._send("Page.captureScreenshot", {"format": "png"})
        return base64.b64decode(result["data"])

    # ---- tabs ---------------------------------------------------------------

    async def list_tabs(self) -> list[dict]:
        await self.ensure()
        pages = self.client.list_pages()
        return [{"tab_id": p.id, "title": p.title, "url": p.url,
                 "current": p.id == self.target_id} for p in pages]

    async def select_tab(self, tab_id: str) -> dict:
        await self.ensure()
        if self.client:
            await self.client.close()
        self.client = None
        self.target_id = tab_id
        await self.ensure()
        return await self.status()

    async def new_tab(self, url: str = "about:blank") -> dict:
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{CDP_PORT}/json/new?{url}", method="PUT")
        import json as _json
        data = _json.loads(urllib.request.urlopen(req, timeout=5).read())
        return await self.select_tab(data["id"])
