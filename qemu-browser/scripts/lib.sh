#!/usr/bin/env bash
# Shared helpers for qemu-browser scripts.
set -euo pipefail

_here() { cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd; }
QB_ROOT="$(_here)"
# shellcheck disable=SC1091
source "${QB_ROOT}/config.env"

mkdir -p "${VAR_DIR}"

BASE_IMG="${VAR_DIR}/base.img"
DISK="${VAR_DIR}/disk.qcow2"
SEED_ISO="${VAR_DIR}/seed.iso"
QEMU_PID="${VAR_DIR}/qemu.pid"
QMP_SOCK="${VAR_DIR}/qmp.sock"
TUNNEL_PID="${VAR_DIR}/tunnel.pid"
SERIAL_LOG="${VAR_DIR}/serial.log"
SSH_KEY="${VAR_DIR}/id_ed25519"
VNC_PASS_FILE="${VAR_DIR}/vnc_pass"

log()  { printf '\033[1;34m[qbrowser]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[qbrowser]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[qbrowser]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

lan_ip() {
  ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1
}

qemu_running() {
  [[ -f "${QEMU_PID}" ]] && kill -0 "$(cat "${QEMU_PID}")" 2>/dev/null
}

tunnel_running() {
  [[ -f "${TUNNEL_PID}" ]] && kill -0 "$(cat "${TUNNEL_PID}")" 2>/dev/null
}

ssh_guest() {
  # Keep SSH from hanging forever when the guest is wedged (TCP up, no banner).
  timeout 8 ssh -i "${SSH_KEY}" \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o LogLevel=ERROR \
    -o BatchMode=yes \
    -o ConnectTimeout=4 \
    -o ConnectionAttempts=1 \
    -o ServerAliveInterval=2 \
    -o ServerAliveCountMax=2 \
    -p "${SSH_PORT}" "${VM_USER}@127.0.0.1" "$@"
}
