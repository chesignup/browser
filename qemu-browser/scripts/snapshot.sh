#!/usr/bin/env bash
# Manage a single live VM snapshot (RAM + disk) named "clean".
#   save   - (re)create the snapshot from the current running state
#   revert - restore the VM to the snapshot instantly
#   status - show stored snapshots
set -euo pipefail
source "$(dirname "$0")/lib.sh"

SNAP_NAME="clean"

qmp() { "${PYTHON_BIN}" "${QB_ROOT}/scripts/qmp.py" "${QMP_SOCK}" "$@"; }

qemu_running || die "VM not running. Run: ./qbrowser start"
[[ -S "${QMP_SOCK}" ]] || die "QMP socket missing. Restart the VM: ./qbrowser restart"

action="${1:-status}"

case "${action}" in
  save)
    log "Saving snapshot '${SNAP_NAME}' (RAM + disk)... this pauses the VM briefly."
    # Keep only one: delete any existing snapshot of that name first.
    qmp "delvm ${SNAP_NAME}" >/dev/null 2>&1 || true
    out="$(qmp "savevm ${SNAP_NAME}")"
    [[ -n "${out}" ]] && printf '%s\n' "${out}"
    log "Snapshot '${SNAP_NAME}' saved."
    "${QB_ROOT}/scripts/snapshot.sh" status
    ;;
  revert|load|restore)
    log "Reverting VM to snapshot '${SNAP_NAME}'..."
    out="$(qmp "loadvm ${SNAP_NAME}")"
    [[ -n "${out}" ]] && printf '%s\n' "${out}"
    # Live TCP sessions (SSH/CDP tunnel) are broken by the RAM restore; rebuild.
    "${QB_ROOT}/scripts/tunnel.sh" down >/dev/null 2>&1 || true
    sleep 1
    "${QB_ROOT}/scripts/tunnel.sh" up >/dev/null 2>&1 || warn "Re-open the CDP tunnel manually: ./qbrowser tunnel up"
    log "Reverted to '${SNAP_NAME}'."
    ;;
  status|list|info)
    echo "== stored snapshots =="
    qmp "info snapshots" || true
    ;;
  delete|del|rm)
    qmp "delvm ${SNAP_NAME}" >/dev/null 2>&1 || true
    log "Snapshot '${SNAP_NAME}' deleted."
    ;;
  *)
    die "Usage: snapshot.sh {save|revert|status|delete}"
    ;;
esac
