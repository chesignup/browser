from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.request import urlopen

from human_browser.cdp import CDPClient
from human_browser.constants import (
    CARBONYL_CDP_PORT,
    CARBONYL_INSTALL_DIR,
    DESKTOP_CHROME_USER_AGENT,
)
from human_browser.session import SessionState, write_state
from human_browser.tmux_input import (
    ensure_tmux_config,
    in_tmux,
    kill_pane,
    send_keys,
    send_mouse_click,
    send_text,
    split_pane,
)


class BrowserBackend(ABC):
    name: str

    @abstractmethod
    def start(self, url: str) -> SessionState: ...

    @abstractmethod
    def stop(self, state: SessionState) -> None: ...

    @abstractmethod
    def cdp(self, state: SessionState) -> CDPClient: ...


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


class PlaywrightBackend(BrowserBackend):
    name = "playwright"

    def start(self, url: str) -> SessionState:
        from playwright.sync_api import sync_playwright

        profile_dir = tempfile.mkdtemp(prefix="human-browser-")
        with sync_playwright() as playwright:
            chromium_path = playwright.chromium.executable_path

        command = [
            chromium_path,
            f"--remote-debugging-port={CARBONYL_CDP_PORT}",
            f"--user-agent={DESKTOP_CHROME_USER_AGENT}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ]
        if os.environ.get("DISPLAY"):
            command.insert(1, "--start-maximized")
        else:
            command.insert(1, "--headless=new")

        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        client = CDPClient(CARBONYL_CDP_PORT)
        for _ in range(50):
            if client.is_alive():
                break
            subprocess.run(["sleep", "0.2"], check=False)
        if not client.is_alive():
            process.kill()
            shutil.rmtree(profile_dir, ignore_errors=True)
            raise RuntimeError("Playwright Chromium failed to expose CDP on port 1112")
        return write_state(
            backend=self.name,
            cdp_port=CARBONYL_CDP_PORT,
            pane_id=None,
            target_prefix=None,
            playwright_profile=profile_dir,
            browser_pid=process.pid,
        )

    def stop(self, state: SessionState) -> None:
        if state.browser_pid:
            try:
                os.kill(state.browser_pid, 15)
            except ProcessLookupError:
                pass
        if state.playwright_profile and Path(state.playwright_profile).exists():
            shutil.rmtree(state.playwright_profile, ignore_errors=True)

    def cdp(self, state: SessionState) -> CDPClient:
        return CDPClient(state.cdp_port)


def install_carbonyl() -> Path:
    install_root = CARBONYL_INSTALL_DIR
    install_root.mkdir(parents=True, exist_ok=True)
    binary = next(install_root.glob("**/carbonyl"), None)
    if binary and binary.is_file():
        return binary.parent

    arch = os.uname().machine
    platform = "linux" if os.name != "darwin" else "macos"
    arch_name = "arm64" if arch in {"arm64", "aarch64"} else "amd64"
    archive_url = (
        f"https://github.com/fathyb/carbonyl/releases/download/v0.0.3/"
        f"carbonyl.{platform}-{arch_name}.zip"
    )
    archive_path = install_root / "carbonyl.zip"
    with urlopen(archive_url, timeout=60) as response, archive_path.open("wb") as handle:
        handle.write(response.read())
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(install_root)
    archive_path.unlink(missing_ok=True)
    binary = next(install_root.glob("**/carbonyl"))
    binary.chmod(0o755)
    return binary.parent


class CarbonylBackend(BrowserBackend):
    name = "carbonyl"

    def start(self, url: str) -> SessionState:
        if not in_tmux():
            raise RuntimeError(
                "Carbonyl backend requires an active tmux session. "
                "Start tmux first, then run human-browser start."
            )
        ensure_tmux_config()
        carbonyl_dir = install_carbonyl()
        carbonyl_bin = carbonyl_dir / "carbonyl"
        command = (
            f"cd '{carbonyl_dir}' && "
            f"./carbonyl --user-agent='{DESKTOP_CHROME_USER_AGENT}' "
            f"--remote-debugging-port={CARBONYL_CDP_PORT} '{url}'"
        )
        pane_id = split_pane(command)
        client = CDPClient(CARBONYL_CDP_PORT)
        for _ in range(30):
            if client.is_alive():
                break
            subprocess.run(["sleep", "0.2"], check=False)
        if not client.is_alive():
            kill_pane(pane_id)
            raise RuntimeError("Carbonyl failed to expose CDP on port 1112")
        return write_state(
            backend=self.name,
            cdp_port=CARBONYL_CDP_PORT,
            pane_id=pane_id,
            target_prefix=None,
            playwright_profile=None,
            browser_pid=None,
        )

    def stop(self, state: SessionState) -> None:
        if state.pane_id:
            kill_pane(state.pane_id)

    def cdp(self, state: SessionState) -> CDPClient:
        return CDPClient(state.cdp_port)

    def type_text(self, state: SessionState, text: str) -> None:
        if not state.pane_id:
            raise RuntimeError("No tmux pane attached to this session")
        send_text(state.pane_id, text)

    def press_key(self, state: SessionState, key: str) -> None:
        if not state.pane_id:
            raise RuntimeError("No tmux pane attached to this session")
        send_keys(state.pane_id, key)

    def click_xy(self, state: SessionState, x: int, y: int) -> None:
        if not state.pane_id:
            raise RuntimeError("No tmux pane attached to this session")
        send_mouse_click(state.pane_id, x, y)


def choose_backend(preferred: str | None = None) -> BrowserBackend:
    if preferred == "carbonyl":
        return CarbonylBackend()
    if preferred == "playwright":
        if not playwright_available():
            raise RuntimeError("Playwright is not installed")
        return PlaywrightBackend()
    if playwright_available():
        return PlaywrightBackend()
    return CarbonylBackend()


def run_async(coro):
    return asyncio.run(coro)
