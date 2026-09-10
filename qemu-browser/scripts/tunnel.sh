#!/usr/bin/env bash
# Manage the SSH tunnel that exposes the guest CDP on host 127.0.0.1:CDP_HOST_PORT.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

action="${1:-up}"

case "${action}" in
  up)
    if tunnel_running; then
      log "Tunnel already up (pid $(cat "${TUNNEL_PID}")): 127.0.0.1:${CDP_HOST_PORT} -> guest:${GUEST_CDP_PORT}"
      exit 0
    fi
    qemu_running || die "VM is not running. Run: ./qbrowser start"
    log "Opening CDP tunnel 127.0.0.1:${CDP_HOST_PORT} -> guest 127.0.0.1:${GUEST_CDP_PORT} ..."
    ssh -i "${SSH_KEY}" \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o LogLevel=ERROR \
      -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=15 \
      -N -f \
      -L "127.0.0.1:${CDP_HOST_PORT}:127.0.0.1:${GUEST_CDP_PORT}" \
      -p "${SSH_PORT}" "${VM_USER}@127.0.0.1"
    # -f backgrounds ssh; capture its pid
    pgrep -f "ssh.*-L 127.0.0.1:${CDP_HOST_PORT}:127.0.0.1:${GUEST_CDP_PORT}" | tail -1 > "${TUNNEL_PID}" || true
    log "Tunnel established."
    ;;
  down)
    if tunnel_running; then
      kill "$(cat "${TUNNEL_PID}")" 2>/dev/null || true
    fi
    pkill -f "ssh.*-L 127.0.0.1:${CDP_HOST_PORT}:127.0.0.1:${GUEST_CDP_PORT}" 2>/dev/null || true
    rm -f "${TUNNEL_PID}"
    log "Tunnel closed."
    ;;
  status)
    if tunnel_running; then echo "up"; else echo "down"; fi
    ;;
  *)
    die "Usage: tunnel.sh {up|down|status}"
    ;;
esac
