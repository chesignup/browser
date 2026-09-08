from __future__ import annotations

import os
from pathlib import Path

DESKTOP_CHROME_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

CARBONYL_CDP_PORT = 1112
CARBONYL_INSTALL_DIR = Path(
    os.environ.get("HUMAN_BROWSER_CARBONYL_DIR", "~/.local/share/human-browser/carbonyl")
).expanduser()
SESSION_FILE = Path(
    os.environ.get("HUMAN_BROWSER_SESSION", "~/.cache/human-browser/session.json")
).expanduser()
TMUX_CONF = Path("/exec-daemon/tmux.portal.conf")
