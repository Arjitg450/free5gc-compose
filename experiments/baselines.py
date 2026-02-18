#!/usr/bin/env python3
"""
Deterministic baselines for control-plane segmentation.

FSM_STEPS, PROCEDURE_STARTS, and PROCEDURE_ENDS are based on verified
free5GC v4.1 log analysis (AMF internal FSM states: Deregistered ->
Authentication -> SecurityMode -> ContextSetup -> Registered).
"""

from __future__ import annotations

import argparse
import json
import pathlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Procedure boundary definitions (verified against real free5GC v4.1 logs)
# ---------------------------------------------------------------------------

PROCEDURE_STARTS: Dict[str, str] = {
    # AMF-side starts
    "initial_ue_message": "registration",
    "registration_request": "registration",
    "ue_sending_reg": "registration",
    # PDU session starts
    "ul_nas_transport": "pdu_session",
    "ue_pdu_send": "pdu_session",
    # Deregistration starts
    "deregistration_request": "deregistration",
    "ue_deregistered": "deregistration",
    # Retry/error
    "retry_or_timeout": "retry_flow",
}

PROCEDURE_ENDS: Dict[str, Set[str]] = {
    "registration": {
        "registration_complete",
        "ue_reg_complete",
        "ue_reg_success",
        "ue_reg_failed",
        "auth_reject",
    },
    "pdu_session": {
        "pdu_resource_setup_resp",
        "sm_context_create_success",
        "ue_pdu_success",
        "ue_pdu_reject",
        "sm_context_create_error",
    },
    "deregistration": {
        "ue_context_release_complete",
        "deregistration_accept",
    },
    "authentication_sub": {
        "ausf_aka_confirm",
        "udm_confirm_auth",
        "auth_sbi_failure",
    },
    "retry_flow": {
        "registration_complete",
        "ue_reg_success",
        "sm_context_create_success",
        "ue_pdu_success",
    },
    "handover": {"handover_event"},
}

# ---------------------------------------------------------------------------
# FSM step sequences per procedure (verified against real free5GC v4.1)
#
# Steps marked (CONDITIONAL) may be skipped; the FSM validator allows
# skipping up to MAX_FSM_SKIP consecutive steps.
# ---------------------------------------------------------------------------

MAX_FSM_SKIP = 3

