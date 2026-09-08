from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from human_browser.constants import TMUX_CONF


def _tmux_base() -> list[str]:
    if TMUX_CONF.exists():
        return ["tmux", "-f", str(TMUX_CONF)]
    return ["tmux"]


def in_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


def ensure_tmux_config() -> None:
    tmux_conf = Path.home() / ".tmux.conf"
    required = [
        "set -g mouse on",
        "set -g allow-passthrough all",
        "set -g extended-keys on",
    ]
    existing = tmux_conf.read_text() if tmux_conf.exists() else ""
    additions = [line for line in required if line not in existing]
    if additions:
        tmux_conf.parent.mkdir(parents=True, exist_ok=True)
        with tmux_conf.open("a") as handle:
            if additions:
                handle.write("\n# human-browser settings\n")
                handle.write("\n".join(additions) + "\n")
    for line in required:
        key, value = line.split(" ", 2)[-2:]
        subprocess.run(
            _tmux_base() + ["set", "-g", key, value],
            check=False,
            capture_output=True,
        )


def split_pane(command: str) -> str:
    result = subprocess.run(
        _tmux_base()
        + [
            "split-window",
            "-h",
            "-p",
            "50",
            "-P",
            "-F",
            "#{pane_id}",
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def send_keys(pane_id: str, *keys: str) -> None:
    subprocess.run(
        _tmux_base() + ["send-keys", "-t", pane_id, *keys],
        check=True,
    )


def send_text(pane_id: str, text: str) -> None:
    subprocess.run(
        _tmux_base() + ["send-keys", "-t", pane_id, "-l", text],
        check=True,
    )


def send_mouse_click(pane_id: str, x: int, y: int, button: int = 1) -> None:
    """Send a real mouse click into a tmux pane using tmux mouse protocol."""
    down = f"MouseDown{button}"
    up = f"MouseUp{button}"
    subprocess.run(
        _tmux_base() + ["send-keys", "-M", "-t", pane_id, down, str(x), str(y)],
        check=True,
    )
    subprocess.run(
        _tmux_base() + ["send-keys", "-M", "-t", pane_id, up, str(x), str(y)],
        check=True,
    )


def click_with_xdotool(pane_id: str, x: int, y: int) -> None:
    """Fallback: click using xdotool against the pane's host window."""
    if not shutil.which("xdotool"):
        raise RuntimeError("xdotool is required for coordinate clicks outside tmux mouse mode")
    pane_info = subprocess.run(
        _tmux_base() + ["display-message", "-p", "-t", pane_id, "#{window_id}"],
        check=True,
        capture_output=True,
        text=True,
    )
    window_id = pane_info.stdout.strip()
    subprocess.run(["xdotool", "mousemove", "--window", window_id, str(x), str(y)], check=True)
    subprocess.run(["xdotool", "click", "--window", window_id, "1"], check=True)


def kill_pane(pane_id: str) -> None:
    subprocess.run(
        _tmux_base() + ["kill-pane", "-t", pane_id],
        check=False,
        capture_output=True,
    )
