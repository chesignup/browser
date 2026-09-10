#!/usr/bin/env bash
# Keep chromebox reachable: SSH + Chrome CDP + host/agent tunnels.
# Recovers guest kernel hangs (RCU stall / Chrome bad-page): restart Chrome
# if SSH works; QMP system_reset only after several consecutive SSH failures.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

WATCH_PID="${VAR_DIR}/watch-chromebox.pid"
WATCH_LOG="${VAR_DIR}/watch-chromebox.log"
INTERVAL="${WATCH_INTERVAL:-20}"
SSH_FAILS_BEFORE_RESET="${SSH_FAILS_BEFORE_RESET:-3}"
CDP_FAILS_BEFORE_RESTART="${CDP_FAILS_BEFORE_RESTART:-2}"

STATE_SSH=0
STATE_CDP=0

cdp_ok() { curl -fsS -m 4 "http://127.0.0.1:${CDP_HOST_PORT}/json/version" >/dev/null 2>&1; }
# ssh_guest is a bash function — do not wrap it in `timeout` (timeout only execs binaries).
guest_ssh_ok() { ssh_guest true >/dev/null 2>&1; }
guest_cdp_ok() { ssh_guest "curl -fsS -m 3 http://127.0.0.1:${GUEST_CDP_PORT}/json/version" >/dev/null 2>&1; }

guest_dns_ok() { ssh_guest "getent ahostsv4 www.yad2.co.il >/dev/null" >/dev/null 2>&1; }

restore_guest_dns() {
  log "guest DNS down — disabling Tailscale MagicDNS, using systemd-resolved"
  ssh_guest "sudo tailscale set --accept-dns=false >/dev/null 2>&1 || true"
  ssh_guest "sudo ln -sfn /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf"
  ssh_guest "grep -q 'nameserver 8.8.8.8' /etc/systemd/resolved.conf.d/99-qbrowser.conf 2>/dev/null || true"
  ssh_guest "sudo systemctl restart systemd-resolved >/dev/null 2>&1 || true"
  guest_dns_ok || ssh_guest "printf 'nameserver 8.8.8.8\nnameserver 1.1.1.1\n' | sudo tee /etc/resolv.conf >/dev/null"
}

ensure_tunnels() {
  "${QB_ROOT}/scripts/tunnel.sh" up >/dev/null 2>&1 || true
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx cursor-agent; then
    docker exec cursor-agent bash -lc 'gbrowser tunnel up' >/dev/null 2>&1 || true
  fi
}

restart_chrome() {
  log "restarting guest chrome.service"
  ssh_guest "sudo systemctl restart chrome" || true
  for _ in $(seq 1 20); do
    guest_cdp_ok && return 0
    sleep 2
  done
  return 1
}

reset_guest() {
  log "guest hung — QMP system_reset (SSH failed ${SSH_FAILS_BEFORE_RESET} times)"
  "${PYTHON_BIN}" "${QB_ROOT}/scripts/qmp.py" "${QMP_SOCK}" "system_reset" >/dev/null || true
  STATE_SSH=0
  STATE_CDP=0
  for _ in $(seq 1 40); do
    guest_ssh_ok && break
    sleep 3
  done
  guest_ssh_ok || { warn "SSH still down after reset"; return 1; }
  restore_guest_dns || true
  for _ in $(seq 1 25); do
    guest_cdp_ok && break
    sleep 2
  done
  ensure_tunnels
  log "guest back (ssh+cdp)"
}

tick() {
  qemu_running || { warn "qemu not running"; return 0; }
  if guest_ssh_ok; then
    STATE_SSH=0
  else
    STATE_SSH=$((STATE_SSH + 1))
    warn "guest SSH fail ${STATE_SSH}/${SSH_FAILS_BEFORE_RESET}"
    if [[ "${STATE_SSH}" -ge "${SSH_FAILS_BEFORE_RESET}" ]]; then
      reset_guest
      return 0
    fi
    return 0
  fi

  guest_dns_ok || restore_guest_dns

  if guest_cdp_ok; then
    STATE_CDP=0
  else
    STATE_CDP=$((STATE_CDP + 1))
    warn "guest CDP fail ${STATE_CDP}/${CDP_FAILS_BEFORE_RESTART}"
    if [[ "${STATE_CDP}" -ge "${CDP_FAILS_BEFORE_RESTART}" ]]; then
      restart_chrome || true
      STATE_CDP=0
    fi
  fi

  if ! cdp_ok; then
    log "host CDP tunnel down — reconnecting"
    "${QB_ROOT}/scripts/tunnel.sh" down >/dev/null 2>&1 || true
    "${QB_ROOT}/scripts/tunnel.sh" up >/dev/null 2>&1 || true
  fi
  ensure_tunnels
}

loop() {
  mkdir -p "${VAR_DIR}"
  log "chromebox watch interval=${INTERVAL}s ssh_fails=${SSH_FAILS_BEFORE_RESET} cdp_fails=${CDP_FAILS_BEFORE_RESTART}"
  while true; do
    tick || true
    sleep "${INTERVAL}"
  done
}

cmd="${1:-up}"
case "${cmd}" in
  loop) loop ;;
  up|start)
    mkdir -p "${VAR_DIR}"
    if [[ -f "${WATCH_PID}" ]] && kill -0 "$(cat "${WATCH_PID}")" 2>/dev/null; then
      log "already running pid $(cat "${WATCH_PID}")"
      exit 0
    fi
    nohup "$0" loop >>"${WATCH_LOG}" 2>&1 &
    echo $! >"${WATCH_PID}"
    log "watch started pid $(cat "${WATCH_PID}") log ${WATCH_LOG}"
    ;;
  down|stop)
    if [[ -f "${WATCH_PID}" ]]; then
      kill "$(cat "${WATCH_PID}")" 2>/dev/null || true
      rm -f "${WATCH_PID}"
    fi
    log "watch stopped"
    ;;
  status)
    if [[ -f "${WATCH_PID}" ]] && kill -0 "$(cat "${WATCH_PID}")" 2>/dev/null; then
      echo "up pid $(cat "${WATCH_PID}")"
    else
      echo "down"
    fi
    ;;
  tick) tick ;;
  *) echo "Usage: watch-chromebox.sh {up|down|status|tick}" >&2; exit 1 ;;
esac
