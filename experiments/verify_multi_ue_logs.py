#!/usr/bin/env python3
"""
Verify from experiment run logs that multi-UE was used (multiple UEs with different IPs).
Usage: python verify_multi_ue_logs.py <path-to-run-dir>
Example: python verify_multi_ue_logs.py runs/S2_moderate_interleave__r1__20260218_171713
"""
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: verify_multi_ue_logs.py <path-to-run-dir>")
        print("Example: verify_multi_ue_logs.py runs/S2_moderate_interleave__r1__20260218_171713")
        return 1
    run_dir = Path(sys.argv[1])
    logs_dir = run_dir / "raw" / "logs"
    if not logs_dir.is_dir():
        print(f"Logs dir not found: {logs_dir}")
        return 1

    print("=== Multi-UE log verification ===\n")

    # 1. UERANSIM: count distinct UEs in a short time window (concurrent)
    ueransim_log = logs_dir / "ueransim.log"
    if ueransim_log.exists():
        text = ueransim_log.read_text()
        ue_signals = re.findall(r"UE\[(\d+)\] new signal detected", text)
        rrc_setups = re.findall(r"RRC Setup for UE\[(\d+)\]", text)
        pdu_setups = re.findall(r"PDU session resource\(s\) setup for UE\[(\d+)\]", text)
        unique_ues_rrc = set(rrc_setups)
        print(f"UERANSIM: {len(ue_signals)} 'new signal' events, {len(unique_ues_rrc)} distinct UEs (RRC Setup), {len(pdu_setups)} PDU session setup(s)")
        if len(unique_ues_rrc) > 1:
            print(f"  -> Multiple UEs present: UE indices {sorted(set(int(u) for u in unique_ues_rrc))}")
        else:
            print("  -> Single UE or no RRC setups")
    else:
        print("UERANSIM: log not found")

    # 2. AMF: count new AmfUe (distinct GUTIs)
    amf_log = logs_dir / "amf.log"
    if amf_log.exists():
        text = amf_log.read_text()
        new_amf_ue = re.findall(r"New AmfUe \[supi:\]\[guti:([^\]]+)\]", text)
        initial_ue = re.findall(r"Handle InitialUEMessage", text)
        print(f"\nAMF: {len(new_amf_ue)} New AmfUe (distinct GUTIs), {len(initial_ue)} InitialUEMessage")
        if len(new_amf_ue) > 1:
            print(f"  -> Multi-UE: {len(new_amf_ue)} UE contexts")
    else:
        print("\nAMF: log not found")

    # 3. SMF: unique SUPIs and allocated IPs
    smf_log = logs_dir / "smf.log"
    if smf_log.exists():
        text = smf_log.read_text()
        supis = set(re.findall(r"supi:(imsi-\d+)", text))
        ips = set(re.findall(r"Allocated UE IP address: ([\d.]+)", text))
        pdu_addrs = set(re.findall(r"Allocated PDUAdress\[([\d.]+)\]", text))
        print(f"\nSMF: {len(supis)} unique SUPI(s), {len(ips)} allocated UE IP(s)")
        if supis:
            print(f"  SUPIs: {sorted(supis)}")
        if ips:
            print(f"  IPs:   {sorted(ips)}")
        if len(supis) > 1 and len(ips) > 1:
            print("  -> Multi-UE with different IPs: OK")
        elif len(supis) == 1 and len(ips) <= 2:
            print("  -> Single UE (or one UE with 2 PDU sessions)")
    else:
        print("\nSMF: log not found")

    # 4. UPF: PFCP session count
    upf_log = logs_dir / "upf.log"
    if upf_log.exists():
        text = upf_log.read_text()
        new_sessions = re.findall(r"New session", text)
        print(f"\nUPF: {len(new_sessions)} PFCP 'New session' events")
        if len(new_sessions) > 2:
            print("  -> Multiple PDU sessions (consistent with multi-UE)")
    else:
        print("\nUPF: log not found")

    print("\n=== Done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
