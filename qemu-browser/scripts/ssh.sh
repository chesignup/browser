#!/usr/bin/env bash
# Open an interactive SSH shell (or run a command) in the guest.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
qemu_running || die "VM not running. Run: ./qbrowser start"
if [[ $# -eq 0 ]]; then
  exec ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o LogLevel=ERROR -p "${SSH_PORT}" "${VM_USER}@127.0.0.1"
else
  ssh_guest "$@"
fi
