# Gold Label Protocol for NetSAM Necessity Evaluation

## Purpose

This document defines how ground-truth ("gold") segmentation labels are
constructed for evaluating the B1/B2/B3 deterministic baselines. Without
independently verified gold labels, all precision/recall/F1 metrics are
meaningless.

## Definitions

- **Segment**: A contiguous group of control-plane events that belong to a
  single 5G NAS/NGAP procedure instance for one UE.
- **Procedure**: One of `registration`, `pdu_session`, `deregistration`,
  `authentication_sub`, `retry_flow`.
- **Event**: A single normalized log event from `events.jsonl`.

## Procedure Boundary Rules

### Registration

A registration segment starts at the **first** of these events for a given UE:
- `initial_ue_message` (AMF NGAP)
- `registration_request` (AMF GMM)
- `ue_sending_reg` (UERANSIM)

It ends at the **first** of these events:
- `registration_complete` (AMF GMM)
- `ue_reg_complete` or `ue_reg_success` (UERANSIM)
- `ue_reg_failed` or `auth_reject` (failure termination)

**Included middle events**: identity request/response, authentication
request/response, security mode command/complete, initial_registration,
registration_accept, initial_context_setup, all AUSF/UDM/UDR sub-procedure
events, FSM transitions, NRF discovery, DL NAS transport.

### PDU Session Establishment

Starts at:
- `ul_nas_transport` (AMF GMM)
- `ue_pdu_send` (UERANSIM)

Ends at:
- `pdu_resource_setup_resp` (AMF NGAP)
- `sm_context_create_success` (AMF GMM)
- `ue_pdu_success` (UERANSIM)
- `ue_pdu_reject` or `sm_context_create_error` (failure)

**Included middle events**: transport_5gsm, select_smf, SMF create/establish
events, PFCP establishment, UPF selection.

### Deregistration

Starts at:
- `deregistration_request` (AMF GMM)
- `ue_deregistered` (UERANSIM)

Ends at:
- `ue_context_release_complete` (AMF NGAP)
- `deregistration_accept` (AMF GMM)

**Included middle events**: sm_context_release, PFCP deletion.

## Labeling Tiers

### Tier 1: S1 (single UE) -- Automatic

For S1 scenarios with exactly 1 UE, gold labels are generated
deterministically by `generate_s1_gold.py`. Since there is no interleaving,
every event can be unambiguously assigned to its procedure.

**Verification**: Manually spot-check at least 5 segments by reading the
raw log lines and confirming the boundary events are correct.

### Tier 2: S2-S6 (multi-UE) -- Human-Reviewed

For multi-UE scenarios:

1. **Seed** initial labels from B2 output using `bootstrap_gold.py`.
2. **Review** each segment using `gold_review_tool.py`:
   - `y` (accept): Segment boundaries and procedure type are correct.
   - `n` (reject): Segment is fundamentally wrong (remove from gold).
   - `e` (edit): Change the procedure type.
   - `s` (split): Break one segment into two at a specified event boundary.
   - `m` (merge): Combine current segment with the next one.
3. **Save** reviewed labels and the review log.

## Ambiguity Handling

When boundaries are unclear:

1. **Prefer the most specific UE key.** If a segment has events with SUPI
   `imsi-208930000000005`, assign it to that UE even if some events have
   `ue_key=unknown`.

2. **Tie-breaking for interleaved events.** If event E could belong to
   Registration-A or Registration-B (both for the same UE), assign it to
   the segment whose FSM state makes E a valid next step.

3. **NRF discovery events** belong to the procedure that triggered them
   (typically registration or PDU session). Assign to the most recent open
   segment for that UE.

4. **FSM transition events** (`fsm_transition`) belong to the registration
   segment for the UE indicated in the same log line's tags.

5. **Events with `ue_key=unknown`** are assigned to the most recently opened
   segment. If no segment is open, they are left unassigned.

## Quality Control

- **Minimum review coverage**: For S2-S6, review at least 80% of segments.
- **Review log**: All decisions are recorded in `gold/review_log.json` for
  reproducibility and potential inter-annotator agreement studies.
- **Consistency check**: After review, run `analysis/evaluate.py` with the
  reviewed gold and verify that at least one baseline achieves F1 > 0.5 on
  the reviewed gold. If no baseline exceeds 0.5, the gold labels should be
  re-examined.

## File Locations

| File | Purpose |
|------|---------|
| `gold/segments_gold.json` | The gold standard labels |
| `gold/review_log.json` | Record of all review decisions |
| `gold/labeling_protocol.md` | This document |
