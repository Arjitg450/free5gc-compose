#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BASELINE_PCAP="/tmp/day2_baseline_n2.pcap"
BASELINE_LOG="/tmp/ue_baseline.log"
SECURE_PCAP="/tmp/day2_secure_n2.pcap"
SECURE_LOG="/tmp/ue_secure.log"
AMF_BAK="/tmp/amfcfg.day2.bak"
UE_BAK="/tmp/uecfg.day2.bak"
GNB_IP="10.100.200.12"
AMF_IP="10.100.200.16"
SUDO_CMD="sudo -n"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need_cmd docker
need_cmd python3
need_cmd sudo
need_cmd tcpdump
need_cmd strings

if [ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)" != "bootcamp" ]; then
  echo "This script must be run from the bootcamp branch." >&2
  exit 1
fi

if ! sudo -n true >/dev/null 2>&1; then
  echo "sudo access is required. You may be prompted once."
  sudo -v
fi

restore_secure_config() {
  if [ -f "$AMF_BAK" ] && [ -f "$UE_BAK" ]; then
    cp "$AMF_BAK" config/amfcfg.yaml
    cp "$UE_BAK" config/uecfg.yaml
  fi
}

restart_stack_edge() {
  docker restart amf ueransim >/dev/null
  sleep 8
}

start_n2_capture() {
  local pcap_file="$1"
  local pid_file="$2"
  $SUDO_CMD bash -lc "rm -f '$pcap_file' '$pid_file'; nohup tcpdump -i br-free5gc -w '$pcap_file' host $GNB_IP and host $AMF_IP >/tmp/$(basename "$pcap_file").log 2>&1 & echo \$! > '$pid_file'"
}

stop_n2_capture() {
  local pid_file="$1"
  $SUDO_CMD bash -lc "if [ -f '$pid_file' ]; then kill \$(cat '$pid_file') 2>/dev/null || true; fi"
}

run_ue() {
  local log_file="$1"
  docker exec ueransim bash -lc "if pgrep -x nr-ue >/dev/null 2>&1; then pkill -x nr-ue; fi; cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >'$log_file' 2>&1 &"
  sleep 20
}

trap 'stop_n2_capture /tmp/day2_baseline_n2.pid; stop_n2_capture /tmp/day2_secure_n2.pid; restore_secure_config' EXIT

$SUDO_CMD chown -R "$(id -un)":"$(id -gn)" "$REPO_ROOT"
./ovf/self-test.sh >/dev/null 2>&1 || self-test.sh >/dev/null

cp config/amfcfg.yaml "$AMF_BAK"
cp config/uecfg.yaml "$UE_BAK"

echo "[1/6] Running baseline comparison pass..."
python3 - <<'PY'
from pathlib import Path
p = Path('config/amfcfg.yaml')
s = p.read_text()
s = s.replace(
    "    cipheringOrder: # the priority of ciphering algorithms\n      - NEA2\n      - NEA0",
    "    cipheringOrder: # the priority of ciphering algorithms\n      - NEA0\n      - NEA2",
)
p.write_text(s)
PY
python3 - <<'PY'
from pathlib import Path
p = Path('config/uecfg.yaml')
s = p.read_text()
s = s.replace('\nprotectionScheme: 1\n', '\n# protectionScheme: 1\n')
s = s.replace('\nhomeNetworkPublicKeyId: 1\n', '\n# homeNetworkPublicKeyId: 1\n')
s = s.replace(
    '\nhomeNetworkPublicKey: "5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650"\n',
    '\n# homeNetworkPublicKey: "5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650"\n',
)
p.write_text(s)
PY
restart_stack_edge
start_n2_capture "$BASELINE_PCAP" /tmp/day2_baseline_n2.pid
run_ue "$BASELINE_LOG"
stop_n2_capture /tmp/day2_baseline_n2.pid

echo "[2/6] Restoring secure config..."
restore_secure_config
restart_stack_edge

echo "[3/6] Running secure comparison pass..."
start_n2_capture "$SECURE_PCAP" /tmp/day2_secure_n2.pid
run_ue "$SECURE_LOG"
stop_n2_capture /tmp/day2_secure_n2.pid

echo "[4/6] Final secure verification..."
./ovf/self-test.sh >/dev/null 2>&1 || self-test.sh >/dev/null

echo "[5/6] Comparison summary"
docker exec ueransim grep -E 'Selected integrity|Initial Registration is successful|PDU Session establishment is successful' "$BASELINE_LOG" "$SECURE_LOG"
docker compose logs --since 5m free5gc-amf | grep -E 'MobileIdentity5GS|Authentication|Security Mode|Registration' || true

echo "--- Baseline strings ---"
strings "$BASELINE_PCAP" | grep internet || true

echo "--- Secure strings ---"
strings "$SECURE_PCAP" | grep internet || true

echo "--- PCAP files ---"
ls -lh "$BASELINE_PCAP" "$SECURE_PCAP"

echo "[6/6] Done. Secure config is restored."
