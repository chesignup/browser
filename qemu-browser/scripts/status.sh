#!/usr/bin/env bash
# Show status of VM, SSH, guest services, tunnel, and CDP.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

echo "== qemu-browser status =="
if qemu_running; then
  echo "VM:        running (pid $(cat "${QEMU_PID}"))"
else
  echo "VM:        stopped"
fi

if qemu_running; then
  if ssh_guest true >/dev/null 2>&1; then
    echo "SSH:       reachable (127.0.0.1:${SSH_PORT})"
    services="$(ssh_guest "systemctl is-active xvfb openbox chrome x11vnc novnc 2>/dev/null | paste -sd' '" 2>/dev/null || true)"
    echo "Services:  ${services:-unknown} (xvfb openbox chrome x11vnc novnc)"
    cloudinit="$(ssh_guest "cloud-init status 2>/dev/null | tr -d '\n'" 2>/dev/null || true)"
    echo "Cloud-init:${cloudinit:- unknown}"
  else
    echo "SSH:       not reachable yet (guest may still be booting/provisioning)"
  fi
fi

if tunnel_running; then
  echo "CDP tunnel: up (127.0.0.1:${CDP_HOST_PORT} -> guest:${GUEST_CDP_PORT})"
  if curl -fsS "http://127.0.0.1:${CDP_HOST_PORT}/json/version" >/dev/null 2>&1; then
    echo "CDP:       alive"
  else
    echo "CDP:       tunnel up but Chrome not answering yet"
  fi
else
  echo "CDP tunnel: down"
fi

echo "noVNC:     http://$(lan_ip):${NOVNC_PORT}/vnc.html  (bind: ${LAN_BIND})"
echo "viewer:    http://$(lan_ip):${VIEWER_PORT}/  (mobile-friendly)"
