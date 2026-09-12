#!/usr/bin/env python3
"""Unified Chrome CDP Bridge & Remote Browser Tab Viewer.

Runs inside the guest VM.
- Connects upstream to Chrome's internal remote debugging port (127.0.0.1:9221).
- Listens on 0.0.0.0:9222 (standard CDP debug port) and 0.0.0.0:6081 (viewer port).
- Serves:
  1. Standard CDP HTTP endpoints (/json/version, /json, /json/new, etc.) with Host
     and WebSocket URL rewriting so remote tools and `chrome://inspect` work seamlessly.
  2. Built-in DevTools inspector (/devtools/*) with CSP fixed and Origin stripped
     so any remote browser can load Chrome DevTools with screencast.
  3. Bi-directional WebSocket proxying on /devtools/* for CDP and DevTools.
  4. Butter-smooth interactive web browser tab viewer on GET / (/ws/viewer)
     using Page.startScreencast with frame ack, mouse/touch, keyboard, Omnibox,
     and tab switching.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("cdp_bridge")

CHROME_INTERNAL_CDP = int(os.environ.get("CHROME_INTERNAL_CDP", "9221"))
CDP_LISTEN_PORT = int(os.environ.get("CDP_LISTEN_PORT", "9222"))
VIEWER_LISTEN_PORT = int(os.environ.get("VIEWER_LISTEN_PORT", "6081"))

UPSTREAM_HTTP = f"http://127.0.0.1:{CHROME_INTERNAL_CDP}"
UPSTREAM_WS = f"ws://127.0.0.1:{CHROME_INTERNAL_CDP}"

INDEX_HTML_PATH = Path(__file__).parent / "index.html"


def get_index_html() -> str:
    if INDEX_HTML_PATH.exists():
        return INDEX_HTML_PATH.read_text(encoding="utf-8")
    return "<h1>Chromebox Viewer: index.html not found</h1>"


# ---------------------------------------------------------------------------
# Upstream Chrome HTTP Helpers
# ---------------------------------------------------------------------------

async def fetch_upstream_json(path: str) -> Any:
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{UPSTREAM_HTTP}{path}", timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


async def get_page_targets() -> list[dict]:
    targets = await fetch_upstream_json("/json")
    if not targets or not isinstance(targets, list):
        return []
    return [t for t in targets if t.get("type") == "page"]


# ---------------------------------------------------------------------------
# Active Tab Screencast & Controller for Web Viewers
# ---------------------------------------------------------------------------

class TabController:
    """Manages active tab CDP screencast and broadcasts to connected web viewers."""

    def __init__(self):
        self.active_target_id: str | None = None
        self.cdp_session: aiohttp.ClientSession | None = None
        self.cdp_ws: aiohttp.ClientWebSocketResponse | None = None
        self.viewers: set[web.WebSocketResponse] = set()
        self.lock = asyncio.Lock()
        self._seq = 0
        self._waiters: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self.last_frame: dict | None = None
        self.current_url: str = ""
        self.current_title: str = ""
        self.device_metrics: dict = {"width": 1920, "height": 1080}

    async def add_viewer(self, ws: web.WebSocketResponse):
        self.viewers.add(ws)
        # Send initial tabs list and current frame if available
        await self.broadcast_tabs()
        if self.last_frame:
            try:
                await ws.send_json(self.last_frame)
            except Exception:
                pass
        if not self.active_target_id or not self.cdp_ws or self.cdp_ws.closed:
            await self.ensure_active_tab()

    def remove_viewer(self, ws: web.WebSocketResponse):
        self.viewers.discard(ws)

    async def broadcast(self, msg: dict):
        dead = []
        for v in list(self.viewers):
            try:
                await v.send_json(msg)
            except Exception:
                dead.append(v)
        for d in dead:
            self.viewers.discard(d)

    async def broadcast_tabs(self):
        targets = await get_page_targets()
        tab_list = [
            {
                "id": t["id"],
                "title": t.get("title") or t.get("url") or "Tab",
                "url": t.get("url") or "",
                "favicon": t.get("faviconUrl") or "",
            }
            for t in targets
        ]
        await self.broadcast({
            "type": "tabs",
            "tabs": tab_list,
            "active": self.active_target_id,
        })

    async def ensure_active_tab(self, target_id: str | None = None):
        async with self.lock:
            targets = await get_page_targets()
            if not targets:
                return

            chosen = None
            if target_id:
                chosen = next((t for t in targets if t["id"] == target_id), None)
            if not chosen and self.active_target_id:
                chosen = next((t for t in targets if t["id"] == self.active_target_id), None)
            if not chosen:
                chosen = targets[0]

            new_target_id = chosen["id"]
            if new_target_id == self.active_target_id and self.cdp_ws and not self.cdp_ws.closed:
                return

            await self._disconnect_cdp()
            self.active_target_id = new_target_id
            self.current_url = chosen.get("url", "")
            self.current_title = chosen.get("title", "")
            await self._connect_cdp(chosen["webSocketDebuggerUrl"])
            await self.broadcast_tabs()

    async def _disconnect_cdp(self):
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self.cdp_ws and not self.cdp_ws.closed:
            try:
                await self.cdp_ws.close()
            except Exception:
                pass
        self.cdp_ws = None
        if self.cdp_session:
            await self.cdp_session.close()
            self.cdp_session = None

    async def _connect_cdp(self, ws_url: str):
        try:
            self.cdp_session = aiohttp.ClientSession()
            # Strip origin so Chrome never rejects connection with 403
            self.cdp_ws = await self.cdp_session.ws_connect(
                ws_url,
                headers={"Host": f"127.0.0.1:{CHROME_INTERNAL_CDP}"},
                origin=None,
                max_msg_size=0,
            )
            self._reader_task = asyncio.create_task(self._cdp_reader())

            await self.call_cdp("Page.enable")
            await self.call_cdp("DOM.enable")
            await self.call_cdp("Runtime.enable")
            try:
                metrics = await self.call_cdp("Page.getLayoutMetrics")
                vp = metrics.get("cssLayoutViewport") or {}
                if vp.get("clientWidth"):
                    self.device_metrics["width"] = float(vp["clientWidth"])
                    self.device_metrics["height"] = float(vp["clientHeight"])
            except Exception:
                pass

            await self.call_cdp("Page.startScreencast", {
                "format": "jpeg",
                "quality": 85,
                "everyNthFrame": 1,
            })
            log.info("Started screencast on target %s", self.active_target_id)
        except Exception as exc:
            log.warning("Failed to connect CDP to %s: %s", ws_url, exc)

    async def _cdp_reader(self):
        try:
            async for msg in self.cdp_ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    break
                data = json.loads(msg.data)
                mid = data.get("id")
                if mid and mid in self._waiters:
                    fut = self._waiters.pop(mid)
                    if not fut.done():
                        fut.set_result(data)
                    continue

                method = data.get("method")
                params = data.get("params", {})
                if method == "Page.screencastFrame":
                    sid = params.get("sessionId")
                    meta = params.get("metadata", {})
                    dw = meta.get("deviceWidth")
                    dh = meta.get("deviceHeight")
                    if dw and dh:
                        self.device_metrics["width"] = float(dw)
                        self.device_metrics["height"] = float(dh)
                    frame_msg = {
                        "type": "frame",
                        "data": params.get("data", ""),
                        "sessionId": sid,
                        "meta": meta,
                        "deviceWidth": self.device_metrics["width"],
                        "deviceHeight": self.device_metrics["height"],
                    }
                    self.last_frame = frame_msg
                    await self.broadcast(frame_msg)

                elif method == "Page.frameNavigated":
                    frame = params.get("frame", {})
                    if not frame.get("parentId"):
                        self.current_url = frame.get("url", "")
                        await self.broadcast({
                            "type": "navigated",
                            "url": self.current_url,
                        })
                        await self.broadcast_tabs()

                elif method == "Page.loadEventFired":
                    await self.broadcast_tabs()

                elif method == "Inspector.detached" or method == "Target.detachedFromTarget":
                    log.info("Target detached; looking for new active tab")
                    asyncio.create_task(self.ensure_active_tab())
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning("CDP reader stopped: %s", exc)

    async def call_cdp(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        if not self.cdp_ws or self.cdp_ws.closed:
            raise RuntimeError("CDP WebSocket not connected")
        self._seq += 1
        seq = self._seq
        fut = asyncio.get_event_loop().create_future()
        self._waiters[seq] = fut
        await self.cdp_ws.send_json({"id": seq, "method": method, "params": params or {}})
        try:
            res = await asyncio.wait_for(fut, timeout)
            return res.get("result", {})
        except Exception:
            self._waiters.pop(seq, None)
            raise

    async def handle_action(self, ev: dict):
        t = ev.get("type")
        if t == "ack":
            sid = ev.get("sessionId")
            if sid and self.cdp_ws and not self.cdp_ws.closed:
                await self.cdp_ws.send_json({
                    "id": 999999,
                    "method": "Page.screencastFrameAck",
                    "params": {"sessionId": sid},
                })

        elif t == "select_tab":
            tid = ev.get("id")
            if tid:
                await self.ensure_active_tab(tid)

        elif t == "refresh_tabs":
            await self.broadcast_tabs()

        elif t == "new_tab":
            url = ev.get("url") or "about:blank"
            encoded_url = urllib.parse.quote(url, safe="")
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{UPSTREAM_HTTP}/json/new?{encoded_url}") as r:
                    data = await r.json()
                    new_id = data.get("id")
                    if new_id:
                        await self.ensure_active_tab(new_id)

        elif t == "close_tab":
            tid = ev.get("id") or self.active_target_id
            if tid:
                async with aiohttp.ClientSession() as s:
                    async with s.get(f"{UPSTREAM_HTTP}/json/close/{tid}"):
                        pass
                await asyncio.sleep(0.2)
                await self.ensure_active_tab()

        elif t == "navigate":
            url = ev.get("url", "").strip()
            if url:
                if not re.match(r"^[a-zA-Z]+://", url):
                    if "." in url and not url.startswith("localhost"):
                        url = "https://" + url
                    else:
                        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(url)}"
                await self.call_cdp("Page.navigate", {"url": url})

        elif t == "reload":
            await self.call_cdp("Page.reload")

        elif t == "history":
            delta = int(ev.get("delta", 0))
            if delta != 0:
                hist = await self.call_cdp("Page.getNavigationHistory")
                idx = hist.get("currentIndex", 0)
                entries = hist.get("entries", [])
                target_idx = idx + delta
                if 0 <= target_idx < len(entries):
                    entry_id = entries[target_idx]["id"]
                    await self.call_cdp("Page.navigateToHistoryEntry", {"entryId": entry_id})

        elif t == "mouse":
            m_event = ev.get("event")  # mousePressed, mouseReleased, mouseMoved, mouseWheel
            x = float(ev.get("x", 0))
            y = float(ev.get("y", 0))
            button = ev.get("button", "left")
            click_count = int(ev.get("clickCount", 1))
            delta_x = float(ev.get("deltaX", 0))
            delta_y = float(ev.get("deltaY", 0))

            params = {
                "type": m_event,
                "x": x,
                "y": y,
                "button": button,
                "clickCount": click_count,
            }
            if m_event == "mouseWheel":
                params["deltaX"] = delta_x
                params["deltaY"] = delta_y
            await self.call_cdp("Input.dispatchMouseEvent", params)

        elif t == "key":
            k_event = ev.get("event", "keyDown")
            params = {
                "type": k_event,
                "key": ev.get("key", ""),
                "code": ev.get("code", ""),
                "text": ev.get("text", ""),
                "windowsVirtualKeyCode": int(ev.get("keyCode", 0)),
            }
            await self.call_cdp("Input.dispatchKeyEvent", params)

        elif t == "insertText":
            text = ev.get("text", "")
            if text:
                await self.call_cdp("Input.insertText", {"text": text})


tab_controller = TabController()


# ---------------------------------------------------------------------------
# HTTP Route Handlers
# ---------------------------------------------------------------------------

routes = web.RouteTableDef()


@routes.get("/")
async def handle_root(request: web.Request):
    accept = request.headers.get("Accept", "")
    # If explicitly requesting JSON, or a tool using /?json
    if "application/json" in accept and "text/html" not in accept:
        return await handle_json_list(request)
    if "json" in request.query:
        return await handle_json_list(request)
    # Browser client gets the rich tab viewer
    return web.Response(text=get_index_html(), content_type="text/html", charset="utf-8")


@routes.get("/json/version")
async def handle_json_version(request: web.Request):
    host = request.host
    data = await fetch_upstream_json("/json/version")
    if not data:
        return web.Response(status=502, text="Chrome not responding")
    if "webSocketDebuggerUrl" in data:
        data["webSocketDebuggerUrl"] = re.sub(
            r"ws://[^/]+", f"ws://{host}", data["webSocketDebuggerUrl"]
        )
    return web.json_response(data)


@routes.get("/json")
@routes.get("/json/list")
async def handle_json_list(request: web.Request):
    host = request.host
    targets = await fetch_upstream_json("/json")
    if targets is None:
        return web.Response(status=502, text="Chrome not responding")
    for t in targets:
        tid = t.get("id", "")
        if "webSocketDebuggerUrl" in t:
            t["webSocketDebuggerUrl"] = f"ws://{host}/devtools/page/{tid}"
        # Direct inspector URL on this host with CSP fix
        t["devtoolsFrontendUrl"] = f"/devtools/inspector.html?ws={host}/devtools/page/{tid}"
    return web.json_response(targets)


@routes.get("/json/protocol")
async def handle_json_protocol(request: web.Request):
    data = await fetch_upstream_json("/json/protocol")
    if not data:
        return web.Response(status=502, text="Chrome not responding")
    return web.json_response(data)


@routes.get("/json/new")
@routes.put("/json/new")
async def handle_json_new(request: web.Request):
    query = request.query_string
    target_url = f"{UPSTREAM_HTTP}/json/new"
    if query:
        target_url += f"?{query}"
    async with aiohttp.ClientSession() as s:
        async with s.get(target_url) as resp:
            data = await resp.json()
            if "webSocketDebuggerUrl" in data:
                data["webSocketDebuggerUrl"] = re.sub(
                    r"ws://[^/]+", f"ws://{request.host}", data["webSocketDebuggerUrl"]
                )
            if "id" in data:
                data["devtoolsFrontendUrl"] = f"/devtools/inspector.html?ws={request.host}/devtools/page/{data['id']}"
            return web.json_response(data)


@routes.get(r"/json/activate/{id}")
async def handle_json_activate(request: web.Request):
    tid = request.match_info["id"]
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{UPSTREAM_HTTP}/json/activate/{tid}") as resp:
            text = await resp.text()
            return web.Response(text=text, status=resp.status)


@routes.get(r"/json/close/{id}")
async def handle_json_close(request: web.Request):
    tid = request.match_info["id"]
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{UPSTREAM_HTTP}/json/close/{tid}") as resp:
            text = await resp.text()
            return web.Response(text=text, status=resp.status)


# ---------------------------------------------------------------------------
# DevTools Static Assets & WebSocket Proxy
# ---------------------------------------------------------------------------

@routes.get(r"/devtools/{path:.*}")
async def handle_devtools(request: web.Request):
    path = request.match_info["path"]

    # 1. Handle WebSocket upgrade for DevTools
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await proxy_devtools_websocket(request, f"{UPSTREAM_WS}/devtools/{path}")

    # 2. Proxy static files (JS, CSS, HTML, PNG, JSON, SourceMaps)
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{UPSTREAM_HTTP}/devtools/{path}") as resp:
            body = await resp.read()
            content_type = resp.headers.get("Content-Type", "application/octet-stream")

            # Rewrite CSP on DevTools HTML entrypoints to allow ws/wss from any host
            if path.endswith(".html") or "text/html" in content_type:
                html = body.decode("utf-8", errors="ignore")
                # Replace restricted localhost ws connect-src with open ws/wss
                html = re.sub(
                    r"ws://127\.0\.0\.1:\*",
                    r"* ws: wss:",
                    html,
                )
                body = html.encode("utf-8")

            headers = {
                "Content-Type": content_type,
                "Cache-Control": "public, max-age=3600" if not path.endswith(".html") else "no-cache",
            }
            return web.Response(body=body, status=resp.status, headers=headers)


async def proxy_devtools_websocket(request: web.Request, upstream_url: str):
    ws_client = web.WebSocketResponse(max_msg_size=0)
    await ws_client.prepare(request)

    session = aiohttp.ClientSession()
    try:
        # Crucial: omit origin so Chrome does not return 403 Forbidden
        async with session.ws_connect(
            upstream_url,
            headers={"Host": f"127.0.0.1:{CHROME_INTERNAL_CDP}"},
            origin=None,
            max_msg_size=0,
        ) as ws_upstream:

            async def client_to_upstream():
                async for msg in ws_client:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await ws_upstream.send_str(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await ws_upstream.send_bytes(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                        break

            async def upstream_to_client():
                async for msg in ws_upstream:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await ws_client.send_str(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await ws_client.send_bytes(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                        break

            await asyncio.gather(client_to_upstream(), upstream_to_client(), return_exceptions=True)
    except Exception as exc:
        log.warning("DevTools WS proxy ended: %s", exc)
    finally:
        await session.close()
        await ws_client.close()
    return ws_client


# ---------------------------------------------------------------------------
# Interactive Web Browser Tab Viewer WebSocket (/ws/viewer)
# ---------------------------------------------------------------------------

@routes.get("/ws/viewer")
@routes.get("/ws")  # backwards compatible with existing screencast path
async def handle_viewer_websocket(request: web.Request):
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(request)
    await tab_controller.add_viewer(ws)

    try:
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                break
            try:
                ev = json.loads(msg.data)
                await tab_controller.handle_action(ev)
            except Exception as exc:
                log.debug("Action error: %s", exc)
    finally:
        tab_controller.remove_viewer(ws)
    return ws


# ---------------------------------------------------------------------------
# Application Startup (Dual Port Listeners)
# ---------------------------------------------------------------------------

async def make_app() -> web.Application:
    app = web.Application()
    app.add_routes(routes)
    return app


async def main():
    app = await make_app()
    runner = web.AppRunner(app)
    await runner.setup()

    # 1. Listen on primary CDP port (9222)
    site_cdp = web.TCPSite(runner, "0.0.0.0", CDP_LISTEN_PORT)
    await site_cdp.start()
    log.info("CDP bridge listening on 0.0.0.0:%d (upstream Chrome -> :%d)", CDP_LISTEN_PORT, CHROME_INTERNAL_CDP)

    # 2. Listen on viewer port (6081) if distinct
    if VIEWER_LISTEN_PORT != CDP_LISTEN_PORT:
        site_viewer = web.TCPSite(runner, "0.0.0.0", VIEWER_LISTEN_PORT)
        await site_viewer.start()
        log.info("Web viewer listening on 0.0.0.0:%d", VIEWER_LISTEN_PORT)

    # Keep running forever
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
