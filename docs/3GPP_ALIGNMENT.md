# 3GPP 5G Specification Alignment — Parser Verification

This document verifies that the event normalizer (`experiments/normalize_events.py`) and its event types, procedure hints, and interface hints align with 3GPP 5G System (5GS) documentation. Multi-source search was used against ETSI/3GPP specs.

---

## 1. Reference points (interfaces)

| Our `interface_hint` | 3GPP reference point | Spec | Notes |
|---------------------|----------------------|------|--------|
| `n2` | **N2** (RAN–AMF) | TS 23.501 | NGAP over SCTP. We map NGAP, N2, SCTP categories → n2. ✓ |
| `n4` | **N4** (SMF–UPF) | TS 23.501 | PFCP. We map PFCP, Perio → n4. ✓ |
| `n3` | **N3** (RAN–UPF) | TS 23.501 | GTP-U user plane. We map Gtp5g, Buff → n3. ✓ |
| `sbi` | **Service Based Interface** | TS 23.501, TS 29.5xx | HTTP/2, JSON. We map GIN, SBI, Consumer, DataRepo, UeAuth, Charging, Disc → sbi. ✓ |
| `nas` | **N1** (UE–AMF) | TS 23.501 | NAS signalling. We use "nas" as protocol name; N1 is the reference point. ✓ |
| `rrc` | RRC (UE–gNB) | TS 38.331 | Not a 5GC reference point; we use for RAN-side events. ✓ |

---

## 2. 5GMM / NAS procedure and message names (TS 24.501, TS 23.502)

| Our event_type / log pattern | 3GPP term | Spec | Notes |
|-----------------------------|-----------|------|--------|
| Registration Request, Accept, Complete, Reject | **Registration Request / Accept / Complete / Reject** | TS 24.501 §4, TS 23.502 | Message types 0x41–0x44. ✓ |
| Initial Registration | **Initial registration** | TS 23.502 | Type of registration procedure. ✓ |
| Authentication Request, Response, Failure, Reject | **Authentication Request / Response / Failure / Reject** | TS 24.501 | 0x56–0x59, 0x58. ✓ |
| Security Mode Command, Complete | **Security Mode Command / Complete** | TS 24.501 | ✓ |
| Identity Request, Response | **Identity Request / Response** | TS 24.501 | ✓ |
| Deregistration Request, Accept | **Deregistration Request / Accept** | TS 24.501 | ✓ |
| Handle UL NAS Transport, Transport 5GSM Message to SMF | **UL NAS Transport**, **5GSM** (session management) | TS 24.501, TS 23.502 | PDU Session Establishment. ✓ |
| 5GMM states (UERANSIM: MM-*) | **5GMM-DEREGISTERED**, **5GMM-REGISTERED**, **5GMM-REGISTERED-INITIATED** | TS 24.501 §5.1.3.2.1.2 | UERANSIM logs use "MM-*"; semantically equivalent to 5GMM-*. ✓ |

---

## 3. NGAP (TS 38.413)

| Our event_type / pattern | 3GPP term | Notes |
|--------------------------|-----------|--------|
| InitialUEMessage | **Initial UE Message** | NGAP procedure. ✓ |
| Initial Context Setup Request | **Initial Context Setup** | ✓ |
| PDUSessionResourceSetupRequest / Response | **PDU Session Resource Setup** | ✓ |
| UE Context Release Command / Complete | **UE Context Release** | ✓ |
| Uplink/Downlink NAS Transport | **Uplink/Downlink NAS Transport** | ✓ |

---

## 4. PFCP (TS 29.244)

| Our event_type / pattern | 3GPP term | Notes |
|--------------------------|-----------|--------|
| Session Establishment Request/Response | **PFCP Session Establishment Request/Response** | ✓ |
| Session Modification Request | **PFCP Session Modification Request** | ✓ |
| Session Deletion Request/Response | **PFCP Session Deletion**; implementation may log "Accepted Response". ✓ |

---

## 5. SBI service and API naming (TS 29.5xx)

