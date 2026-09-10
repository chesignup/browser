#!/usr/bin/env bash
# Bootstrap the full stack on a fresh Ubuntu 22.04/24.04 server.
# Installs: KVM/QEMU, Docker, firewall rules, human-browser, chromebox VM,
# mobile viewer, Cursor agent container, MCP container.
#
# Usage:
#   sudo ./deploy/bootstrap.sh
#   # optional:
#   VNC_PASS='your-vnc-pass' MCP_BEARER_TOKEN='your-token' ./deploy/bootstrap.sh
#
# After it finishes, complete interactive Tailscale logins (printed at the end).
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_USER="${SUDO_USER:-${INSTALL_USER:-ubuntu}}"
INSTALL_HOME="$(getent passwd "${INSTALL_USER}" | cut -d: -f6)"
BROWSER_ROOT="${BROWSER_ROOT:-${INSTALL_HOME}/browser}"
VNC_PASS="${VNC_PASS:-chromebox-lan}"
MCP_BEARER_TOKEN="${MCP_BEARER_TOKEN:-$(openssl rand -hex 24)}"
AGENT_MODEL="${AGENT_MODEL:-gpt-5.4-mini}"
ROOT_PASSWORD="${ROOT_PASSWORD:-agent}"

log() { printf '\n==> %s\n' "$*"; }

log "Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  qemu-system-x86 qemu-utils cpu-checker curl ca-certificates gnupg \
  python3 python3-pip python3-venv git ufw jq openssh-client \
  acl docker.io docker-compose-v2 2>/dev/null \
  || apt-get install -y --no-install-recommends \
       qemu-system-x86 qemu-utils cpu-checker curl ca-certificates \
       python3 python3-pip git ufw jq openssh-client acl docker.io

# Prefer docker compose plugin; fall back to standalone binary if missing.
if ! docker compose version >/dev/null 2>&1; then
  if ! command -v docker-compose >/dev/null 2>&1; then
    curl -fsSL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64" \
      -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
  fi
  compose() { docker-compose "$@"; }
else
  compose() { docker compose "$@"; }
fi

log "User groups (kvm, docker)"
usermod -aG kvm,docker "${INSTALL_USER}" || true
setfacl -m "u:${INSTALL_USER}:rw" /dev/kvm 2>/dev/null || true
systemctl enable --now docker

log "Firewall (LAN noVNC + mobile viewer + agent SSH)"
ufw allow OpenSSH || true
ufw allow from 10.0.0.0/8 to any port 6080 proto tcp || true
ufw allow from 10.0.0.0/8 to any port 6081 proto tcp || true
ufw allow from 172.16.0.0/12 to any port 6080 proto tcp || true
ufw allow from 172.16.0.0/12 to any port 6081 proto tcp || true
ufw allow from 192.168.0.0/16 to any port 6080 proto tcp || true
ufw allow from 192.168.0.0/16 to any port 6081 proto tcp || true
ufw allow 2223/tcp || true
ufw --force enable || true

log "Install repo at ${BROWSER_ROOT}"
if [[ "${REPO_ROOT}" != "${BROWSER_ROOT}" ]]; then
  mkdir -p "$(dirname "${BROWSER_ROOT}")"
  rsync -a --delete \
    --exclude '.git/' --exclude 'qemu-browser/var/' --exclude '__pycache__/' \
    "${REPO_ROOT}/" "${BROWSER_ROOT}/"
fi
chown -R "${INSTALL_USER}:${INSTALL_USER}" "${BROWSER_ROOT}"

log "Python deps (human_browser + seed ISO)"
sudo -u "${INSTALL_USER}" python3 -m pip install --user -q pycdlib websockets
sudo -u "${INSTALL_USER}" bash -lc "cd '${BROWSER_ROOT}' && python3 -m pip install --user -e ."

