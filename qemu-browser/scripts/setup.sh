#!/usr/bin/env bash
# One-time setup: download base image, build overlay disk, keys, seed ISO.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

command -v qemu-img >/dev/null || die "qemu-img not found"
command -v qemu-system-x86_64 >/dev/null || die "qemu-system-x86_64 not found"

# 1) Base cloud image
if [[ ! -f "${BASE_IMG}" ]]; then
  log "Downloading base cloud image..."
  curl -fSL --progress-bar -o "${BASE_IMG}.part" "${IMG_URL}"
  mv "${BASE_IMG}.part" "${BASE_IMG}"
else
  log "Base image already present: ${BASE_IMG}"
fi

# 2) Overlay disk backed by base, grown to VM_DISK_SIZE
if [[ ! -f "${DISK}" ]]; then
  log "Creating overlay disk (${VM_DISK_SIZE})..."
  qemu-img create -f qcow2 -F qcow2 -b "${BASE_IMG}" "${DISK}" "${VM_DISK_SIZE}" >/dev/null
else
  log "Disk already present: ${DISK}"
fi

# 3) SSH keypair for guest management
if [[ ! -f "${SSH_KEY}" ]]; then
  log "Generating SSH keypair..."
  ssh-keygen -t ed25519 -N "" -f "${SSH_KEY}" -C "qemu-browser" >/dev/null
fi
SSH_PUBKEY="$(cat "${SSH_KEY}.pub")"

# 4) VNC password (arg > env > existing file > prompt)
VNC_PASS="${1:-${VNC_PASS:-}}"
if [[ -z "${VNC_PASS}" && -f "${VNC_PASS_FILE}" ]]; then
  VNC_PASS="$(cat "${VNC_PASS_FILE}")"
  log "Reusing existing VNC password from ${VNC_PASS_FILE}"
fi
if [[ -z "${VNC_PASS}" ]]; then
  read -rsp "Set a VNC password for the noVNC viewer: " VNC_PASS; echo
  [[ -n "${VNC_PASS}" ]] || die "VNC password cannot be empty"
fi
umask 077; printf '%s' "${VNC_PASS}" > "${VNC_PASS_FILE}"

# 5) Render user-data and build seed ISO
log "Rendering cloud-init user-data..."
export VM_USER SCREEN_W SCREEN_H GUEST_CDP_PORT USER_AGENT SSH_PUBKEY VNC_PASS
RENDERED_UD="${VAR_DIR}/user-data"
"${PYTHON_BIN}" "${QB_ROOT}/scripts/render.py" "${QB_ROOT}/cloud-init/user-data.tmpl" "${RENDERED_UD}" >/dev/null

log "Building cloud-init seed ISO..."
"${PYTHON_BIN}" "${QB_ROOT}/scripts/make-seed.py" "${RENDERED_UD}" "${QB_ROOT}/cloud-init/meta-data" "${SEED_ISO}" >/dev/null

log "Setup complete."
log "  disk:     ${DISK}"
log "  seed:     ${SEED_ISO}"
log "  ssh key:  ${SSH_KEY}"
log "Next: ./qbrowser start"
