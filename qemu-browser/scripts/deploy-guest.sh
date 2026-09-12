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
  log "Deploying CDP bridge & remote browser viewer to guest..."
  ssh_guest "dpkg -s python3-aiohttp >/dev/null 2>&1 || sudo apt-get install -y python3-aiohttp >/dev/null 2>&1 || true"

  # Ensure Chrome uses internal CDP port (9221)
  ssh_guest "if grep -q 'remote-debugging-port=${GUEST_CDP_PORT}' /etc/systemd/system/chrome.service 2>/dev/null; then \
    sudo sed -i 's/remote-debugging-port=${GUEST_CDP_PORT}/remote-debugging-port=${CHROME_INTERNAL_PORT}/' /etc/systemd/system/chrome.service \
    && sudo systemctl daemon-reload \
    && sudo systemctl restart chrome; \
  fi"

  "${SCP[@]}" "${QB_ROOT}/guest/screencast/server.py" "${VM_USER}@127.0.0.1:/tmp/server.py"
  "${SCP[@]}" "${QB_ROOT}/guest/screencast/index.html" "${VM_USER}@127.0.0.1:/tmp/index.html"
  "${SCP[@]}" "${QB_ROOT}/guest/screencast/screencast.service" "${VM_USER}@127.0.0.1:/tmp/screencast.service"
  ssh_guest "sudo mkdir -p /opt/screencast \
    && sudo mv /tmp/server.py /tmp/index.html /opt/screencast/ \
    && sudo mv /tmp/screencast.service /etc/systemd/system/screencast.service \
    && sudo sed -i 's/CHROME_INTERNAL_CDP=9221/CHROME_INTERNAL_CDP=${CHROME_INTERNAL_PORT}/' /etc/systemd/system/screencast.service \
    && sudo sed -i 's/CDP_LISTEN_PORT=9222/CDP_LISTEN_PORT=${GUEST_CDP_PORT}/' /etc/systemd/system/screencast.service \
    && sudo sed -i 's/VIEWER_LISTEN_PORT=6081/VIEWER_LISTEN_PORT=${VIEWER_PORT}/' /etc/systemd/system/screencast.service \
    && sudo systemctl daemon-reload \
    && sudo systemctl enable --now screencast \
    && sudo systemctl restart screencast"
  log "CDP bridge & remote browser viewer deployed (guest :${GUEST_CDP_PORT} & :${VIEWER_PORT})."
fi
