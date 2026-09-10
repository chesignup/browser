#!/usr/bin/env bash
set -e

mkdir -p /root/.ssh /var/run/tailscale /var/lib/tailscale

# Install guest SSH key (mounted read-only) for the CDP tunnel.
if [[ -f /guest_key.ro ]]; then
  cp /guest_key.ro /root/.ssh/guest_key
  chmod 600 /root/.ssh/guest_key
fi

# Tailscale daemon (real TUN; needs NET_ADMIN + /dev/net/tun from compose).
tailscaled \
  --state=/var/lib/tailscale/tailscaled.state \
  --socket=/var/run/tailscale/tailscaled.sock \
  --tun="${TS_TUN:-tailscale0}" \
  >/var/log/tailscaled.log 2>&1 &

# MCP server (Streamable HTTP at /mcp).
python /app/server.py >/var/log/mcp.log 2>&1 &

sleep 2
echo "[entrypoint] MCP server starting on :${MCP_PORT:-8000} (path /mcp)."
echo "[entrypoint] Next steps (one-time):"
echo "  1) docker exec -it mcp-human-browser tailscale up      # approve the node"
echo "  2) docker exec -it mcp-human-browser mcp-expose        # public HTTPS via Funnel"
echo "  3) In ChatGPT (Developer mode) add the printed https://<host>.ts.net/mcp URL"
echo "[entrypoint] Bearer token (also in /run/mcp_token):"
grep -m1 'Bearer token' /var/log/mcp.log || true

exec tail -f /dev/null
