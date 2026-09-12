#!/usr/bin/env bash
# Launch the VM (daemonized) with user-mode networking + host port forwards.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

[[ -f "${DISK}" ]] || die "Disk not found. Run: ./qbrowser setup"
[[ -f "${SEED_ISO}" ]] || die "Seed ISO not found. Run: ./qbrowser setup"

if qemu_running; then
  warn "VM already running (pid $(cat "${QEMU_PID}"))."
  exit 0
fi

ACCEL="tcg"
if [[ -w /dev/kvm ]] || id -nG | tr ' ' '\n' | grep -qx kvm; then
  ACCEL="kvm"
fi
log "Accel: ${ACCEL}"

# hostfwd:
#   SSH  -> host 127.0.0.1:SSH_PORT  -> guest :22   (management + CDP tunnel)
#   noVNC-> host LAN_BIND:NOVNC_PORT -> guest :6080  (view + interact from LAN)
#   CDP  -> host LAN_BIND:GUEST_CDP_PORT -> guest :9222 (web tab viewer + CDP)
HOSTFWD="hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22"
HOSTFWD+=",hostfwd=tcp:${LAN_BIND}:${NOVNC_PORT}-:6080"
HOSTFWD+=",hostfwd=tcp:${LAN_BIND}:${VIEWER_PORT}-:${VIEWER_PORT}"
HOSTFWD+=",hostfwd=tcp:${LAN_BIND}:${GUEST_CDP_PORT}-:${GUEST_CDP_PORT}"

log "Starting VM '${VM_NAME}' (${VM_CPUS} vCPU, ${VM_RAM_MB} MB)..."
qemu-system-x86_64 \
  -name "${VM_NAME}" \
  -machine q35,accel="${ACCEL}" \
  -cpu host \
  -smp "${VM_CPUS}" \
  -m "${VM_RAM_MB}" \
  -drive file="${DISK}",if=virtio,format=qcow2 \
  -drive file="${SEED_ISO}",if=virtio,format=raw,media=cdrom \
  -netdev user,id=net0,"${HOSTFWD}" \
  -device virtio-net-pci,netdev=net0 \
  -display none \
  -serial "file:${SERIAL_LOG}" \
  -qmp "unix:${QMP_SOCK},server=on,wait=off" \
  -pidfile "${QEMU_PID}" \
  -daemonize

sleep 1
qemu_running || die "VM failed to start. Check ${SERIAL_LOG}"
log "VM started (pid $(cat "${QEMU_PID}"))."
log "Serial log: ${SERIAL_LOG}"
log "First boot provisions the guest (installs Chrome, etc.) — this can take a few minutes."
log "noVNC will be at: http://$(lan_ip):${NOVNC_PORT}/vnc.html"
