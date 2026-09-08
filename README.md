# Human Browser

Human-like browser automation for cloud agents and terminal environments.

**Strategy:** Playwright Chromium first (headed when `DISPLAY` is available, otherwise headless). If Playwright is unavailable or fails to launch, fall back to **Carbonyl** in a tmux split pane.

Both backends expose CDP on port **1112** with a real desktop Chrome user agent. Page state is always read and verified over CDP (`websockets` with `suppress_origin=True`). Input is routed through real keyboard/mouse channels.
