#!/bin/bash
# ============================================================================
# run_attack_with_pcap.sh — Capture-enabled run (uses sudo for tcpdump)
# ============================================================================
# Run from free5gc-compose: ./attack_poc/run_attack_with_pcap.sh
# This execs the one-shot script with sudo so host tcpdump can capture N3
# GTP-U on the bridge and the pcap file is written.
# ============================================================================
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec sudo "${REPO_ROOT}/attack_poc/run_attack_from_scratch.sh" "$@"
