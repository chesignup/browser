#!/usr/bin/env bash
set -e

mkdir -p /var/run/tailscale /var/lib/tailscale /root/.ssh /var/run/sshd

# Install the guest SSH key (mounted read-only) with correct perms.
if [[ -f /guest_key.ro ]]; then
  cp /guest_key.ro /root/.ssh/guest_key
  chmod 600 /root/.ssh/guest_key
fi

# SSH access to THIS container: authorized key (if provided) and/or root password.
if [[ -n "${AUTHORIZED_KEYS:-}" ]]; then
  printf '%s\n' "${AUTHORIZED_KEYS}" > /root/.ssh/authorized_keys
  chmod 600 /root/.ssh/authorized_keys
fi
echo "root:${ROOT_PASSWORD:-agent}" | chpasswd

# Start tailscaled (real TUN; needs NET_ADMIN + /dev/net/tun from compose).
tailscaled \
  --state=/var/lib/tailscale/tailscaled.state \
  --socket=/var/run/tailscale/tailscaled.sock \
  --tun="${TS_TUN:-tailscale0}" \
  >/var/log/tailscaled.log 2>&1 &

# SSH server (ForceCommand attaches the tmux 'agent' session).
/usr/sbin/sshd

# Approve the human-browser MCP server for the CLI (idempotent, best-effort).
export PATH=/root/.local/bin:$PATH
cursor-agent mcp enable human-browser >/dev/null 2>&1 || true

# Pre-create the agent tmux session so SSH logins attach immediately.
tmux has-session -t agent 2>/dev/null || \
  tmux new-session -d -s agent -n agent "/usr/local/bin/agent-run"

echo "[entrypoint] container ready."
echo "[entrypoint]   SSH (LAN):      ssh -p 2223 root@<host-ip>      (password: ${ROOT_PASSWORD:-agent})"
echo "[entrypoint]   Tailscale:      run 'tailscale up' inside, then reach it by its tailnet IP"
echo "[entrypoint]   Guest host:     ${GUEST_HOST:-100.92.122.70}"

exec tail -f /dev/null
