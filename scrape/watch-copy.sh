#!/usr/bin/env bash
# Copy scrape dumps from cursor-agent as they grow (does not wait for 100%).
# Usage:
#   ./watch-copy.sh              # loop; recopy whenever progress changes
#   ./watch-copy.sh --once      # copy current dumps now
#   ./watch-copy.sh --interval 30
#   ./watch-copy.sh --until-done  # exit after both sale and rent finish
#   ./watch-copy.sh --pid-file /path.pid
set -euo pipefail

DEST="${YAD2_DEST:-$(cd "$(dirname "$0")" && pwd)}"
CONTAINER="${AGENT_CONTAINER:-cursor-agent}"
SALE_SRC="${SALE_SRC:-/root/work}"
RENT_SRC="${RENT_SRC:-/root/work/rent}"
INTERVAL="${INTERVAL:-20}"
ONCE=0
UNTIL_DONE=0
PID_FILE="${WATCH_COPY_PID:-${DEST}/watch-copy.pid}"
ON_COMPLETE="${YAD2_ON_COMPLETE:-${DEST}/research/run.py}"
complete_hook_ran=0

SALE_FILES=(
  master_listings.json listing_details.json listing_details.csv
  apartments_for_sale.md scrape_progress.json pending_tokens.json
  all_listings.json feed_by_token.json
  telaviv_all.json ramatgan_all.json givatayim_all.json
  petachtikva_all.json bneiarak_all.json kiriatono_all.json
)
RENT_FILES=(
  master_listings.json listing_details.json listing_details.csv
  apartments_for_rent.md scrape_progress.json
  telaviv_rent.json ramatgan_rent.json givatayim_rent.json
  petachtikva_rent.json bneiarak_rent.json kiriatono_rent.json
)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --once) ONCE=1; shift ;;
    --force) ONCE=1; shift ;;  # old name: copy now even if incomplete
    --until-done) UNTIL_DONE=1; shift ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --pid-file) PID_FILE="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

log() { printf '%s %s\n' "$(date -Is)" "$*"; }

in_container() {
  docker exec "$CONTAINER" "$@"
}

read_progress() {
  local path="$1"
  in_container cat "$path" 2>/dev/null || echo "{}"
}

is_done() {
  python3 -c '
import json,sys
p=json.loads(sys.stdin.read() or "{}")
done=int(p.get("done") or 0)
errors=int(p.get("errors") or 0)
total=int(p.get("total") or 0)
print("yes" if total>0 and done+errors>=total else "no")
' <<<"$1"
}

progress_line() {
  python3 -c '
import json,sys
p=json.loads(sys.stdin.read() or "{}")
d,e,t = p.get("done",0), p.get("errors",0), p.get("total",0)
print("%s+%s/%s" % (d,e,t))
' <<<"$1"
}

copy_kind() {
  local kind="$1" src="$2"; shift
  local dest="${DEST}/${kind}"
  mkdir -p "$dest"
  local copied=0
  for f in "$@"; do
    if in_container test -f "${src}/${f}"; then
      docker cp "${CONTAINER}:${src}/${f}" "${dest}/${f}.tmp" >/dev/null
      if [[ "$f" == *.json ]]; then
        if python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "${dest}/${f}.tmp" 2>/dev/null; then
          mv "${dest}/${f}.tmp" "${dest}/${f}"
          copied=$((copied + 1))
        else
          log "skip corrupt ${kind}/${f}"
          rm -f "${dest}/${f}.tmp"
        fi
      else
        mv "${dest}/${f}.tmp" "${dest}/${f}"
        copied=$((copied + 1))
      fi
    fi
  done
  log "copied ${kind}: ${copied} files -> ${dest}"
}

sale_stamp=""
rent_stamp=""

loop() {
  local sale rent sline rline sale_done rent_done
  sale="$(read_progress "${SALE_SRC}/scrape_progress.json")"
  rent="$(read_progress "${RENT_SRC}/scrape_progress.json")"
  sline="$(progress_line "$sale")"
  rline="$(progress_line "$rent")"
  log "sale=${sline}  rent=${rline}"

  if [[ "$sline" != "$sale_stamp" ]]; then
    copy_kind sale "$SALE_SRC" "${SALE_FILES[@]}"
    sale_stamp="$sline"
  fi
  if [[ "$rline" != "$rent_stamp" ]]; then
    copy_kind rent "$RENT_SRC" "${RENT_FILES[@]}"
    rent_stamp="$rline"
  fi

  sale_done="$(is_done "$sale")"
  rent_done="$(is_done "$rent")"
  [[ "$sale_done" == "yes" && "$rent_done" == "yes" ]]
}

if [[ "$ONCE" -eq 1 ]]; then
  sale_stamp="__force__"
  rent_stamp="__force__"
  loop || true
  exit 0
fi

if [[ -n "${PID_FILE}" ]]; then
  if [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
    log "already running pid $(cat "${PID_FILE}")"
    exit 0
  fi
  echo $$ >"${PID_FILE}"
  trap 'rm -f "${PID_FILE}"' EXIT
fi

log "watching ${CONTAINER} every ${INTERVAL}s  dest=${DEST}  (copies on progress, not only at 100%)"
while true; do
  if loop; then
    if [[ "${complete_hook_ran}" -eq 0 ]]; then
      complete_hook_ran=1
      if [[ -n "${ON_COMPLETE}" && -f "${ON_COMPLETE}" ]]; then
        log "both scrapes complete — running ${ON_COMPLETE}"
        nohup python3 "${ON_COMPLETE}" --yad2 "${DEST}" >>"${DEST}/research/run.log" 2>&1 &
        log "research pid $!"
      fi
    fi
    if [[ "$UNTIL_DONE" -eq 1 ]]; then
      log "sale and rent both complete. exiting."
      exit 0
    fi
  fi
  sleep "$INTERVAL"
done