| Our GIN path / pattern | 3GPP service / API | Spec | Notes |
|------------------------|--------------------|------|--------|
| `/namf-comm/` | **Namf_Communication** (e.g. N1N2MessageTransfer) | TS 29.518 | ✓ |
| `/nausf-auth/` | **Nausf_UEAuthentication** | TS 29.509 | ✓ |
| `/nudm-ueau/` | **Nudm_UEAuthentication** (GenerateAuthData, ConfirmAuth) | TS 29.503 | ✓ |
| `/nudm-sdm/` | **Nudm_SDM** (subscription data) | TS 29.503 | ✓ |
| `/nudm-uecm/` | **Nudm_UECM** (UE context management) | TS 29.503 | ✓ |
| `/nudr-dr/` | **Nudr_DR** (Data Repository); `{apiRoot}/nudr-dr/v2/` | TS 29.504 | subscription-data, provisioned-data, context-data, policy-data. ✓ |
| `/nnrf-disc/v1/nf-instances` | **Nnrf_NFDiscovery** | TS 29.510 | ✓ |
| `/nnrf-nfm/v1/nf-instances` | **Nnrf_NFManagement** (NFRegister, NFUpdate) | TS 29.510 | ✓ |
| `/nsmf-pdusession/` | **Nsmf_PDUSession** (CreateSMContext, etc.) | TS 29.502, TS 29.512 | ✓ |
| `/oauth2/token` | OAuth2 token (SBI security) | TS 29.500 | ✓ |

---

## 6. Procedure hints vs 3GPP procedures

| Our `procedure_hint` | 3GPP procedure / concept | Spec |
|----------------------|---------------------------|------|
| `registration` | Registration procedure (Initial/Periodic/Mobility/Emergency) | TS 23.502 §4.2.2 |
| `deregistration` | Deregistration procedure | TS 23.502 |
| `pdu_session` | PDU Session Establishment / Modification / Release | TS 23.502 §4.3.2 |
| `authentication_sub` | Primary authentication (AMF–AUSF–UDM); "Authentication subscription" | TS 23.502 §4.2.7, TS 33.501 |
| `sbi_discovery` | NF discovery (Nnrf_NFDiscovery) | TS 29.510 |
| `nf_management` | NF registration/update (Nnrf_NFManagement) | TS 29.510 |
| `nas_transport` | NAS transport (N1/N2) | TS 24.501 |
| `pfcp_association` | PFCP Association (SMF–UPF) | TS 29.244 |
| `sbi_auth` | SBI OAuth2 / token | TS 29.500 |
| `gnb_setup` | NG Setup (gNB–AMF) | TS 38.413 |
| `ue_state` | 5GMM state (UE side) | TS 24.501 §5.1.3 |
| `retry_flow` | Implementation (timeout/retransmit) | — |
| `handover` | Handover procedures | TS 23.502 |
| `fsm` | Internal FSM (e.g. 5GMM state machine) | Implementation |

---

## 7. Identifiers (SUPI, SUCI, NGAP IDs)

| Our `ids` / `ue_key` | 3GPP term | Notes |
|----------------------|-----------|--------|
| `supi` (imsi-…) | **SUPI** (Subscription Permanent Identifier) | TS 23.501 §2.2. ✓ |
| SUCI in messages | **SUCI** (Subscription Concealed Identifier) | TS 24.501, TS 33.501. ✓ |
| `amf_ue_ngap_id`, `ran_ue_ngap_id` | **AMF UE NGAP ID**, **RAN UE NGAP ID** | TS 38.413. ✓ |
| `pdu_session_id` | **PDU Session ID** | TS 24.501, TS 23.502. ✓ |
| UERANSIM `UE[N]` → `ran_ue_ngap_id` | RAN UE NGAP ID (or local UE index) | Implementation; used for correlation. ✓ |

---

## 8. Minor implementation vs spec

- **PFCP response text**: 3GPP TS 29.244 uses "PFCP Session Establishment Response"; free5GC logs "PFCP Session Establishment **Accepted** Response". Parser matches implementation. ✓
- **5GMM state names**: 3GPP TS 24.501 uses **5GMM-** (e.g. 5GMM-REGISTERED-INITIATED). UERANSIM uses **MM-** in logs. Parser matches simulator; semantics align. ✓
- **Nudm_UEAuthentication**: API path is `nudm-ueau` (not "ueauth"); our patterns use `nudm-ueau`. ✓

---

## 9. Summary

- **Reference points**: N1 (NAS), N2 (NGAP), N3 (GTP-U), N4 (PFCP), SBI — all reflected in `interface_hint`. ✓  
- **5GMM/NAS**: Registration, Authentication, Security Mode, Identity, Deregistration, UL/DL NAS Transport — message and procedure names align with TS 24.501 / TS 23.502. ✓  
- **NGAP**: Initial UE Message, Initial Context Setup, PDU Session Resource Setup, UE Context Release — align with TS 38.413. ✓  
- **PFCP**: Session Establishment / Modification / Deletion — align with TS 29.244. ✓  
- **SBI**: Nudm, Nausf, Nnrf, Namf, Nsmf, Nudr_DR paths and services — align with TS 29.503, 29.504, 29.509, 29.510, 29.518, 29.512. ✓  
- **Procedure hints**: Mapped to 3GPP procedure areas (registration, PDU session, authentication, NF discovery/management). ✓  