FSM_STEPS: Dict[str, List[str]] = {
    "registration": [
        "initial_ue_message",           # [AMF][Ngap] Handle InitialUEMessage
        "registration_request",         # [AMF][Gmm] Handle Registration Request
        "identity_request",             # (CONDITIONAL)
        "identity_response",            # (CONDITIONAL)
        "auth_procedure_start",         # [AMF][Gmm] Authentication procedure
        "auth_request",                 # [AMF][Gmm] Send Authentication Request
        "auth_response",                # [AMF][Gmm] Handle Authentication Response
        "security_mode_command",        # [AMF][Gmm] Send Security Mode Command
        "security_mode_complete",       # [AMF][Gmm] Handle Security Mode Complete
        "initial_registration",         # [AMF][Gmm] Handle InitialRegistration
        "registration_accept",          # [AMF][Gmm] Send Registration Accept
        "initial_context_setup",        # [AMF][Ngap] Send Initial Context Setup Request
        "registration_complete",        # [AMF][Gmm] Handle Registration Complete
    ],
    "pdu_session": [
        "ul_nas_transport",             # [AMF][Gmm] Handle UL NAS Transport
        "transport_5gsm",               # [AMF][Gmm] Transport 5GSM Message to SMF
        "select_smf",                   # [AMF] Select SMF
        "smf_receive_create",           # [SMF][PduSess] Receive Create SM Context Request
        "sm_context_create",            # [SMF][PduSess] HandlePDUSessionSMContextCreate
        "pdu_session_est_req",          # [SMF][GSM] HandlePDUSessionEstablishmentRequest
        "smf_selected_upf",             # [SMF] Selected UPF
        "pfcp_session_est_req",         # [SMF][PFCP] Send PFCP Session Establishment Request
        "sm_context_create_success",    # [AMF][Gmm] create smContext Success
        "pdu_resource_setup",           # [AMF][Ngap] Send PDUSessionResourceSetupRequest
        "pdu_resource_setup_resp",      # [AMF][Ngap] Handle PDUSessionResourceSetupResponse
        "sm_context_update",            # [SMF] HandlePDUSessionSMContextUpdate
        "pfcp_session_mod_req",         # [SMF][PFCP] Send PFCP Session Modification Request
    ],
    "deregistration": [
        "deregistration_request",       # [AMF][Gmm] Handle Deregistration Request
        "sm_context_release",           # [SMF] HandlePDUSessionSMContextRelease
        "pfcp_session_del_req",         # [SMF][PFCP] Send PFCP Session Deletion
        "deregistration_accept",        # [AMF][Gmm] Send Deregistration Accept
        "ue_context_release_cmd",       # [AMF][Ngap] Send UE Context Release Command
        "ue_context_release_complete",  # [AMF][Ngap] Handle UE Context Release Complete
    ],
    "authentication_sub": [
        "ausf_auth_post",               # [AUSF] HandleUeAuthPostRequest
        "ausf_net_authorized",          # [AUSF] Serving network authorized
        "udm_generate_auth",            # [UDM] HandleGenerateAuthDataRequest
        "udm_suci_deconcealment",       # [UDM][Suci] suciPart: [...]
        "udr_query_auth",               # [UDR] HandleQueryAuthSubsData
        "ausf_aka_confirm",             # [AUSF] HandleAuth5gAkaComfirmRequest
        "udm_confirm_auth",             # [UDM] HandleConfirmAuthDataRequest
    ],
    "retry_flow": [
        "retry_or_timeout",
        "registration_request",
        "auth_request",
        "registration_accept",
        "registration_complete",
    ],
    "handover": ["handover_event"],
}

# AMF internal FSM state transitions from [LIB][FSM] log lines
FSM_TRANSITIONS: Dict[str, Tuple[str, str]] = {
    "Start Authentication":   ("Deregistered", "Authentication"),
    "Authentication Success": ("Authentication", "SecurityMode"),
    "SecurityMode Success":   ("SecurityMode", "ContextSetup"),
    "ContextSetup Success":   ("ContextSetup", "Registered"),
    "Gmm Message":            ("Registered", "Registered"),
}

# Events that indicate errors / retries (for B3 awareness)
ERROR_EVENT_TYPES = {
    "auth_failure", "auth_reject", "auth_sbi_failure",
    "sm_context_create_error", "ue_reg_failed", "ue_pdu_reject",
    "retry_or_timeout",
}


@dataclass
class Segment:
    segment_id: str
    procedure: str
    ue_key: str
    event_ids: List[int] = field(default_factory=list)
    start_ts: str = ""
    end_ts: str = ""
    closed: bool = False
    fsm_index: int = 0
    attempt: int = 1


def load_events(path: pathlib.Path) -> List[Dict]:
    events = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    events.sort(key=lambda e: e["timestamp"])
    return events


def new_segment_id(prefix: str, i: int) -> str:
    return f"{prefix}_{i:06d}"


def candidate_open_segments(open_segments: List[Segment], ue_key: str, procedure: Optional[str]) -> List[Segment]:
    out = [s for s in open_segments if (s.ue_key == ue_key or ue_key == "unknown")]
    if procedure:
        out = [s for s in out if s.procedure == procedure]
    return out


# ---------------------------------------------------------------------------
# FSM validation helpers
# ---------------------------------------------------------------------------

def is_valid_fsm_transition(segment: Segment, event_type: str) -> bool:
    """
    Check if event_type is a valid next step in the procedure FSM.
    Allows skipping up to MAX_FSM_SKIP steps (for conditional steps).
    """
    steps = FSM_STEPS.get(segment.procedure, [])
    if not steps:
        return True
    idx = segment.fsm_index
    for skip in range(MAX_FSM_SKIP + 1):
        check_idx = idx + skip
        if check_idx < len(steps) and event_type == steps[check_idx]:
            return True
    return event_type in PROCEDURE_ENDS.get(segment.procedure, set())


