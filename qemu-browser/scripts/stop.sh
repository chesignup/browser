#!/usr/bin/env bash
# Stop the CDP tunnel and shut the VM down.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

"${QB_ROOT}/scripts/tunnel.sh" down || true

if qemu_running; then
  pid="$(cat "${QEMU_PID}")"
  log "Attempting graceful guest shutdown..."
  ssh_guest "sudo poweroff" >/dev/null 2>&1 || true
  for _ in $(seq 1 20); do
    qemu_running || break
    sleep 1
  done
  if qemu_running; then
    warn "Graceful shutdown timed out; terminating qemu (pid ${pid})."
    kill "${pid}" 2>/dev/null || true
    sleep 2
    kill -9 "${pid}" 2>/dev/null || true
  fi
  rm -f "${QEMU_PID}"
  log "VM stopped."
else
  log "VM not running."
fi
