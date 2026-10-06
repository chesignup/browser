#!/usr/bin/env bash
# Manage the SSH tunnel that exposes the guest CDP on host 127.0.0.1:CDP_HOST_PORT.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

action="${1:-up}"

case "${action}" in
  up)
    if tunnel_running; then
      # Refresh pidfile when a root-owned forwarder is already serving CDP.
      pgrep -f "ssh.*-L 127.0.0.1:${CDP_HOST_PORT}:127.0.0.1:${GUEST_CDP_PORT}" | head -1 > "${TUNNEL_PID}" || true
      log "Tunnel already up (pid $(cat "${TUNNEL_PID}" 2>/dev/null || echo unknown)): 127.0.0.1:${CDP_HOST_PORT} -> guest:${GUEST_CDP_PORT}"
      exit 0
    fi
    qemu_running || die "VM is not running. Run: ./qbrowser start"
    # Stale bind without a detectable ssh: try reclaiming the port.
    if ss -ltn 2>/dev/null | grep -q ":${CDP_HOST_PORT} "; then
      warn "port ${CDP_HOST_PORT} busy — attempting reclaim"
      pkill -f "ssh.*-L 127.0.0.1:${CDP_HOST_PORT}:127.0.0.1:${GUEST_CDP_PORT}" 2>/dev/null || true
      sleep 0.5
      if curl -fsS -m 2 "http://127.0.0.1:${CDP_HOST_PORT}/json/version" >/dev/null 2>&1; then
        pgrep -f "ssh.*-L 127.0.0.1:${CDP_HOST_PORT}:127.0.0.1:${GUEST_CDP_PORT}" | head -1 > "${TUNNEL_PID}" || true
        log "Tunnel already serving CDP on ${CDP_HOST_PORT}"
        exit 0
      fi
    fi
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