log "QEMU chromebox VM"
sudo -u "${INSTALL_USER}" bash -lc "
  set -e
  cd '${BROWSER_ROOT}/qemu-browser'
  chmod +x qbrowser scripts/*.sh scripts/*.py 2>/dev/null || true
  ./qbrowser setup '${VNC_PASS}'
  ./qbrowser start
  ./qbrowser snapshot save || true
"

GUEST_TS_IP="$(sudo -u "${INSTALL_USER}" bash -lc "cd '${BROWSER_ROOT}/qemu-browser' && ./qbrowser ssh 'tailscale ip -4 2>/dev/null' 2>/dev/null" | tr -d '\r' | head -1 || true)"
if [[ -z "${GUEST_TS_IP}" ]]; then
  GUEST_TS_IP="SET_AFTER_GUEST_TAILSCALE_UP"
  log "Guest Tailscale not up yet — set GUEST_HOST later"
fi

log "Wire container env (GUEST_HOST=${GUEST_TS_IP})"
sed -i "s|^\\(\\s*- GUEST_HOST=\\).*|\\1${GUEST_TS_IP}|" \
  "${BROWSER_ROOT}/agent-container/docker-compose.yml" \
  "${BROWSER_ROOT}/mcp-container/docker-compose.yml"
sed -i "s|^\\(\\s*- MCP_BEARER_TOKEN=\\).*|\\1${MCP_BEARER_TOKEN}|" \
  "${BROWSER_ROOT}/mcp-container/docker-compose.yml"
sed -i "s|^\\(\\s*- AGENT_MODEL=\\).*|\\1${AGENT_MODEL}|" \
  "${BROWSER_ROOT}/agent-container/docker-compose.yml"
sed -i "s|^\\(\\s*- ROOT_PASSWORD=\\).*|\\1${ROOT_PASSWORD}|" \
  "${BROWSER_ROOT}/agent-container/docker-compose.yml"

export BROWSER_ROOT
log "Build + start agent + MCP containers"
sudo -u "${INSTALL_USER}" bash -lc "
  set -e
  export BROWSER_ROOT='${BROWSER_ROOT}'
  cd '${BROWSER_ROOT}/agent-container'
  compose() { docker compose \"\$@\" 2>/dev/null || docker-compose \"\$@\"; }
  compose build
  compose up -d
  cd '${BROWSER_ROOT}/mcp-container'
  compose build
  compose up -d
"

HOST_IP="$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -1)"
cat <<EOF

========================================================================
Bootstrap complete.

Host paths
  Repo:          ${BROWSER_ROOT}
  VM control:    ${BROWSER_ROOT}/qemu-browser/qbrowser
  Agent compose: ${BROWSER_ROOT}/agent-container
  MCP compose:   ${BROWSER_ROOT}/mcp-container

LAN viewers (after guest is up)
  noVNC:   http://${HOST_IP}:6080/vnc.html   (VNC password: ${VNC_PASS})
  Mobile:  http://${HOST_IP}:6081/

Agent SSH (LAN)
  ssh -p 2223 root@${HOST_IP}     password: ${ROOT_PASSWORD}

MCP bearer token (ChatGPT plugin Token auth)
  ${MCP_BEARER_TOKEN}

Interactive follow-ups (required once)
  1) Guest Tailscale (if not already):
       cd ${BROWSER_ROOT}/qemu-browser && ./qbrowser tailscale up
  2) Agent Tailscale:
       docker exec -it cursor-agent tailscale up
  3) MCP Tailscale + public HTTPS:
       docker exec -it mcp-human-browser tailscale up
       docker exec -it mcp-human-browser mcp-expose
  4) Cursor login inside agent (if needed):
       ssh -p 2223 root@${HOST_IP}
       NO_OPEN_BROWSER=1 cursor-agent login

Re-login / new shell needed for kvm+docker group membership:
  newgrp docker   # or log out/in

Docs: ${BROWSER_ROOT}/DEPLOY.md
========================================================================
EOF
