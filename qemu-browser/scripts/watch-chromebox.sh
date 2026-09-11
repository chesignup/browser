#!/usr/bin/env bash
# Keep chromebox ALWAYS up: start QEMU if it died, QMP-reset a hung guest,
# restart Chrome if CDP is dead, restore SSH tunnels.
# SSH probes are hard-timeout'd so a wedged guest cannot stall this loop.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

WATCH_PID="${VAR_DIR}/watch-chromebox.pid"
WATCH_LOG="${VAR_DIR}/watch-chromebox.log"
WATCH_DISABLE="${VAR_DIR}/watch.disable"
INTERVAL="${WATCH_INTERVAL:-15}"
SSH_FAILS_BEFORE_RESET="${SSH_FAILS_BEFORE_RESET:-2}"
RESET_FAILS_BEFORE_REBOOT="${RESET_FAILS_BEFORE_REBOOT:-2}"
CDP_FAILS_BEFORE_RESTART="${CDP_FAILS_BEFORE_RESTART:-2}"

STATE_SSH=0
STATE_RESET=0
STATE_CDP=0

cdp_ok() { curl -fsS -m 3 "http://127.0.0.1:${CDP_HOST_PORT}/json/version" >/dev/null 2>&1; }
guest_ssh_ok() { ssh_guest true >/dev/null 2>&1; }
guest_cdp_ok() { ssh_guest "curl -fsS -m 3 http://127.0.0.1:${GUEST_CDP_PORT}/json/version" >/dev/null 2>&1; }
guest_dns_ok() { ssh_guest "curl -fsS -m 4 -o /dev/null https://www.yad2.co.il" >/dev/null 2>&1; }

ensure_tunnels() {
  "${QB_ROOT}/scripts/tunnel.sh" up >/dev/null 2>&1 || true
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx cursor-agent; then
    timeout 15 docker exec cursor-agent bash -lc 'gbrowser tunnel up' >/dev/null 2>&1 || true
  fi
}

restore_guest_dns() {
  log "restoring guest public DNS (disable Tailscale MagicDNS)"
  ssh_guest "sudo tailscale set --accept-dns=false >/dev/null 2>&1 || true" || true
  ssh_guest "sudo ln -sfn /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf" || true
  ssh_guest "sudo systemctl restart systemd-resolved >/dev/null 2>&1 || true" || true
  guest_dns_ok || ssh_guest "printf 'nameserver 8.8.8.8\nnameserver 1.1.1.1\n' | sudo tee /etc/resolv.conf >/dev/null" || true
}

start_qemu() {
  log "starting QEMU chromebox"
  "${QB_ROOT}/scripts/run.sh" || true
  for _ in $(seq 1 60); do
    guest_ssh_ok && break
    sleep 2
  done
  if guest_ssh_ok; then
    restore_guest_dns
    ensure_tunnels
    for _ in $(seq 1 30); do
      guest_cdp_ok && break
      sleep 2
    done
    log "QEMU up (ssh$(guest_cdp_ok && echo +cdp))"
  else
    warn "QEMU started but SSH still down"
  fi
}

kill_qemu() {
  log "killing QEMU pidfile=$(cat "${QEMU_PID}" 2>/dev/null || echo none)"
  "${QB_ROOT}/scripts/tunnel.sh" down >/dev/null 2>&1 || true
  if qemu_running; then
    kill "$(cat "${QEMU_PID}")" 2>/dev/null || true
    sleep 2
    qemu_running && kill -9 "$(cat "${QEMU_PID}")" 2>/dev/null || true
  fi
  rm -f "${QEMU_PID}"
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
  log "guest hung — QMP system_reset"
  timeout 15 "${PYTHON_BIN}" "${QB_ROOT}/scripts/qmp.py" "${QMP_SOCK}" "system_reset" >/dev/null 2>&1 || true
  STATE_SSH=0
  STATE_CDP=0
  for _ in $(seq 1 40); do
    guest_ssh_ok && break
    sleep 3
  done
  if ! guest_ssh_ok; then
    warn "SSH still down after QMP reset"
    return 1
  fi
  restore_guest_dns
  for _ in $(seq 1 25); do
    guest_cdp_ok && break
    sleep 2
  done
  ensure_tunnels
  log "guest back after reset"
  return 0
}