def advance_fsm(segment: Segment, event_type: str) -> None:
    """Advance the FSM index to the position after the matched step."""
    steps = FSM_STEPS.get(segment.procedure, [])
    idx = segment.fsm_index
    for skip in range(MAX_FSM_SKIP + 1):
        check_idx = idx + skip
        if check_idx < len(steps) and event_type == steps[check_idx]:
            segment.fsm_index = check_idx + 1
            return


# ---------------------------------------------------------------------------
# B1: ID + Window baseline
# ---------------------------------------------------------------------------

def run_b1(events: List[Dict], window_size_events: int = 40) -> Dict:
    seg_counter = 0
    open_segments: List[Segment] = []
    closed_segments: List[Segment] = []
    event_pos_by_id = {int(e["event_id"]): i for i, e in enumerate(events)}

    for idx, event in enumerate(events):
        et = event["event_type"]
        ue_key = event.get("ue_key", "unknown")
        procedure = PROCEDURE_STARTS.get(et)
        assigned = False

        if procedure:
            seg = Segment(
                segment_id=new_segment_id("b1", seg_counter),
                procedure=procedure,
                ue_key=ue_key,
                start_ts=event["timestamp"],
            )
            seg_counter += 1
            seg.event_ids.append(event["event_id"])
            open_segments.append(seg)
            assigned = True
        else:
            cands = candidate_open_segments(open_segments, ue_key=ue_key, procedure=None)
            if cands:
                seg = cands[-1]
                seg.event_ids.append(event["event_id"])
                assigned = True
                if et in PROCEDURE_ENDS.get(seg.procedure, set()):
                    seg.closed = True
                    seg.end_ts = event["timestamp"]
                    closed_segments.append(seg)
                    open_segments.remove(seg)

        for seg in list(open_segments):
            if not seg.event_ids:
                continue
            last_pos = event_pos_by_id.get(int(seg.event_ids[-1]), idx)
            if idx - last_pos > window_size_events:
                seg.closed = True
                seg.end_ts = event["timestamp"]
                closed_segments.append(seg)
                open_segments.remove(seg)

        if not assigned:
            pass

    for seg in open_segments:
        seg.closed = True
        seg.end_ts = seg.end_ts or seg.start_ts
        closed_segments.append(seg)

    return {
        "baseline": "B1_IDWindow",
        "segments": [segment_to_dict(s) for s in closed_segments],
    }


# ---------------------------------------------------------------------------
# B2: FSM-Constrained baseline
# ---------------------------------------------------------------------------

def run_b2(events: List[Dict]) -> Dict:
    seg_counter = 0
    open_segments: List[Segment] = []
    closed_segments: List[Segment] = []

    for event in events:
        et = event["event_type"]
        ue_key = event.get("ue_key", "unknown")
        procedure = PROCEDURE_STARTS.get(et)

        if procedure:
            seg = Segment(
                segment_id=new_segment_id("b2", seg_counter),
                procedure=procedure,
                ue_key=ue_key,
                start_ts=event["timestamp"],
            )
            seg_counter += 1
            seg.event_ids.append(event["event_id"])
            advance_fsm(seg, et)
            open_segments.append(seg)
            continue

        candidates = candidate_open_segments(open_segments, ue_key=ue_key, procedure=None)
        candidates = [s for s in candidates if is_valid_fsm_transition(s, et)]
        if candidates:
            seg = candidates[-1]
            seg.event_ids.append(event["event_id"])
            advance_fsm(seg, et)
            if et in PROCEDURE_ENDS.get(seg.procedure, set()):
                seg.closed = True
                seg.end_ts = event["timestamp"]
                closed_segments.append(seg)
                open_segments.remove(seg)

    for seg in open_segments:
        seg.closed = True
        seg.end_ts = seg.end_ts or seg.start_ts
        closed_segments.append(seg)

    return {
        "baseline": "B2_FSMConstrained",
        "segments": [segment_to_dict(s) for s in closed_segments],
    }


