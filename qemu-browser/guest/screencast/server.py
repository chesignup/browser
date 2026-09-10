#!/usr/bin/env python3
"""Mobile-friendly remote viewer for the guest's Chrome — now multi-tab.

Streams the selected tab as JPEG frames (via CDP Page.captureScreenshot polling,
reliable on headless Xvfb) over a WebSocket, shows a live tab bar of ALL open tabs
(so you can see what any/all agents are doing and switch between them), and forwards
taps/scrolls/keystrokes to the selected tab.

Runs INSIDE the guest, talking to Chrome on 127.0.0.1:<cdp>. Listens on 0.0.0.0:<port>.
Deps: python3-aiohttp
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import aiohttp
from aiohttp import web

CDP_PORT = int(os.environ.get("SCREENCAST_CDP_PORT", "9222"))
LISTEN_PORT = int(os.environ.get("SCREENCAST_PORT", "6081"))
FPS = float(os.environ.get("SCREENCAST_FPS", "8"))
CDP_BASE = f"http://127.0.0.1:{CDP_PORT}"
INDEX = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")

_KEYS = {
    "Enter": (13, "\r"), "Tab": (9, "\t"), "Backspace": (8, None),
    "Delete": (46, None), "Escape": (27, None), "ArrowLeft": (37, None),
    "ArrowUp": (38, None), "ArrowRight": (39, None), "ArrowDown": (40, None),
    "Home": (36, None), "End": (35, None), "PageUp": (33, None),
    "PageDown": (34, None),
}


async def list_targets(session: aiohttp.ClientSession) -> list[dict]:
    async with session.get(f"{CDP_BASE}/json") as r:
        return [t for t in await r.json() if t.get("type") == "page"]


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0
        self._waiters: dict[int, asyncio.Future] = {}
        self._reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for m in self.ws:
                if m.type != aiohttp.WSMsgType.TEXT:
                    break
                data = json.loads(m.data)
                fut = self._waiters.pop(data.get("id"), None)
                if fut and not fut.done():
                    fut.set_result(data)
        except Exception:
            pass

    async def call(self, method, params=None, timeout=15):
        self._id += 1
        mid = self._id
        fut = asyncio.get_event_loop().create_future()
        self._waiters[mid] = fut
        await self.ws.send_json({"id": mid, "method": method, "params": params or {}})
        data = await asyncio.wait_for(fut, timeout)
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))
        return data.get("result", {})

    async def close(self):
        self._reader.cancel()
        try:
            await self.ws.close()
        except Exception:
            pass


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    client = web.WebSocketResponse(max_msg_size=0)
    await client.prepare(request)
    session = aiohttp.ClientSession()
    cdp: CDP | None = None
    current_id: str | None = None
    css = {"w": 1280.0, "h": 720.0}

    async def connect_target(target_id: str | None):
        nonlocal cdp, current_id
        targets = await list_targets(session)
        if not targets:
            raise RuntimeError("no page targets")
        target = None
        if target_id:
            target = next((t for t in targets if t["id"] == target_id), None)
        if target is None:
            target = targets[0]
        if cdp is not None:
            await cdp.close()
        page_ws = await session.ws_connect(target["webSocketDebuggerUrl"], max_msg_size=0)
        cdp = CDP(page_ws)
        current_id = target["id"]
        await cdp.call("Page.enable")
        try:
            m = await cdp.call("Page.getLayoutMetrics")
            vp = m.get("cssLayoutViewport") or {}
            if vp.get("clientWidth"):
                css["w"] = float(vp["clientWidth"]); css["h"] = float(vp["clientHeight"])
        except Exception:
            pass

    async def send_tabs():
        try:
            targets = await list_targets(session)
            await client.send_json({
                "tabs": [{"id": t["id"], "title": (t.get("title") or t.get("url") or "")[:60],
                          "url": t.get("url", "")} for t in targets],
                "current": current_id,
            })
        except Exception:
            pass

    try:
        await connect_target(None)
        await send_tabs()

        async def stream():
            interval = 1.0 / FPS
            tick = 0
            while not client.closed:
                start = asyncio.get_event_loop().time()
                try:
                    shot = await cdp.call("Page.captureScreenshot",
                                          {"format": "jpeg", "quality": 55}, timeout=10)
                    await client.send_json({"frame": shot["data"], "w": css["w"], "h": css["h"]})
                except Exception as exc:  # target may have closed; try to recover
                    try:
                        await connect_target(None)
                    except Exception:
                        await client.send_json({"error": str(exc)})
                        await asyncio.sleep(0.5)
                tick += 1
                if tick % max(1, int(FPS * 2)) == 0:
                    await send_tabs()
                elapsed = asyncio.get_event_loop().time() - start
                await asyncio.sleep(max(0.0, interval - elapsed))

        async def inputs():
            async for m in client:
                if m.type != aiohttp.WSMsgType.TEXT:
                    break
                ev = json.loads(m.data)
                t = ev.get("t")
                if t == "select_tab":
                    try:
                        await connect_target(ev.get("id"))
                        await send_tabs()
                    except Exception:
                        pass
                    continue
                if t == "list_tabs":
                    await send_tabs(); continue
                if cdp is None:
                    continue
                if t in ("click", "down", "up", "move"):
                    x = float(ev.get("nx", 0)) * css["w"]; y = float(ev.get("ny", 0)) * css["h"]
                    if t == "click":
                        for phase in ("mousePressed", "mouseReleased"):
                            await cdp.call("Input.dispatchMouseEvent", {"type": phase, "x": x, "y": y,
                                "button": "left", "buttons": 1, "clickCount": 1})
                    else:
                        phase = {"down": "mousePressed", "up": "mouseReleased", "move": "mouseMoved"}[t]
                        await cdp.call("Input.dispatchMouseEvent", {"type": phase, "x": x, "y": y,
                            "button": "left", "buttons": 0 if t == "move" else 1, "clickCount": 1})
                elif t == "scroll":
                    x = float(ev.get("nx", 0.5)) * css["w"]; y = float(ev.get("ny", 0.5)) * css["h"]
                    await cdp.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y,
                        "deltaX": float(ev.get("dx", 0)), "deltaY": float(ev.get("dy", 0))})
                elif t == "text":
                    await cdp.call("Input.insertText", {"text": ev.get("text", "")})
                elif t == "key":
                    spec = _KEYS.get(ev.get("key", ""))
                    if spec:
                        vk, text = spec
                        base = {"key": ev["key"], "code": ev["key"],
                                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
                        if text:
                            base["text"] = text
                        await cdp.call("Input.dispatchKeyEvent", {**base, "type": "keyDown"})
                        await cdp.call("Input.dispatchKeyEvent", {**base, "type": "keyUp"})
                elif t == "reload":
                    await cdp.call("Page.reload")
                elif t == "nav":
                    await cdp.call("Page.navigate", {"url": ev.get("url", "about:blank")})
                elif t == "new_tab":
                    import urllib.request
                    urllib.request.urlopen(urllib.request.Request(
                        f"{CDP_BASE}/json/new?about:blank", method="PUT"), timeout=5).read()
                    await send_tabs()

        await asyncio.gather(stream(), inputs())
    except Exception as exc:  # noqa: BLE001
        try:
            await client.send_json({"error": str(exc)})
        except Exception:
            pass
    finally:
        if cdp is not None:
            await cdp.close()
        await session.close()
    return client


async def index_handler(_: web.Request) -> web.Response:
    return web.Response(text=INDEX, content_type="text/html")


def main() -> None:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", ws_handler)
    web.run_app(app, host="0.0.0.0", port=LISTEN_PORT)


if __name__ == "__main__":
    main()
