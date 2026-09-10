#!/usr/bin/env python3
"""Render a @@KEY@@ template using environment variables.

Usage: render.py <template> <output>
Every @@KEY@@ token is replaced by os.environ["KEY"] (must be set).
"""
from __future__ import annotations

import os
import re
import sys


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    tmpl, out = sys.argv[1], sys.argv[2]
    text = open(tmpl, encoding="utf-8").read()

    missing: list[str] = []

    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key not in os.environ:
            missing.append(key)
            return m.group(0)
        return os.environ[key]

    rendered = re.sub(r"@@([A-Z0-9_]+)@@", repl, text)
    if missing:
        sys.exit("Missing env vars for template: " + ", ".join(sorted(set(missing))))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(rendered)
    print(out)


if __name__ == "__main__":
    main()
