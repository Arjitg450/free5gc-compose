#!/usr/bin/env python3
"""
Normalize raw pcap files into structured control-plane events.

Uses tshark to decode:
  - NGAP  (SCTP port 38412)  → N2 signalling between gNB and AMF   (TS 38.413)
  - PFCP  (UDP port 8805)    → N4 session mgmt between SMF and UPF (TS 29.244)
  - HTTP/2 (TCP port 8000)   → SBI calls between NFs               (TS 29.5xx)
  - GTP-U (UDP port 2152)    → N3 user-plane tunnel evidence       (TS 29.281)

Output: normalized/events_pcap.jsonl in the same schema as log-based events.
See docs/3GPP_ALIGNMENT.md for specification references.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Container IP → NF name mapping (resolved at runtime via run_metadata)
# ---------------------------------------------------------------------------

DEFAULT_NF_PORT_MAP = {
    8000: "sbi",
    38412: "ngap",
    8805: "pfcp",
    2152: "gtp-u",
}

# 3GPP NGAP procedure codes → human-readable names (TS 38.413 Table 9.1.3)
NGAP_PROCEDURE_NAMES: Dict[int, Tuple[str, str]] = {
    0: ("amf_config_update", "nf_management"),
    10: ("handover_cancel", "handover"),
    11: ("handover_required", "handover"),
    12: ("handover_request", "handover"),
    14: ("initial_context_setup", "registration"),
    15: ("initial_ue_message", "registration"),
    21: ("nas_non_delivery", "nas_transport"),
    25: ("pdu_session_resource_modify", "pdu_session"),
    26: ("pdu_session_resource_modify_indication", "pdu_session"),
    27: ("pdu_session_resource_release", "deregistration"),
    28: ("pdu_session_resource_setup", "pdu_session"),
    29: ("paging", "paging"),
    33: ("ran_config_update", "nf_management"),
    38: ("ue_context_modification", "registration"),
    40: ("ue_context_release", "deregistration"),
    41: ("ue_context_release_request", "deregistration"),
    46: ("dl_nas_transport", "nas_transport"),
    47: ("ul_nas_transport", "nas_transport"),
    21: ("ng_setup", "gnb_setup"),
}

# 3GPP PFCP message types (TS 29.244 Table 7.2.1-1)
PFCP_MESSAGE_NAMES: Dict[int, Tuple[str, str]] = {
    1: ("pfcp_heartbeat_request", "pfcp_heartbeat"),
    2: ("pfcp_heartbeat_response", "pfcp_heartbeat"),
    5: ("pfcp_association_setup_request", "pfcp_association"),
    6: ("pfcp_association_setup_response", "pfcp_association"),
    50: ("pfcp_session_est_request", "pdu_session"),
    51: ("pfcp_session_est_response", "pdu_session"),
    52: ("pfcp_session_mod_request", "pdu_session"),
    53: ("pfcp_session_mod_response", "pdu_session"),
    54: ("pfcp_session_del_request", "deregistration"),
    55: ("pfcp_session_del_response", "deregistration"),
    56: ("pfcp_session_report_request", "pfcp_reporting"),
    57: ("pfcp_session_report_response", "pfcp_reporting"),
}


def find_tshark() -> str:
    path = shutil.which("tshark")
    if not path:
        raise SystemExit("tshark not found. Install wireshark-cli / tshark.")
    return path


def load_ip_nf_map(run_dir: pathlib.Path) -> Dict[str, str]:
    """Build IP → NF name map from run_metadata environment or fall back to convention."""
    meta_path = run_dir / "run_metadata.json"
    ip_map: Dict[str, str] = {}
    if meta_path.exists():
        with meta_path.open() as f:
            meta = json.load(f)
        for target in meta.get("scenario", {}).get("capture", {}).get("pcap_targets", []):
            container = target.get("container", "")
            if container:
                ip_map[container] = container
    return ip_map


# ---------------------------------------------------------------------------
# tshark field extraction per protocol
# ---------------------------------------------------------------------------

TSHARK_NGAP_FIELDS = [
    "frame.time_epoch",
    "ip.src", "ip.dst",
    "ngap.procedureCode",
    "ngap.RAN_UE_NGAP_ID",
    "ngap.AMF_UE_NGAP_ID",
]

TSHARK_PFCP_FIELDS = [
    "frame.time_epoch",
    "ip.src", "ip.dst",
    "pfcp.msg_type",
    "pfcp.seid",
    "pfcp.enterprise_id",
]

TSHARK_HTTP2_FIELDS = [
    "frame.time_epoch",
    "ip.src", "ip.dst",
    "tcp.srcport", "tcp.dstport",
    "http2.headers.method",
    "http2.headers.path",
    "http2.headers.status",
    "http2.header.value",
]

TSHARK_GTP_FIELDS = [
    "frame.time_epoch",
    "ip.src", "ip.dst",
    "gtp.teid",
    "gtp.message",
]


def run_tshark(tshark: str, pcap_path: str, display_filter: str,
               fields: List[str]) -> List[Dict[str, str]]:
    """Run tshark with field extraction and return list of field dicts."""
    cmd = [
        tshark, "-r", pcap_path, "-Y", display_filter,
        "-T", "fields", "-E", "separator=|", "-E", "header=y",
        "-E", "quote=n", "-E", "occurrence=f",
    ]
    for f in fields:
        cmd.extend(["-e", f])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        print(f"  [warn] tshark timed out on {pcap_path} filter={display_filter}")
        return []

    if result.returncode != 0:
        stderr = result.stderr.strip()[:200]
        if stderr:
            print(f"  [warn] tshark stderr: {stderr}")
        return []

    lines = result.stdout.strip().split("\n")
    if len(lines) < 2:
        return []

    headers = lines[0].split("|")
    rows = []
    for line in lines[1:]:
        vals = line.split("|")
        row = {}
        for i, h in enumerate(headers):
            row[h] = vals[i] if i < len(vals) else ""
        rows.append(row)
    return rows


def epoch_to_iso(epoch_str: str) -> str:
    """Convert tshark epoch timestamp to ISO 8601."""
    import datetime as dt
    try:
        ts = float(epoch_str)
        return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).isoformat()
    except (ValueError, OSError):
        return epoch_str


# ---------------------------------------------------------------------------
# Protocol-specific event extractors
# ---------------------------------------------------------------------------

def extract_ngap_events(tshark: str, pcap_path: str, source: str,
                        start_id: int) -> Tuple[List[Dict], int]:
    """Extract NGAP events from pcap."""
    rows = run_tshark(tshark, pcap_path, "ngap", TSHARK_NGAP_FIELDS)
    events = []
    eid = start_id
    for row in rows:
        proc_code_str = row.get("ngap.procedureCode", "")
        if not proc_code_str:
            continue
        try:
            proc_code = int(proc_code_str)
        except ValueError:
            continue
        event_type, procedure = NGAP_PROCEDURE_NAMES.get(
            proc_code, (f"ngap_proc_{proc_code}", "unknown")
        )
        ran_ue = row.get("ngap.RAN_UE_NGAP_ID", "") or None
        amf_ue = row.get("ngap.AMF_UE_NGAP_ID", "") or None

        events.append({
            "event_id": eid,
            "timestamp": epoch_to_iso(row.get("frame.time_epoch", "")),
            "source": f"pcap_{source}",
            "nf": "AMF",
            "category": "NGAP",
            "level": "PCAP",
            "interface_hint": "n2",
            "event_type": f"pcap_{event_type}",
            "procedure_hint": procedure,
            "ue_key": f"amfue-{amf_ue}" if amf_ue else (f"ranue-{ran_ue}" if ran_ue else "unknown"),
            "ids": {
                "supi": None,
                "ran_ue_ngap_id": ran_ue,
                "amf_ue_ngap_id": amf_ue,
                "pdu_session_id": None,
            },
            "raw_line": f"NGAP proc={proc_code} {event_type} {row.get('ip.src','')}→{row.get('ip.dst','')}",
        })
        eid += 1
    return events, eid


def extract_pfcp_events(tshark: str, pcap_path: str, source: str,
                        start_id: int) -> Tuple[List[Dict], int]:
    """Extract PFCP events from pcap."""
    rows = run_tshark(tshark, pcap_path, "pfcp", TSHARK_PFCP_FIELDS)
    events = []
    eid = start_id
    for row in rows:
        msg_type_str = row.get("pfcp.msg_type", "")
        if not msg_type_str:
            continue
        try:
            msg_type = int(msg_type_str)
        except ValueError:
            continue

        if msg_type in (1, 2, 56, 57):
            continue

        event_type, procedure = PFCP_MESSAGE_NAMES.get(
            msg_type, (f"pfcp_msg_{msg_type}", "unknown")
        )
        seid = row.get("pfcp.seid", "") or None

        events.append({
            "event_id": eid,
            "timestamp": epoch_to_iso(row.get("frame.time_epoch", "")),
            "source": f"pcap_{source}",
            "nf": "SMF" if msg_type % 2 == 0 else "UPF",
            "category": "PFCP",
            "level": "PCAP",
            "interface_hint": "n4",
            "event_type": f"pcap_{event_type}",
            "procedure_hint": procedure,
            "ue_key": f"seid-{seid}" if seid and seid != "0" else "unknown",
            "ids": {
                "supi": None,
                "ran_ue_ngap_id": None,
                "amf_ue_ngap_id": None,
                "pdu_session_id": None,
                "pfcp_seid": seid,
            },
            "raw_line": f"PFCP type={msg_type} {event_type} seid={seid} {row.get('ip.src','')}→{row.get('ip.dst','')}",
        })
        eid += 1
    return events, eid


SBI_PATH_TO_SERVICE: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r"/nausf-auth/"), "ausf_sbi_auth", "authentication_sub"),
    (re.compile(r"/nudm-ueau/"), "udm_sbi_auth", "authentication_sub"),
    (re.compile(r"/nudm-sdm/"), "udm_sbi_sdm", "registration"),
    (re.compile(r"/nudm-uecm/"), "udm_sbi_uecm", "registration"),
    (re.compile(r"/nudr-dr/.*authentication"), "udr_sbi_auth", "authentication_sub"),
    (re.compile(r"/nudr-dr/.*provisioned-data"), "udr_sbi_prov", "registration"),
    (re.compile(r"/nudr-dr/.*context-data"), "udr_sbi_ctx", "registration"),
    (re.compile(r"/nudr-dr/.*policy-data"), "udr_sbi_policy", "pdu_session"),
    (re.compile(r"/nudr-dr/"), "udr_sbi_data", "registration"),
    (re.compile(r"/nsmf-pdusession/"), "smf_sbi_pdu", "pdu_session"),
    (re.compile(r"/namf-comm/"), "amf_sbi_comm", "pdu_session"),
    (re.compile(r"/nnrf-disc/"), "nrf_sbi_disc", "sbi_discovery"),
    (re.compile(r"/nnrf-nfm/"), "nrf_sbi_nfm", "nf_management"),
    (re.compile(r"/oauth2/token"), "nrf_sbi_oauth", "sbi_auth"),
    (re.compile(r"/npcf-"), "pcf_sbi_policy", "pdu_session"),
    (re.compile(r"/nchf-"), "chf_sbi_charging", "pdu_session"),
]


def classify_sbi_path(path: str) -> Tuple[str, str]:
    """Map an SBI URL path to (event_type, procedure_hint)."""
    for pattern, event_type, procedure in SBI_PATH_TO_SERVICE:
        if pattern.search(path):
            return event_type, procedure
    return "sbi_unknown", "unknown"


def extract_http2_events(tshark: str, pcap_path: str, source: str,
                         start_id: int) -> Tuple[List[Dict], int]:
    """Extract HTTP/2 SBI events from pcap."""
    rows = run_tshark(tshark, pcap_path, "http2", TSHARK_HTTP2_FIELDS)
    events = []
    eid = start_id
    seen_requests: set = set()

    for row in rows:
        method = row.get("http2.headers.method", "")
        path = row.get("http2.headers.path", "")
        status = row.get("http2.headers.status", "")

        if not method and not status:
            continue
        if status and not method:
            continue

        dedup_key = (row.get("frame.time_epoch", ""), method, path)
        if dedup_key in seen_requests:
            continue
        seen_requests.add(dedup_key)

        if not path:
            continue

        event_type, procedure = classify_sbi_path(path)

        supi = None
        m = re.search(r"(imsi-\d{10,15})", path)
        if m:
            supi = m.group(1)

        events.append({
            "event_id": eid,
            "timestamp": epoch_to_iso(row.get("frame.time_epoch", "")),
            "source": f"pcap_{source}",
            "nf": source.upper(),
            "category": "SBI",
            "level": "PCAP",
            "interface_hint": "sbi",
            "event_type": f"pcap_{event_type}",
            "procedure_hint": procedure,
            "ue_key": supi if supi else "unknown",
            "ids": {
                "supi": supi,
                "ran_ue_ngap_id": None,
                "amf_ue_ngap_id": None,
                "pdu_session_id": None,
            },
            "raw_line": f"HTTP/2 {method} {path} {row.get('ip.src','')}→{row.get('ip.dst','')}",
        })
        eid += 1
    return events, eid


def extract_gtp_events(tshark: str, pcap_path: str, source: str,
                       start_id: int) -> Tuple[List[Dict], int]:
    """Extract GTP-U tunnel events (session evidence, not per-packet)."""
    rows = run_tshark(tshark, pcap_path, "gtp", TSHARK_GTP_FIELDS)
    events = []
    eid = start_id
    seen_teids: set = set()

    for row in rows:
        teid = row.get("gtp.teid", "")
        if not teid:
            continue
        if teid in seen_teids:
            continue
        seen_teids.add(teid)

        events.append({
            "event_id": eid,
            "timestamp": epoch_to_iso(row.get("frame.time_epoch", "")),
            "source": f"pcap_{source}",
            "nf": "UPF",
            "category": "GTP",
            "level": "PCAP",
            "interface_hint": "n3",
            "event_type": "pcap_gtp_tunnel_active",
            "procedure_hint": "pdu_session",
            "ue_key": f"teid-{teid}",
            "ids": {
                "supi": None,
                "ran_ue_ngap_id": None,
                "amf_ue_ngap_id": None,
                "pdu_session_id": None,
                "gtp_teid": teid,
            },
            "raw_line": f"GTP-U TEID={teid} {row.get('ip.src','')}→{row.get('ip.dst','')}",
        })
        eid += 1
    return events, eid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def normalize_pcap_file(tshark: str, pcap_path: pathlib.Path,
                        source: str, start_id: int) -> Tuple[List[Dict], Dict]:
    """Parse one pcap and return (events, coverage_stats)."""
    all_events: List[Dict] = []
    eid = start_id
    counts: Dict[str, int] = {}

    ngap_events, eid = extract_ngap_events(tshark, str(pcap_path), source, eid)
    all_events.extend(ngap_events)
    counts["ngap"] = len(ngap_events)

    pfcp_events, eid = extract_pfcp_events(tshark, str(pcap_path), source, eid)
    all_events.extend(pfcp_events)
    counts["pfcp"] = len(pfcp_events)

    http2_events, eid = extract_http2_events(tshark, str(pcap_path), source, eid)
    all_events.extend(http2_events)
    counts["http2_sbi"] = len(http2_events)

    gtp_events, eid = extract_gtp_events(tshark, str(pcap_path), source, eid)
    all_events.extend(gtp_events)
    counts["gtp"] = len(gtp_events)

    coverage = {
        "source": f"pcap_{source}",
        "pcap_file": pcap_path.name,
        "total_events": len(all_events),
        "per_protocol": counts,
    }
    return all_events, coverage


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize pcap files into events_pcap.jsonl."
    )
    parser.add_argument("--run-dir", required=True, help="Path to experiments/runs/<run_id>.")
    args = parser.parse_args()

    run_dir = pathlib.Path(args.run_dir).resolve()
    pcaps_dir = run_dir / "raw" / "pcaps"
    out_dir = run_dir / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not pcaps_dir.exists():
        print(f"[pcap] No pcaps directory: {pcaps_dir}")
        return 0

    pcap_files = sorted(pcaps_dir.glob("*.pcap"))
    if not pcap_files:
        print("[pcap] No pcap files found.")
        return 0

    tshark = find_tshark()
    print(f"[pcap] Using tshark: {tshark}")

    all_events: List[Dict] = []
    all_coverage: List[Dict] = []
    next_id = 0

    for pcap_path in pcap_files:
        source = pcap_path.stem
        print(f"  [pcap] Processing {pcap_path.name} (source={source})...")
        events, coverage = normalize_pcap_file(tshark, pcap_path, source, next_id)
        all_events.extend(events)
        all_coverage.append(coverage)
        next_id += len(events)
        total = coverage["total_events"]
        by_proto = coverage["per_protocol"]
        print(
            f"    → {total} events "
            f"(ngap={by_proto.get('ngap',0)}, pfcp={by_proto.get('pfcp',0)}, "
            f"sbi={by_proto.get('http2_sbi',0)}, gtp={by_proto.get('gtp',0)})"
        )

    all_events.sort(key=lambda x: x["timestamp"])

    out_path = out_dir / "events_pcap.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for event in all_events:
            f.write(json.dumps(event, sort_keys=True) + "\n")

    coverage_path = out_dir / "pcap_coverage.json"
    with coverage_path.open("w", encoding="utf-8") as f:
        json.dump({
            "total_pcap_events": len(all_events),
            "per_pcap": all_coverage,
        }, f, indent=2)

    print(f"[pcap] Wrote {len(all_events)} events to {out_path}")
    print(f"[pcap] Coverage report: {coverage_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
