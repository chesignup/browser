#!/usr/bin/env python3
"""Minimal QMP client: run an HMP monitor command over the QMP unix socket.

Usage: qmp.py <socket> <hmp-command...>
Example: qmp.py var/qmp.sock "savevm clean"
Prints the HMP command's textual output.
"""
from __future__ import annotations

import json
import socket
import sys


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sock_path = sys.argv[1]
    hmp = " ".join(sys.argv[2:])

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(120)
    s.connect(sock_path)
    f = s.makefile("rwb", buffering=0)

    def recv_json():
        line = f.readline()
        return json.loads(line.decode()) if line else None

    recv_json()  # QMP greeting
    f.write(json.dumps({"execute": "qmp_capabilities"}).encode() + b"\n")
    while True:  # read until the capabilities return
        msg = recv_json()
        if msg is None:
            sys.exit("QMP: connection closed during handshake")
        if "return" in msg or "error" in msg:
            break

    f.write(
        json.dumps(
            {
                "execute": "human-monitor-command",
                "arguments": {"command-line": hmp},
            }
        ).encode()
        + b"\n"
    )
    while True:
        msg = recv_json()
        if msg is None:
            sys.exit("QMP: connection closed")
        if "error" in msg:
            sys.exit("QMP error: " + json.dumps(msg["error"]))
        if "return" in msg:
            out = msg["return"]
            if isinstance(out, str):
                sys.stdout.write(out)
            return
        # ignore async events


if __name__ == "__main__":
    main()