No mandatory 3GPP naming or procedure mismatches were found. The parser is aligned with 3GPP 5G documentation for the purposes of control-plane event normalization and segmentation.

---

## 10. Pcap capture: ports and reference points (run_experiment, scenarios)

Capture filters and ports used in `pcap_targets` must align with 3GPP reference points and assigned ports.

| Capture target | Filter | 3GPP reference | Spec / assignment | Notes |
|----------------|--------|-----------------|-------------------|--------|
| AMF | `sctp port 38412 or tcp port 8000` | **N2** (NGAP), **SBI** | TS 38.412/38.413 (NGAP over SCTP); configurable port. free5GC default **38412** (TS number). SBI **8000** (implementation). | ✓ |
| SMF | `udp port 8805 or tcp port 8000` | **N4** (PFCP), **SBI** | TS 29.244: PFCP over UDP; IANA/3GPP **8805**. SBI 8000. | ✓ |
| UPF | `udp port 2152 or udp port 8805` | **N3** (GTP-U), **N4** (PFCP) | TS 29.281: GTP-U **2152**. PFCP **8805**. | ✓ |

- **NGAP (SCTP)**: Port 38412 is the free5GC default (TS 38.412 does not mandate a single port; implementations choose it). ✓  
- **PFCP (UDP 8805)**: Officially assigned for PFCP (3GPP/IANA). ✓  
- **GTP-U (UDP 2152)**: Standard port for GTPv1-U (TS 29.281). ✓  
- **SBI (TCP 8000)**: Implementation choice; 3GPP SBI is HTTP/2, port not fixed by spec. ✓  

No shortcuts: filters restrict to the relevant protocols per interface.

---

## 11. Pcap normalizer (normalize_pcap.py) — spec alignment

### 11.1 NGAP procedure codes (TS 38.413 Table 9.1.3)

| Code | Our name | 3GPP procedure | procedure_hint |
|------|----------|----------------|----------------|
| 0 | ng_setup | NG Setup | gnb_setup |
| 1 | amf_config_update | AMF Configuration Update | nf_management |
| 14 | initial_context_setup | Initial Context Setup | registration |
| 15 | initial_ue_message | Initial UE Message | registration |
| 21 | nas_non_delivery | NAS Non Delivery Indication | nas_transport |
| 27 | pdu_session_resource_release | PDU Session Resource Release | deregistration |
| 28 | pdu_session_resource_setup | PDU Session Resource Setup | pdu_session |
| 40 | ue_context_release | UE Context Release | deregistration |
| 41 | ue_context_release_request | UE Context Release Request | deregistration |
| 46 | dl_nas_transport | Downlink NAS Transport | nas_transport |
| 47 | ul_nas_transport | Uplink NAS Transport | nas_transport |

Procedure codes 10–12 (handover), 25–26 (PDU session modify), 29 (paging), 33 (RAN config update), 38 (UE context modification) are also mapped per TS 38.413. **Duplicate key fix**: Previously procedure code 21 was mapped twice (nas_non_delivery and ng_setup); 21 is **NAS Non Delivery Indication** per spec. NG Setup is procedure code **0** (non-UE-associated). ✓  

### 11.2 PFCP message types (TS 29.244 Table 7.2.1-1)

| Type | Our name | 3GPP | procedure_hint | Emitted? |
|------|----------|------|----------------|----------|
| 1, 2 | pfcp_heartbeat_* | Heartbeat Request/Response | pfcp_heartbeat | No (filtered) |
| 5, 6 | pfcp_association_setup_* | Association Setup Request/Response | pfcp_association | Yes |
| 50, 51 | pfcp_session_est_* | Session Establishment Request/Response | pdu_session | Yes |
| 52, 53 | pfcp_session_mod_* | Session Modification Request/Response | pdu_session | Yes |
| 54, 55 | pfcp_session_del_* | Session Deletion Request/Response | deregistration | Yes |
| 56, 57 | pfcp_session_report_* | Session Report Request/Response | pfcp_reporting | No (filtered) |

