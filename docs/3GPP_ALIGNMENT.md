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

**References (ETSI/3GPP)**  
- TS 23.501 — 5G System architecture  
- TS 23.502 — Procedures for the 5G System  
- TS 24.501 — NAS protocol for 5GS (5GMM, 5GSM)  
- TS 29.244 — PFCP (N4)  
- TS 29.500 — 5G SBI, OAuth2  
- TS 29.502 — Session Management SBI  
- TS 29.503 — Nudm (UECM, SDM, UEAuth)  
- TS 29.504 — Nudr_DR  
- TS 29.509 — Nausf_UEAuthentication  
- TS 29.510 — Nnrf_NFDiscovery, Nnrf_NFManagement  
- TS 29.512 — Nsmf_PDUSession, Npcf_SMPolicyControl  
- TS 29.518 — Namf services  
- TS 38.413 — NGAP (N2)