# ---------------------------------------------------------------------------
# B3: Retry-Aware FSM baseline
# ---------------------------------------------------------------------------

def run_b3(events: List[Dict]) -> Dict:
    seg_counter = 0
    open_segments: List[Segment] = []
    closed_segments: List[Segment] = []
    seen_duplicates: set[Tuple[str, str, int]] = set()
    retry_count: Dict[Tuple[str, str], int] = {}

    for event in events:
        et = event["event_type"]
        ue_key = event.get("ue_key", "unknown")
        dedup_key = (ue_key, et, int(event["event_id"]))
        if dedup_key in seen_duplicates:
            continue
        seen_duplicates.add(dedup_key)

        procedure = PROCEDURE_STARTS.get(et)
        if procedure:
            # If this is an error-triggered re-start, close the existing segment first
            existing = candidate_open_segments(open_segments, ue_key=ue_key, procedure=procedure)
            for old_seg in existing:
                old_seg.closed = True
                old_seg.end_ts = event["timestamp"]
                closed_segments.append(old_seg)
                open_segments.remove(old_seg)

            k = (ue_key, procedure)
            attempt = retry_count.get(k, 0) + 1
            retry_count[k] = attempt
            seg = Segment(
                segment_id=new_segment_id("b3", seg_counter),
                procedure=procedure,
                ue_key=ue_key,
                start_ts=event["timestamp"],
                attempt=attempt,
            )
            seg_counter += 1
            seg.event_ids.append(event["event_id"])
            advance_fsm(seg, et)
            open_segments.append(seg)
            continue

        candidates = candidate_open_segments(open_segments, ue_key=ue_key, procedure=None)
        candidates = [s for s in candidates if is_valid_fsm_transition(s, et)]

        if et in ERROR_EVENT_TYPES and candidates:
            candidates[-1].attempt += 1

        if candidates:
            seg = candidates[-1]
            seg.event_ids.append(event["event_id"])
            advance_fsm(seg, et)
            if et in PROCEDURE_ENDS.get(seg.procedure, set()):
                seg.closed = True
                seg.end_ts = event["timestamp"]
                closed_segments.append(seg)
                open_segments.remove(seg)

    for seg in open_segments:
        seg.closed = True
        seg.end_ts = seg.end_ts or seg.start_ts
        closed_segments.append(seg)

    return {
        "baseline": "B3_RetryAwareFSM",
        "segments": [segment_to_dict(s) for s in closed_segments],
    }


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def segment_to_dict(seg: Segment) -> Dict:
    return {
        "segment_id": seg.segment_id,
        "procedure": seg.procedure,
        "ue_key": seg.ue_key,
        "event_ids": seg.event_ids,
        "start_ts": seg.start_ts,
        "end_ts": seg.end_ts,
        "attempt": seg.attempt,
    }


def save_output(path: pathlib.Path, payload: Dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic segmentation baselines.")
    parser.add_argument("--run-dir", required=True, help="Path to experiments/runs/<run_id>.")
    args = parser.parse_args()

    run_dir = pathlib.Path(args.run_dir).resolve()
    events_path = run_dir / "normalized" / "events.jsonl"
    if not events_path.exists():
        raise SystemExit(f"Missing normalized events: {events_path}")

    events = load_events(events_path)
    preds_dir = run_dir / "predictions"
    preds_dir.mkdir(parents=True, exist_ok=True)

    b1 = run_b1(events)
    b2 = run_b2(events)
    b3 = run_b3(events)

    save_output(preds_dir / "B1_IDWindow.json", b1)
    save_output(preds_dir / "B2_FSMConstrained.json", b2)
    save_output(preds_dir / "B3_RetryAwareFSM.json", b3)

    for result in [b1, b2, b3]:
        name = result["baseline"]
        n_seg = len(result["segments"])
        procedures = {}
        for s in result["segments"]:
            procedures[s["procedure"]] = procedures.get(s["procedure"], 0) + 1
        print(f"  {name}: {n_seg} segments {procedures}")

    print(f"Wrote baseline outputs to {preds_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