tick() {
  if [[ -f "${WATCH_DISABLE}" ]]; then
    return 0
  fi
  if ! qemu_running; then
    warn "qemu not running — bringing chromebox up"
    start_qemu
    STATE_SSH=0
    STATE_RESET=0
    return 0
  fi

  if guest_ssh_ok; then
    STATE_SSH=0
    STATE_RESET=0
  else
    STATE_SSH=$((STATE_SSH + 1))
    warn "guest SSH fail ${STATE_SSH}/${SSH_FAILS_BEFORE_RESET}"
    if [[ "${STATE_SSH}" -ge "${SSH_FAILS_BEFORE_RESET}" ]]; then
      if reset_guest; then
        STATE_RESET=0
      else
        STATE_RESET=$((STATE_RESET + 1))
        if [[ "${STATE_RESET}" -ge "${RESET_FAILS_BEFORE_REBOOT}" ]]; then
          log "QMP reset did not recover — hard restart QEMU"
          kill_qemu
          start_qemu
          STATE_RESET=0
          STATE_SSH=0
        fi
      fi
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
      if ! guest_cdp_ok; then
        warn "chrome still dead — QMP reset"
        reset_guest || { kill_qemu; start_qemu; }
      fi
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
  log "chromebox watch interval=${INTERVAL}s (start qemu / qmp reset / chrome restart)"
  while true; do
    tick || true
    sleep "${INTERVAL}"
  done
}

install_systemd() {
  local unit_dir="${HOME}/.config/systemd/user"
  mkdir -p "${unit_dir}"
  cat >"${unit_dir}/chromebox-watch.service" <<EOF
[Unit]
Description=Keep QEMU chromebox (Chrome CDP) always up
After=default.target

[Service]
Type=simple
ExecStart=${QB_ROOT}/scripts/watch-chromebox.sh loop
Restart=always
RestartSec=5
KillMode=mixed

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user enable --now chromebox-watch.service 2>/dev/null || true
  loginctl enable-linger "${USER}" >/dev/null 2>&1 || true
}

cmd="${1:-up}"
case "${cmd}" in
  loop) loop ;;
  up|start)
    mkdir -p "${VAR_DIR}"
    rm -f "${WATCH_DISABLE}"
    if systemctl --user start chromebox-watch.service 2>/dev/null; then
      install_systemd
      log "watch via systemd --user chromebox-watch.service"
      systemctl --user is-active chromebox-watch.service || true
      exit 0
    fi
    if [[ -f "${WATCH_PID}" ]] && kill -0 "$(cat "${WATCH_PID}")" 2>/dev/null; then
      log "already running pid $(cat "${WATCH_PID}")"
      exit 0
    fi
    nohup "$0" loop >>"${WATCH_LOG}" 2>&1 &
    echo $! >"${WATCH_PID}"
    log "watch started pid $(cat "${WATCH_PID}") log ${WATCH_LOG}"
    ;;
  install)
    install_systemd
    log "enabled systemd --user chromebox-watch.service (linger on)"
    ;;
  down|stop)
    touch "${WATCH_DISABLE}"
    systemctl --user stop chromebox-watch.service 2>/dev/null || true
    if [[ -f "${WATCH_PID}" ]]; then
      kill "$(cat "${WATCH_PID}")" 2>/dev/null || true
      rm -f "${WATCH_PID}"
    fi
    pkill -f 'watch-chromebox.sh loop' 2>/dev/null || true
    log "watch stopped (will not auto-start qemu until: qbrowser watch up)"
    ;;
  status)
    if systemctl --user is-active chromebox-watch.service >/dev/null 2>&1; then
      echo "up systemd"
    elif [[ -f "${WATCH_PID}" ]] && kill -0 "$(cat "${WATCH_PID}")" 2>/dev/null; then
      echo "up pid $(cat "${WATCH_PID}")"
    else
      echo "down"
    fi
    ;;
  tick) tick ;;
  *) echo "Usage: watch-chromebox.sh {up|down|status|tick|install}" >&2; exit 1 ;;
esac
