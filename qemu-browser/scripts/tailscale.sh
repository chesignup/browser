#!/usr/bin/env bash
# Manage Tailscale inside the guest. Runs 'tailscale up' and surfaces the login
# URL and final status so you can reach the VM from outside the LAN.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

qemu_running || die "VM not running. Run: ./qbrowser start"

action="${1:-up}"; shift || true

ensure_installed() {
  ssh_guest "command -v tailscale >/dev/null 2>&1" \
    || die "tailscale not installed yet (guest may still be provisioning). Try: ./qbrowser status"
}

case "${action}" in
  up)
    ensure_installed
    log "Running 'sudo tailscale up ${*}' in the guest..."
    # Start tailscale up detached so the blocking auth wait doesn't hang us,
    # then read the login URL it prints.
    # MagicDNS overwrites /etc/resolv.conf and then fails in this QEMU guest,
    # which makes Chrome show chromewebdata for every public site (incl. yad2).
    ssh_guest "sudo rm -f /tmp/tsup.log; sudo bash -c 'nohup tailscale up --accept-dns=false ${*} >/tmp/tsup.log 2>&1 &'" || true

    url=""
    for _ in $(seq 1 20); do
      url="$(ssh_guest "grep -Eo 'https://login\.tailscale\.com/[a-zA-Z0-9/]+' /tmp/tsup.log 2>/dev/null | head -1" 2>/dev/null || true)"
      [[ -n "${url}" ]] && break
      # Already authenticated? then it connects with no URL.
      if ssh_guest "tailscale status >/dev/null 2>&1"; then break; fi
      sleep 1
    done

    if [[ -n "${url}" ]]; then
      echo
      echo "=============================================================="
      echo " Tailscale login required. Open this URL to authenticate:"
      echo
      echo "   ${url}"
      echo
      echo " Waiting for you to complete login..."
      echo "=============================================================="
    fi

    # Poll until connected (or timeout).
    for _ in $(seq 1 60); do
      if ssh_guest "tailscale status >/dev/null 2>&1"; then break; fi
      sleep 2
    done
    echo
    log "tailscale up result:"
    ssh_guest "cat /tmp/tsup.log 2>/dev/null" || true
    echo
    log "tailscale status:"
    ssh_guest "tailscale status 2>&1" || true
    echo
    ip4="$(ssh_guest "tailscale ip -4 2>/dev/null" 2>/dev/null || true)"
    [[ -n "${ip4}" ]] && log "Tailscale IPv4: ${ip4}  (reach noVNC at http://${ip4}:6080/vnc.html)"
    ;;
  status)
    ensure_installed
    ssh_guest "tailscale status 2>&1" || true
    echo
    ssh_guest "echo -n 'Tailscale IPv4: '; tailscale ip -4 2>/dev/null" || true
    ;;
  down)
    ensure_installed
    ssh_guest "sudo tailscale down" && log "tailscale down."
    ;;
  *)
    # Pass any other tailscale subcommand straight through.
    ensure_installed
    ssh_guest "sudo tailscale ${action} ${*}"
    ;;
esac
