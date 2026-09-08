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

    async def navigate(self, url: str) -> None:
        await self.send("Page.navigate", {"url": url})

    async def element_center(self, selector: str) -> tuple[float, float]:
        doc = await self.send("DOM.getDocument")
        node = await self.send(
            "DOM.querySelector",
            {"nodeId": doc["root"]["nodeId"], "selector": selector},
        )
        if not node.get("nodeId"):
            raise RuntimeError(f"Element not found: {selector}")
        box = await self.send("DOM.getBoxModel", {"nodeId": node["nodeId"]})
        content = box["model"]["content"]
        x1, y1, _, x3, y3, *_ = content
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
