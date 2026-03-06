#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

TEMPLATE="ubuntu-22.04.5-free5gc.pkr.hcl"
STALL_TIMEOUT=600
CHECK_INTERVAL=15
KILL_ON_STALL=0
FORCE_BUILD=1
VM_NAME="ubuntu-22.04.5-free5gc"
CLEAN_VM=1

usage() {
  cat <<USAGE
Usage: ./packer-watch.sh [options]

Options:
  -t, --template FILE          Packer template file (default: ${TEMPLATE})
  -s, --stall-timeout SEC      Stall timeout in seconds (default: ${STALL_TIMEOUT})
  -i, --check-interval SEC     Watchdog polling interval in seconds (default: ${CHECK_INTERVAL})
  -k, --kill-on-stall          Stop build when stall timeout is hit
      --no-force               Do not pass -force to packer build
      --vm-name NAME           VM name to cleanup before build (default: ${VM_NAME})
      --keep-vm                Skip pre-build cleanup of existing VM with same name
  -h, --help                   Show this help

Examples:
  ./packer-watch.sh
  ./packer-watch.sh --stall-timeout 480 --kill-on-stall
  ./packer-watch.sh --no-force
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--template)
      TEMPLATE="${2:?missing template path}"
      shift 2
      ;;
    -s|--stall-timeout)
      STALL_TIMEOUT="${2:?missing timeout}"
      shift 2
      ;;
    -i|--check-interval)
      CHECK_INTERVAL="${2:?missing interval}"
      shift 2
      ;;
    -k|--kill-on-stall)
      KILL_ON_STALL=1
      shift
      ;;
    --no-force)
      FORCE_BUILD=0
      shift
      ;;
    --vm-name)
      VM_NAME="${2:?missing vm name}"
      shift 2
      ;;
    --keep-vm)
      CLEAN_VM=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ ! -f "$TEMPLATE" ]]; then
  echo "Template not found: $TEMPLATE" >&2
  exit 2
fi

if ! [[ "$STALL_TIMEOUT" =~ ^[0-9]+$ ]] || ! [[ "$CHECK_INTERVAL" =~ ^[0-9]+$ ]]; then
  echo "stall-timeout and check-interval must be positive integers" >&2
  exit 2
fi

if (( CHECK_INTERVAL == 0 )); then
  echo "check-interval must be > 0" >&2
  exit 2
fi

mkdir -p logs
STAMP="$(date +%Y%m%d-%H%M%S)"
UI_LOG="logs/packer-ui-${STAMP}.log"
DEBUG_LOG="logs/packer-debug-${STAMP}.log"

cleanup() {
  if [[ -n "${TAIL_PID:-}" ]] && kill -0 "$TAIL_PID" 2>/dev/null; then
    kill "$TAIL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "[$(date '+%F %T')] Starting build: $TEMPLATE"
echo "[$(date '+%F %T')] UI log: $UI_LOG"
echo "[$(date '+%F %T')] Debug log: $DEBUG_LOG"

if (( CLEAN_VM == 1 )); then
  if VBoxManage list vms | grep -Fq "\"$VM_NAME\""; then
    echo "[$(date '+%F %T')] Found existing VM: $VM_NAME (cleaning it)"
    VBoxManage controlvm "$VM_NAME" poweroff >/dev/null 2>&1 || true
    VBoxManage unregistervm "$VM_NAME" --delete >/dev/null 2>&1 || true
  fi
  vm_dir="$HOME/VirtualBox VMs/$VM_NAME"
  if [[ -d "$vm_dir" ]]; then
    echo "[$(date '+%F %T')] Removing stale VM directory: $vm_dir"
    rm -rf "$vm_dir"
  fi
fi

touch "$UI_LOG"
build_cmd=(packer build -timestamp-ui "$TEMPLATE")
if (( FORCE_BUILD == 1 )); then
  build_cmd=(packer build -force -timestamp-ui "$TEMPLATE")
fi
echo "[$(date '+%F %T')] Command: ${build_cmd[*]}"
PACKER_LOG=1 PACKER_LOG_PATH="$DEBUG_LOG" "${build_cmd[@]}" >"$UI_LOG" 2>&1 &
PACKER_PID=$!

tail -n +1 -f "$UI_LOG" &
TAIL_PID=$!

start_ts=$(date +%s)
last_change_ts=$start_ts
last_size=0

while kill -0 "$PACKER_PID" 2>/dev/null; do
  sleep "$CHECK_INTERVAL"
  now=$(date +%s)
  size=$(stat -c %s "$UI_LOG" 2>/dev/null || echo 0)

  if (( size > last_size )); then
    last_change_ts=$now
    last_size=$size
  fi

  elapsed=$(( now - start_ts ))
  idle=$(( now - last_change_ts ))
  printf '[%s] watchdog: elapsed=%ss idle=%ss\n' "$(date '+%F %T')" "$elapsed" "$idle"

  if (( idle >= STALL_TIMEOUT )); then
    echo "[$(date '+%F %T')] watchdog: no new packer output for ${STALL_TIMEOUT}s"
    if (( KILL_ON_STALL == 1 )); then
      echo "[$(date '+%F %T')] watchdog: stopping stuck build"
      kill "$PACKER_PID" 2>/dev/null || true
      sleep 2
      if kill -0 "$PACKER_PID" 2>/dev/null; then
        kill -9 "$PACKER_PID" 2>/dev/null || true
      fi
    fi
    break
  fi
done

wait "$PACKER_PID" || rc=$?
rc=${rc:-0}

if (( rc == 0 )); then
  echo "[$(date '+%F %T')] Build finished successfully"
else
  echo "[$(date '+%F %T')] Build failed (exit code $rc)"
  echo "Last 30 log lines:"
  tail -n 30 "$UI_LOG" || true
fi

exit "$rc"
