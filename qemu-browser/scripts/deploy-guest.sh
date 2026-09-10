#!/usr/bin/env bash
# Idempotently deploy in-guest services (currently: the mobile screencast viewer).
# Safe to run repeatedly; used by 'qbrowser start' so rebuilt guests get it too.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

qemu_running || die "VM not running."
ssh_guest true >/dev/null 2>&1 || die "guest SSH not reachable."

SCP=(scp -i "${SSH_KEY}" -P "${SSH_PORT}" -o StrictHostKeyChecking=no \
     -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)

need_deploy=1
if ssh_guest "systemctl is-active screencast >/dev/null 2>&1 && test -f /opt/screencast/server.py"; then
  # Redeploy only if local files are newer is overkill; just refresh files each start.
  need_deploy=1
fi

if [[ "${need_deploy}" == "1" ]]; then
  log "Deploying screencast viewer to guest..."
  ssh_guest "dpkg -s python3-aiohttp >/dev/null 2>&1 || sudo apt-get install -y python3-aiohttp >/dev/null 2>&1 || true"
  "${SCP[@]}" "${QB_ROOT}/guest/screencast/server.py" "${VM_USER}@127.0.0.1:/tmp/server.py"
  "${SCP[@]}" "${QB_ROOT}/guest/screencast/index.html" "${VM_USER}@127.0.0.1:/tmp/index.html"
  "${SCP[@]}" "${QB_ROOT}/guest/screencast/screencast.service" "${VM_USER}@127.0.0.1:/tmp/screencast.service"
  ssh_guest "sudo mkdir -p /opt/screencast \
    && sudo mv /tmp/server.py /tmp/index.html /opt/screencast/ \
    && sudo mv /tmp/screencast.service /etc/systemd/system/screencast.service \
    && sudo sed -i 's/SCREENCAST_PORT=6081/SCREENCAST_PORT=${VIEWER_PORT}/' /etc/systemd/system/screencast.service \
    && sudo systemctl daemon-reload \
    && sudo systemctl enable --now screencast \
    && sudo systemctl restart screencast"
  log "Screencast viewer deployed (guest :${VIEWER_PORT})."
fi
