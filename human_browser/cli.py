from __future__ import annotations

import argparse
import json
import sys

from human_browser.backends import (
    CarbonylBackend,
    PlaywrightBackend,
    choose_backend,
    playwright_available,
    run_async,
)
from human_browser.cdp import CDPClient
from human_browser.session import SessionState


def _load_state() -> SessionState:
    state = SessionState.load()
    if not state:
        print("No active human-browser session. Run: human-browser start <url>", file=sys.stderr)
        sys.exit(1)
    return state


def _backend_for(state: SessionState):
    if state.backend == "carbonyl":
        return CarbonylBackend()
    return PlaywrightBackend()


async def _with_cdp(state: SessionState, fn):
    backend = _backend_for(state)
    client = backend.cdp(state)
    if not client.is_alive():
        print("Browser CDP endpoint is not reachable.", file=sys.stderr)
        sys.exit(1)
    target = client.find_page(state.target_prefix)
    await client.connect(target)
    try:
        return await fn(client, target)
    finally:
        await client.close()


def cmd_start(args: argparse.Namespace) -> None:
    try:
        backend = choose_backend(args.backend)
        state = backend.start(args.url)
    except Exception as exc:
        if args.backend or not playwright_available():
            raise
        print(f"Playwright launch failed ({exc}); falling back to Carbonyl.", file=sys.stderr)
        backend = CarbonylBackend()
        state = backend.start(args.url)
    print(
        json.dumps(
            {
                "backend": state.backend,
                "cdp_port": state.cdp_port,
                "pane_id": state.pane_id,
                "browser_pid": state.browser_pid,
            },
            indent=2,
        )
    )


def cmd_status(_: argparse.Namespace) -> None:
    state = SessionState.load()
    if not state:
        print(json.dumps({"active": False}))
        return
    client = CDPClient(state.cdp_port)
    print(
        json.dumps(
            {
                "active": True,
                "backend": state.backend,
                "cdp_port": state.cdp_port,
                "cdp_alive": client.is_alive(),
                "pane_id": state.pane_id,
            },
            indent=2,
        )
    )


def cmd_stop(_: argparse.Namespace) -> None:
    state = SessionState.load()
    if not state:
        print("No active session.")
        return
    _backend_for(state).stop(state)
    state.clear()
    print("Session stopped.")


def cmd_list(_: argparse.Namespace) -> None:
    state = _load_state()

    async def action(client, _target):
        for page in client.list_pages():
            print(f"{page.id[:8]}  {page.title[:50]:<50}  {page.url}")

    run_async(_with_cdp(state, action))


def cmd_nav(args: argparse.Namespace) -> None:
    state = _load_state()

    async def action(client, _target):
        await client.navigate(args.url)
        print(f"Navigated to {args.url}")

    run_async(_with_cdp(state, action))


def cmd_eval(args: argparse.Namespace) -> None:
    state = _load_state()

    async def action(client, _target):
        value = await client.evaluate(args.expression)
        if isinstance(value, (dict, list)):
            print(json.dumps(value, indent=2))
        else:
            print(value)

    run_async(_with_cdp(state, action))


def cmd_html(args: argparse.Namespace) -> None:
    state = _load_state()

    async def action(client, _target):
        print(await client.html(args.selector))

    run_async(_with_cdp(state, action))


def cmd_snap(_: argparse.Namespace) -> None:
    state = _load_state()

    async def action(client, _target):
        print(await client.accessibility_tree())

    run_async(_with_cdp(state, action))


def cmd_shot(args: argparse.Namespace) -> None:
    state = _load_state()

    async def action(client, _target):
        path = await client.screenshot(args.output)
        print(path)

    run_async(_with_cdp(state, action))


def cmd_type(args: argparse.Namespace) -> None:
    state = _load_state()
    if state.backend == "carbonyl":
        CarbonylBackend().type_text(state, args.text)
        print(f"Typed via tmux: {args.text}")
        return
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{state.cdp_port}")
        page = browser.contexts[0].pages[0]
        page.keyboard.type(args.text)
        print(f"Typed via Playwright: {args.text}")


def cmd_key(args: argparse.Namespace) -> None:
    state = _load_state()
    if state.backend == "carbonyl":
        CarbonylBackend().press_key(state, args.key)
        print(f"Sent key via tmux: {args.key}")
        return
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{state.cdp_port}")
        page = browser.contexts[0].pages[0]
        page.keyboard.press(args.key)
        print(f"Sent key via Playwright: {args.key}")


def cmd_clickxy(args: argparse.Namespace) -> None:
    state = _load_state()
    if state.backend == "carbonyl":
        CarbonylBackend().click_xy(state, args.x, args.y)
        print(f"Clicked via tmux mouse at ({args.x}, {args.y})")
        return
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{state.cdp_port}")
        page = browser.contexts[0].pages[0]
        page.mouse.click(args.x, args.y)
        print(f"Clicked via Playwright at ({args.x}, {args.y})")


def cmd_click(args: argparse.Namespace) -> None:
    state = _load_state()

    async def action(client, _target):
        x, y = await client.element_center(args.selector)
        if state.backend == "carbonyl":
            CarbonylBackend().click_xy(state, int(x), int(y))
            print(f"Clicked {args.selector} via tmux mouse at ({int(x)}, {int(y)})")
        else:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{state.cdp_port}"
                )
                page = browser.contexts[0].pages[0]
                page.mouse.click(x, y)
                print(f"Clicked {args.selector} via Playwright at ({x}, {y})")

    run_async(_with_cdp(state, action))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="human-browser",
        description="Human-like browser automation (Playwright first, Carbonyl fallback).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Start a browser session")
    start.add_argument("url", default="https://example.com", nargs="?")
    start.add_argument("--backend", choices=["playwright", "carbonyl"])
    start.set_defaults(func=cmd_start)

    sub.add_parser("status", help="Show session status").set_defaults(func=cmd_status)
    sub.add_parser("stop", help="Stop the active session").set_defaults(func=cmd_stop)
    sub.add_parser("list", help="List open tabs").set_defaults(func=cmd_list)

    nav = sub.add_parser("nav", help="Navigate the active tab")
    nav.add_argument("url")
    nav.set_defaults(func=cmd_nav)

    evaluate = sub.add_parser("eval", help="Evaluate JavaScript via CDP")
    evaluate.add_argument("expression")
    evaluate.set_defaults(func=cmd_eval)

    html = sub.add_parser("html", help="Get page HTML via CDP")
    html.add_argument("selector", nargs="?")
    html.set_defaults(func=cmd_html)

    sub.add_parser("snap", help="Print accessibility tree via CDP").set_defaults(func=cmd_snap)

    shot = sub.add_parser("shot", help="Capture screenshot via CDP")
    shot.add_argument("output", nargs="?", default="/tmp/human-browser-shot.png")
    shot.set_defaults(func=cmd_shot)

    type_cmd = sub.add_parser("type", help="Type text via real keyboard input")
    type_cmd.add_argument("text")
    type_cmd.set_defaults(func=cmd_type)

    key = sub.add_parser("key", help="Press a key via real keyboard input")
    key.add_argument("key")
    key.set_defaults(func=cmd_key)

    clickxy = sub.add_parser("clickxy", help="Click coordinates via real mouse input")
    clickxy.add_argument("x", type=int)
    clickxy.add_argument("y", type=int)
    clickxy.set_defaults(func=cmd_clickxy)

    click = sub.add_parser("click", help="Click selector (coords from CDP, input via mouse)")
    click.add_argument("selector")
    click.set_defaults(func=cmd_click)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
