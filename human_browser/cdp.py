from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

import websockets


@dataclass
class Target:
    id: str
    title: str
    url: str
    web_socket_debugger_url: str


class CDPClient:
    """Minimal Chrome DevTools Protocol client over WebSocket."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self._ws: Any | None = None
        self._next_id = 1

    def _fetch_json(self, path: str) -> Any:
        with urllib.request.urlopen(f"{self.base}{path}", timeout=5) as response:
            return json.loads(response.read().decode())

    def is_alive(self) -> bool:
        try:
            self._fetch_json("/json/version")
            return True
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def list_pages(self) -> list[Target]:
        targets = self._fetch_json("/json")
        pages: list[Target] = []
        for item in targets:
            if item.get("type") != "page":
                continue
            pages.append(
                Target(
                    id=item["id"],
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    web_socket_debugger_url=item["webSocketDebuggerUrl"],
                )
            )
        return pages

    def find_page(self, prefix: str | None = None) -> Target:
        pages = self.list_pages()
        if not pages:
            raise RuntimeError("No open browser pages found")
        if not prefix:
            return pages[0]
        for page in pages:
            if page.id.startswith(prefix) or prefix.lower() in page.title.lower():
                return page
        raise RuntimeError(f"Target not found: {prefix}")

    async def connect(self, target: Target | None = None) -> None:
        page = target or self.find_page()
        ws_url = page.web_socket_debugger_url
        try:
            self._ws = await websockets.connect(ws_url, suppress_origin=True)
        except TypeError:
            self._ws = await websockets.connect(ws_url, origin=None)

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self._ws is None:
            raise RuntimeError("CDP client is not connected")
        message_id = self._next_id
        self._next_id += 1
        await self._ws.send(
            json.dumps({"id": message_id, "method": method, "params": params or {}})
        )
        while True:
            raw = await self._ws.recv()
            message = json.loads(raw)
            if message.get("id") != message_id:
                continue
            if message.get("error"):
                raise RuntimeError(message["error"].get("message", str(message["error"])))
            return message.get("result")

    async def evaluate(self, expression: str) -> Any:
        result = await self.send(
            "Runtime.evaluate", {"expression": expression, "returnByValue": True}
        )
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            raise RuntimeError(details.get("text") or str(details))
        return result.get("result", {}).get("value")

    async def navigate(self, url: str, timeout: float = 30.0) -> None:
        # Closing the CDP connection while a navigation is still in flight aborts
        # it and leaves a chrome-error page. We must block until THIS navigation
        # finishes loading before returning (the caller then closes the socket).
        #
        # Page.enable replays a stale load event for the currently-loaded page,
        # so we correlate on the loaderId returned by Page.navigate and only
        # accept lifecycle "load"/"networkIdle" events for that loaderId.
        import asyncio

        await self.send("Page.enable")
        await self.send("Page.setLifecycleEventsEnabled", {"enabled": True})
        result = await self.send("Page.navigate", {"url": url})
        if result.get("errorText"):
            # Navigation failed to even start (e.g. bad scheme); nothing to wait.
            return
        loader_id = result.get("loaderId")
        try:
            await asyncio.wait_for(self._wait_for_load(loader_id), timeout)
        except asyncio.TimeoutError:
            pass

    async def _wait_for_load(self, loader_id: str | None) -> None:
        if self._ws is None:
            raise RuntimeError("CDP client is not connected")
        while True:
            raw = await self._ws.recv()
            message = json.loads(raw)
            if message.get("method") != "Page.lifecycleEvent":
                continue
            params = message.get("params", {})
            if loader_id and params.get("loaderId") != loader_id:
                continue  # stale event from a previous navigation
            if params.get("name") in ("load", "networkIdle"):
                return

    async def element_center(self, selector: str) -> tuple[float, float]:
        doc = await self.send("DOM.getDocument")
        node = await self.send(
            "DOM.querySelector",
            {"nodeId": doc["root"]["nodeId"], "selector": selector},
        )
        if not node.get("nodeId"):
            raise RuntimeError(f"Element not found: {selector}")
        box = await self.send("DOM.getBoxModel", {"nodeId": node["nodeId"]})
        # content is a quad: [x1,y1, x2,y2, x3,y3, x4,y4] (top-left, top-right,
        # bottom-right, bottom-left). Center = midpoint of the diagonal.
        content = box["model"]["content"]
        x1, y1 = content[0], content[1]
        x3, y3 = content[4], content[5]
        return (x1 + x3) / 2, (y1 + y3) / 2

    async def accessibility_tree(self) -> str:
        result = await self.send("Accessibility.getFullAXTree")
        nodes = result.get("nodes", [])
        lines: list[str] = []

        def walk(node: dict[str, Any], depth: int = 0) -> None:
            role = (node.get("role") or {}).get("value", "")
            name = (node.get("name") or {}).get("value", "")
            if role and role not in {"none", "generic"}:
                lines.append(f"{'  ' * depth}[{role}] {name}")
            for child in node.get("children", []):
                child_node = next(
                    (item for item in nodes if item.get("nodeId") == child.get("nodeId")),
                    child,
                )
                walk(child_node, depth + 1)

        if nodes:
            walk(nodes[0])
        return "\n".join(lines)

    async def html(self, selector: str | None = None) -> str:
        if selector:
            expression = (
                f"document.querySelector('{selector}')?.outerHTML || 'Element not found'"
            )
        else:
            expression = "document.documentElement.outerHTML"
        value = await self.evaluate(expression)
        return str(value)

    async def screenshot(self, path: str) -> str:
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        data = result["data"]
        with open(path, "wb") as handle:
            handle.write(__import__("base64").b64decode(data))
        return path

    # --- Native CDP input (works against any real Chrome, no Playwright needed) ---

    async def type_text(self, text: str) -> None:
        for ch in text:
            params = {"type": "keyDown", "text": ch}
            await self.send("Input.dispatchKeyEvent", params)
            await self.send("Input.dispatchKeyEvent", {"type": "keyUp", "text": ch})

    async def press_key(self, key: str) -> None:
        spec = _KEY_MAP.get(key) or _KEY_MAP.get(key.lower())
        if spec is None:
            # Single printable character fallback.
            if len(key) == 1:
                await self.type_text(key)
                return
            raise RuntimeError(f"Unknown key: {key}")
        down = {
            "type": "keyDown",
            "key": spec["key"],
            "code": spec["code"],
            "windowsVirtualKeyCode": spec["vk"],
            "nativeVirtualKeyCode": spec["vk"],
        }
        if spec.get("text"):
            down["text"] = spec["text"]
        await self.send("Input.dispatchKeyEvent", down)
        up = dict(down)
        up["type"] = "keyUp"
        await self.send("Input.dispatchKeyEvent", up)

    async def move_mouse(self, x: float, y: float) -> None:
        await self.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y},
        )

    async def click_xy(self, x: float, y: float, button: str = "left") -> None:
        await self.move_mouse(x, y)
        for event in ("mousePressed", "mouseReleased"):
            await self.send(
                "Input.dispatchMouseEvent",
                {
                    "type": event,
                    "x": x,
                    "y": y,
                    "button": button,
                    "buttons": 1,
                    "clickCount": 1,
                },
            )


_KEY_MAP = {
    "Enter": {"key": "Enter", "code": "Enter", "vk": 13, "text": "\r"},
    "Tab": {"key": "Tab", "code": "Tab", "vk": 9, "text": "\t"},
    "Backspace": {"key": "Backspace", "code": "Backspace", "vk": 8},
    "Delete": {"key": "Delete", "code": "Delete", "vk": 46},
    "Escape": {"key": "Escape", "code": "Escape", "vk": 27},
    "Space": {"key": " ", "code": "Space", "vk": 32, "text": " "},
    "ArrowLeft": {"key": "ArrowLeft", "code": "ArrowLeft", "vk": 37},
    "ArrowUp": {"key": "ArrowUp", "code": "ArrowUp", "vk": 38},
    "ArrowRight": {"key": "ArrowRight", "code": "ArrowRight", "vk": 39},
    "ArrowDown": {"key": "ArrowDown", "code": "ArrowDown", "vk": 40},
    "Home": {"key": "Home", "code": "Home", "vk": 36},
    "End": {"key": "End", "code": "End", "vk": 35},
    "PageUp": {"key": "PageUp", "code": "PageUp", "vk": 33},
    "PageDown": {"key": "PageDown", "code": "PageDown", "vk": 34},
}
