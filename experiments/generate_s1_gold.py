#!/usr/bin/env python3
"""
Generate deterministic gold labels for S1 (single-UE, clean) scenarios.

Since S1 has exactly 1 UE and no interleaving, procedure boundaries are
unambiguous: each Registration starts at the first registration-related event
and ends at registration_complete/ue_reg_success; each PDU session starts at
ul_nas_transport/ue_pdu_send and ends at the corresponding success/response.

The output is a high-confidence gold standard suitable for evaluating baselines.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Dict, List, Optional, Set

# Procedure start events (first event opens a new segment)
REGISTRATION_STARTS = {
    "initial_ue_message", "registration_request", "ue_sending_reg",
}
PDU_SESSION_STARTS = {
    "ul_nas_transport", "ue_pdu_send",
}
DEREGISTRATION_STARTS = {
    "deregistration_request", "ue_deregistered",
}

# Procedure end events (segment closes after this event)
REGISTRATION_ENDS = {
    "registration_complete", "ue_reg_complete", "ue_reg_success", "ue_reg_failed", "auth_reject",
}
PDU_SESSION_ENDS = {
    "pdu_resource_setup_resp", "sm_context_create_success",
    "ue_pdu_success", "ue_pdu_reject", "sm_context_create_error",
}
DEREGISTRATION_ENDS = {
    "ue_context_release_complete", "deregistration_accept",
}

# Events that belong to a registration procedure (middle events)
REGISTRATION_MEMBERS = {
    "initial_ue_message", "registration_request", "ue_sending_reg",
    "identity_request", "identity_response",
    "auth_procedure_start", "auth_request", "auth_response",
    "auth_failure", "auth_reject", "auth_sbi_failure",
    "security_mode_command", "security_mode_complete",
    "initial_registration", "registration_accept", "initial_context_setup",
    "registration_complete",
    "ue_reg_initiated", "ue_auth_request", "ue_sec_mode_cmd",
    "ue_reg_accept", "ue_reg_complete", "ue_reg_success", "ue_reg_failed",
    "ue_rrc_connected", "ue_cell_selected",
    "ausf_auth_post", "ausf_net_authorized", "ausf_aka_confirm",
    "udm_generate_auth", "udm_suci_deconcealment", "udm_confirm_auth",
    "udm_create_amf_ctx", "udm_get_am_data", "udm_get_smf_select",
    "udr_query_auth", "udr_create_amf_ctx",
    "nrf_discovery",
    "fsm_transition",
    "dl_nas_transport",
}

PDU_SESSION_MEMBERS = {
    "ul_nas_transport", "transport_5gsm", "select_smf",
    "smf_receive_create", "sm_context_create",
    "pdu_session_est_req", "smf_selected_upf",
    "pfcp_session_est_req", "sm_context_create_success",
    "pdu_resource_setup", "pdu_resource_setup_resp",
    "sm_context_update", "pfcp_session_mod_req",
    "ue_pdu_send", "ue_pdu_success", "ue_pdu_reject",
    "sm_context_create_error",
}

DEREGISTRATION_MEMBERS = {
    "deregistration_request", "deregistration_accept",
    "sm_context_release", "pfcp_session_del_req",
    "ue_context_release_cmd", "ue_context_release_complete",
    "ue_deregistered",
}


def load_events(path: pathlib.Path) -> List[Dict]:
    events = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    events.sort(key=lambda e: e["timestamp"])
    return events


def generate_gold(events: List[Dict]) -> List[Dict]:
    """Walk through events sequentially, grouping into procedure segments."""
    segments: List[Dict] = []
    seg_counter = 0
    current_seg: Optional[Dict] = None
    current_ends: Set[str] = set()
    current_members: Set[str] = set()

    for event in events:
        et = event["event_type"]
        eid = event["event_id"]

        # Skip state-change and other non-procedure events
        if et in ("ue_state_change",):
            if current_seg is not None:
                current_seg["event_ids"].append(eid)
            continue

        # Check if this event starts a new procedure
        new_procedure = None
        if et in REGISTRATION_STARTS:
            new_procedure = "registration"
        elif et in PDU_SESSION_STARTS:
            new_procedure = "pdu_session"
        elif et in DEREGISTRATION_STARTS:
            new_procedure = "deregistration"

        if new_procedure:
            # Close any open segment first
            if current_seg is not None:
                current_seg["end_ts"] = event["timestamp"]
                segments.append(current_seg)

            seg_id = f"gold_{seg_counter:06d}"
            seg_counter += 1
            current_seg = {
                "segment_id": seg_id,
                "procedure": new_procedure,
                "ue_key": event.get("ue_key", "unknown"),
                "event_ids": [eid],
                "start_ts": event["timestamp"],
                "end_ts": "",
                "attempt": 1,
            }
            if new_procedure == "registration":
                current_ends = REGISTRATION_ENDS
                current_members = REGISTRATION_MEMBERS
            elif new_procedure == "pdu_session":
                current_ends = PDU_SESSION_ENDS
                current_members = PDU_SESSION_MEMBERS
            else:
                current_ends = DEREGISTRATION_ENDS
                current_members = DEREGISTRATION_MEMBERS
            continue

        # If we have an open segment, try to add the event
        if current_seg is not None:
            if et in current_members or et in current_ends:
                current_seg["event_ids"].append(eid)
                if et in current_ends:
                    current_seg["end_ts"] = event["timestamp"]
                    segments.append(current_seg)
                    current_seg = None
                    current_ends = set()
                    current_members = set()
            else:
                # Event doesn't belong to current procedure; attach anyway
                # for single-UE this is a safe fallback
                current_seg["event_ids"].append(eid)

    # Close any remaining open segment
    if current_seg is not None:
        if not current_seg["end_ts"] and current_seg["event_ids"]:
            current_seg["end_ts"] = current_seg["start_ts"]
        segments.append(current_seg)

    return segments


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate deterministic gold labels for S1 single-UE scenarios."
    )
    parser.add_argument("--run-dir", required=True, help="Path to experiments/runs/<run_id>.")
    args = parser.parse_args()

    run_dir = pathlib.Path(args.run_dir).resolve()
    events_path = run_dir / "normalized" / "events.jsonl"
    gold_dir = run_dir / "gold"
    gold_dir.mkdir(parents=True, exist_ok=True)

    if not events_path.exists():
        raise SystemExit(f"Missing normalized events: {events_path}")

    events = load_events(events_path)
    if not events:
        raise SystemExit("No events found in normalized stream.")

    # Verify single-UE assumption
    ue_keys = {e.get("ue_key", "unknown") for e in events} - {"unknown"}
    if len(ue_keys) > 1:
        print(f"[WARN] Found {len(ue_keys)} distinct UE keys: {ue_keys}")
        print("[WARN] S1 gold generator assumes single-UE; results may be inaccurate.")

    segments = generate_gold(events)

    gold_output = {
        "label_source": "auto_s1_deterministic",
        "review_required": False,
        "ue_keys_found": sorted(ue_keys),
        "segments": segments,
    }

    out_path = gold_dir / "segments_gold.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(gold_output, f, indent=2)

    # Print summary
    procedures = {}
    for s in segments:
        procedures[s["procedure"]] = procedures.get(s["procedure"], 0) + 1
    total_events = sum(len(s["event_ids"]) for s in segments)

    print(f"Generated {len(segments)} gold segments covering {total_events} events")
    print(f"Procedure breakdown: {procedures}")
    print(f"Output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
