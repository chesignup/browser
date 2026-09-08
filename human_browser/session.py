from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from human_browser.constants import SESSION_FILE


@dataclass
class SessionState:
    backend: str
    cdp_port: int
    pane_id: str | None = None
    target_prefix: str | None = None
    playwright_profile: str | None = None
    browser_pid: int | None = None

    @classmethod
    def load(cls) -> SessionState | None:
        if not SESSION_FILE.exists():
            return None
        data = json.loads(SESSION_FILE.read_text())
        return cls(**data)

    def save(self) -> None:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(asdict(self), indent=2))

    def clear(self) -> None:
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()


def write_state(**kwargs: Any) -> SessionState:
    state = SessionState(**kwargs)
    state.save()
    return state