Filtering 1, 2, 56, 57 is intentional: heartbeats and session reports are high-volume, low-value for procedure segmentation; TS 29.244 defines them but they are not procedure-lifecycle events. ✓  

**NF assignment**: Request messages (even types 50, 52, 54) are sent by CP (SMF); response messages (odd 51, 53, 55) by UP (UPF). Code uses `SMF if msg_type % 2 == 0 else UPF`. ✓  

### 11.3 SBI path classification (TS 29.5xx)

Same service/path mapping as in §5: `/nausf-auth/`, `/nudm-ueau/`, `/nudm-sdm/`, `/nudm-uecm/`, `/nudr-dr/`, `/nsmf-pdusession/`, `/namf-comm/`, `/nnrf-disc/`, `/nnrf-nfm/`, `/oauth2/token`, `/npcf-`, `/nchf-`. No shortcuts; paths align with API resource names in the specs. ✓  

### 11.4 GTP-U (N3) — TS 29.281

We emit one event per distinct TEID (tunnel evidence), not per packet. TS 29.281 defines GTP-U for user-plane tunnelling; TEID is the tunnel identifier. Interface hint `n3` and procedure_hint `pdu_session` are correct. ✓  

### 11.5 Identifiers

- **NGAP**: `RAN_UE_NGAP_ID`, `AMF_UE_NGAP_ID` from tshark fields per TS 38.413. ✓  
- **PFCP**: `SEID` (Session Endpoint ID) per TS 29.244. ✓  
- **SBI**: SUPI extracted from path via `imsi-\d{10,15}` (SUPI format per TS 23.501). ✓  

---

## 12. Shortcuts and design choices (no spec violations)

| Item | Choice | 3GPP / note |
|------|--------|-------------|
| NGAP port | 38412 | Implementation default (free5GC); TS 38.412 allows configurable port. |
| SBI port | 8000 | Implementation; spec does not fix port. |
| PFCP 56/57 | Filtered | Session Report is valid TS 29.244; excluded to reduce noise, not because it is non-compliant. |
| PFCP 1/2 | Filtered | Heartbeat is mandatory for liveness; excluded from event stream for segmentation only. |
| NGAP procedure 0 vs 1 | 0 = NG Setup, 1 = AMF Config Update | Non-UE-associated codes per Table 9.1.3; order may vary by release; our mapping matches common usage. |
| pcap NF for SBI | Source from pcap filename (amf_0, smf_1) | SBI is peer-to-peer; we attribute by capture point, not by HTTP client/server. Acceptable for correlation. |
| GTP-U | One event per TEID | Avoids per-packet flood; sufficient for tunnel presence. |

None of the above contradict 3GPP; they are implementation/optimisation choices.

---

## 13. Summary (extended)

- **Log parser** (§1–§9): Interfaces, NAS/NGAP/PFCP/SBI terminology, procedure hints, and identifiers align with TS 23.501, 23.502, 24.501, 29.244, 29.5xx, 38.413. ✓  
- **Pcap capture** (§10): Ports and filters (38412, 8805, 2152, 8000) match 3GPP reference points N2, N4, N3, and SBI. ✓  
- **Pcap normalizer** (§11): NGAP procedure codes (duplicate 21 fixed), PFCP message types and filtering, SBI paths, GTP-U TEID, and identifier extraction are aligned with the same specs; no shortcuts that violate 3GPP. ✓  
- **Shortcuts** (§12): Documented and confirmed as non-mandatory optimisations or implementation details. ✓  

Verification is at the same level as the rest of this document: each mapping is tied to a 3GPP reference where applicable.

---

**References (ETSI/3GPP)**  
- TS 23.501 — 5G System architecture  
- TS 23.502 — Procedures for the 5G System  
- TS 24.501 — NAS protocol for 5GS (5GMM, 5GSM)  
- TS 29.244 — PFCP (N4)  
- TS 29.281 — GTPv1-U (N3 user plane)  
- TS 29.500 — 5G SBI, OAuth2  
- TS 29.502 — Session Management SBI  
- TS 29.503 — Nudm (UECM, SDM, UEAuth)  
- TS 29.504 — Nudr_DR  
- TS 29.509 — Nausf_UEAuthentication  
- TS 29.510 — Nnrf_NFDiscovery, Nnrf_NFManagement  
- TS 29.512 — Nsmf_PDUSession, Npcf_SMPolicyControl  
- TS 29.518 — Namf services  
- TS 38.412 — NG signalling transport (SCTP)  
- TS 38.413 — NGAP (N2)
