#!/usr/bin/env python3
"""
Normalize raw NF logs into a unified event stream.

Supports three parser paths:
  1. free5GC v4.x NF logs (AMF, SMF, AUSF, UDM, UDR, NRF, etc.)
  2. free5GC v3.2 legacy NF logs
  3. UERANSIM nr-ue / nr-gnb logs

Event types, procedure_hint and interface_hint align with 3GPP 5GS:
  TS 23.501/23.502 (architecture, procedures), TS 24.501 (5GMM/NAS),
  TS 29.244 (PFCP), TS 29.5xx (SBI: Nudm, Nausf, Nnrf, Namf, Nsmf, Nudr_DR),
  TS 38.413 (NGAP). See docs/3GPP_ALIGNMENT.md for verification.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
from typing import Dict, Iterable, List, Optional, Tuple

# Strip ANSI color/format codes from free5GC log lines (e.g. [36m [0m)
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(line: str) -> str:
    return ANSI_ESCAPE_RE.sub("", line)

# ---------------------------------------------------------------------------
# Timestamp regexes
# ---------------------------------------------------------------------------

# free5GC: 2024-04-29T16:59:34.192410890+02:00  or  2022-07-27T09:47:19Z
FREE5GC_TS_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))"
)

# UERANSIM: [2024-02-11 09:33:22.731]
UERANSIM_TS_RE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})\]"
)

# ---------------------------------------------------------------------------
# free5GC generic log line parser (v4.x and v3.2)
# ---------------------------------------------------------------------------

# v4.x:  2024-... [DEBU][AMF][Gmm][amf_ue_ngap_id:RU:1,AU:1(3GPP)][supi:SUPI:imsi-208930000000001] message
# v3.2:  2022-... [INFO][AMF][GMM][AMF_UE_NGAP_ID:1][SUPI:imsi-2089300007487] message
FREE5GC_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))"
    r"\s+\[(?P<level>\w{4})\]"
    r"\[(?P<nf>\w+)\]"
    r"\[(?P<category>\w+)\]"
    r"(?P<tags>(?:\[[^\]]*\])*)"
    r"\s*(?P<message>.*)$"
)

# ---------------------------------------------------------------------------
# Identifier extraction from bracket tags
# ---------------------------------------------------------------------------

# v4.x format: [amf_ue_ngap_id:RU:1,AU:1(3GPP)]
SUPI_V4_RE = re.compile(r"\[supi:SUPI:(imsi-\d+)\]")
AMF_UE_V4_RE = re.compile(r"\[amf_ue_ngap_id:RU:(\d+),AU:(\d+)\(\w+\)\]")

# v3.2 format: [AMF_UE_NGAP_ID:1]  [SUPI:imsi-NNN]
SUPI_V3_RE = re.compile(r"\[SUPI:(imsi-\d+)\]")
AMF_UE_V3_RE = re.compile(r"\[AMF_UE_NGAP_ID:(\d+)\]")
RAN_UE_V3_RE = re.compile(r"\[RAN_UE_NGAP_ID:(\d+)\]")

# Inline identifiers (SMF style)
SUPI_INLINE_RE = re.compile(r"(?:SUPI|UE)\[(imsi-\d+)\]")
PDU_SESSION_INLINE_RE = re.compile(r"(?:PDUSessionID|pduSessionID|PSI)\[(\d+)\]")
PDU_SESSION_KV_RE = re.compile(r"pdu_session_id[:=]\s*(\d+)", re.IGNORECASE)

# Fallback loose SUPI
SUPI_LOOSE_RE = re.compile(r"(imsi-\d{10,15})")

# UERANSIM UE index: UE[1], UE[2], ... in gNB / UE logs
UERANSIM_UE_IDX_RE = re.compile(r"UE\[(\d+)\]")

# High-frequency noise: data-plane telemetry (UPF periodic usage reports) and
# charging heartbeats (SMF) account for 95%+ of raw log lines but carry zero
# control-plane procedure information.  Filtering them early avoids ~170k
# unnecessary regex checks per S2 run.
NOISE_RE = re.compile(
    r"build MultiUnitUsageFromUsageReport"
    r"|No report need to be charged"
    r"|serveUSAReport"
    r"|handleSessionReportResponse"
    r"|recv event\[TYPE_PERIO_"
    r"|new ticker"
    r"|Certificate verify: x509:"
    r"|XresStar ="
)

# ---------------------------------------------------------------------------
# UERANSIM log line parser
# ---------------------------------------------------------------------------

UERANSIM_LINE_RE = re.compile(
    r"^\[(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})\]"
    r"\s+\[(?P<module>\w+)\]"
    r"\s+\[(?P<level>\w+)\]"
    r"\s+(?P<message>.+)$"
)

# ---------------------------------------------------------------------------
# Event patterns: (compiled_regex, event_type, procedure_hint)
# Ordered so more-specific patterns are checked first.
# ---------------------------------------------------------------------------

EVENT_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # ===================================================================
    # AMF NGAP  (case-insensitive variants for v4.x log text)
    # ===================================================================
    (re.compile(r"Handle InitialUEMessage"), "initial_ue_message", "registration"),
    (re.compile(r"Send Initial Context Setup Request"), "initial_context_setup", "registration"),
    (re.compile(r"Send PDU\s*Session\s*Resource\s*Setup\s*Request"), "pdu_resource_setup", "pdu_session"),
    (re.compile(r"Handle PDUSessionResourceSetupResponse"), "pdu_resource_setup_resp", "pdu_session"),
    (re.compile(r"Send UE Context Release Command"), "ue_context_release_cmd", "deregistration"),
    (re.compile(r"Handle UE Context Release Complete"), "ue_context_release_complete", "deregistration"),
    (re.compile(r"Send Downlink (?:NAS|Nas) Transport"), "dl_nas_transport", "nas_transport"),
    (re.compile(r"Handle Uplink(?:NAS|Nas)Transport"), "ul_nas_transport_ngap", "nas_transport"),
    (re.compile(r"Handle N1N2 Message Transfer Request"), "n1n2_transfer", "pdu_session"),
    (re.compile(r"Not comprehended IE"), "ngap_ie_warning", "registration"),

    # ===================================================================
    # AMF GMM — Registration
    # ===================================================================
    (re.compile(r"Handle Registration Request"), "registration_request", "registration"),
    (re.compile(r"Handle InitialRegistration"), "initial_registration", "registration"),
    (re.compile(r"Send Registration Accept|RegistrationAccept sent"), "registration_accept", "registration"),
    (re.compile(r"Handle Registration Complete"), "registration_complete", "registration"),
    (re.compile(r"Send Registration Reject"), "registration_reject", "registration"),
    (re.compile(r"RegistrationType:\s*Initial Registration"), "registration_type_initial", "registration"),
    (re.compile(r"Send Configuration Update Command"), "config_update_cmd", "registration"),
    (re.compile(r"MobileIdentity5GS:\s*SUCI"), "suci_identity", "registration"),
    (re.compile(r"nsiInformation is still nil"), "nsi_fallback_nrf", "registration"),
    (re.compile(r"RequestedNssai.*ServingSnssai"), "nssai_selection", "registration"),

    # ===================================================================
    # AMF GMM — Identity
    # ===================================================================
    (re.compile(r"Send Identity Request"), "identity_request", "registration"),
    (re.compile(r"Handle Identity Response"), "identity_response", "registration"),

    # ===================================================================
    # AMF GMM — Authentication  (specific-first ordering)
    # ===================================================================
    (re.compile(r"Authentication procedure failed"), "auth_procedure_failed", "registration"),
    (re.compile(r"Authentication procedure"), "auth_procedure_start", "registration"),
    (re.compile(r"Send Authentication Request"), "auth_request", "registration"),
    (re.compile(r"Handle Authentication Response"), "auth_response", "registration"),
    (re.compile(r"Handle Authentication Failure"), "auth_failure", "registration"),
    (re.compile(r"Handle Authentication Error"), "auth_error", "registration"),
    (re.compile(r"Send Authentication Reject"), "auth_reject", "registration"),
    (re.compile(r"Nausf_UEAU Authenticate Request (?:Failed|Error)"), "auth_sbi_failure", "registration"),
    (re.compile(r"UE Security Context is not Available"), "ue_security_ctx_missing", "registration"),

    # ===================================================================
    # AMF GMM — Security
    # ===================================================================
    (re.compile(r"Send Security Mode Command"), "security_mode_command", "registration"),
    (re.compile(r"Handle Security Mode Complete"), "security_mode_complete", "registration"),

    # ===================================================================
    # AMF GMM — Timers
    # ===================================================================
    (re.compile(r"Start T\d+ timer"), "timer_start", "registration"),
    (re.compile(r"Stop T\d+ timer"), "timer_stop", "registration"),

    # ===================================================================
    # AMF GMM — PDU Session
    # ===================================================================
    (re.compile(r"Handle UL NAS Transport"), "ul_nas_transport", "pdu_session"),
    (re.compile(r"Transport 5GSM Message to SMF"), "transport_5gsm", "pdu_session"),
    (re.compile(r"create smContext\[pduSessionID:\s*\d+\]\s*Success"), "sm_context_create_success", "pdu_session"),
    (re.compile(r"CreateSmContextRequest Error"), "sm_context_create_error", "pdu_session"),
    (re.compile(r"Select SMF"), "select_smf", "pdu_session"),

    # ===================================================================
    # AMF GMM — Deregistration
    # ===================================================================
    (re.compile(r"Handle Deregistration Request"), "deregistration_request", "deregistration"),
    (re.compile(r"Send Deregistration Accept"), "deregistration_accept", "deregistration"),

    # ===================================================================
    # AMF GIN — SBI HTTP access
    # ===================================================================
    (re.compile(r"\|\s*(?:POST|PUT)\s*\|.*/namf-comm/"), "amf_sbi_comm", "pdu_session"),

    # ===================================================================
    # LIB FSM state transitions
    # ===================================================================
    (re.compile(r"Handle event\[(.+?)\], transition from \[(\w+)\] to \[(\w+)\]"), "fsm_transition", "fsm"),

    # ===================================================================
    # AUSF
    # ===================================================================
    (re.compile(r"HandleUeAuthPostRequest"), "ausf_auth_post", "authentication_sub"),
    (re.compile(r"HandleAuth5gAka(?:Comfirm|Confirm)Request|Auth5gAkaComfirmRequest"), "ausf_aka_confirm", "authentication_sub"),
    (re.compile(r"5G AKA confirmation succeeded"), "ausf_aka_confirm_ok", "authentication_sub"),
    (re.compile(r"Serving network authorized"), "ausf_net_authorized", "authentication_sub"),
    (re.compile(r"Use 5G AKA auth method"), "ausf_5g_aka_selected", "authentication_sub"),
    (re.compile(r"GenerateAuthDataApi error"), "ausf_generate_auth_error", "authentication_sub"),

    # ===================================================================
    # AUSF GIN — SBI HTTP access
    # ===================================================================
    (re.compile(r"\|\s*(?:POST|PUT)\s*\|.*/nausf-auth/"), "ausf_sbi_auth", "authentication_sub"),

    # ===================================================================
    # UDM
    # ===================================================================
    (re.compile(r"HandleGenerateAuthDataRequest|Handle GenerateAuthDataRequest"), "udm_generate_auth", "authentication_sub"),
    (re.compile(r"HandleConfirmAuthDataRequest|Handle ConfirmAuthDataRequest"), "udm_confirm_auth", "authentication_sub"),
    (re.compile(r"Handle CreateAMFContext"), "udm_create_amf_ctx", "registration"),
    (re.compile(r"HandleGetAmData|Handle GetAmData"), "udm_get_am_data", "registration"),
    (re.compile(r"HandleGetSmfSelectData|Handle GetSmfSelectData"), "udm_get_smf_select", "registration"),
    (re.compile(r"HandleGetSmData|Handle GetSmData"), "udm_get_sm_data", "pdu_session"),
    (re.compile(r"Handle RegistrationAmf3gppAccess"), "udm_reg_amf_ctx", "registration"),
    (re.compile(r"Handle GetNssai"), "udm_get_nssai", "registration"),
    (re.compile(r"Handle GetUeContextInSmfData"), "udm_get_ue_ctx_smf", "pdu_session"),
    (re.compile(r"suciPart:|SuciToSupi"), "udm_suci_deconcealment", "authentication_sub"),
    (re.compile(r"SUPI type is IMSI"), "udm_supi_type_imsi", "authentication_sub"),
    (re.compile(r"decryption MAC match"), "udm_decryption_ok", "authentication_sub"),
    (re.compile(r"HandleSubscribe|Handle Subscribe"), "udm_subscribe", "registration"),
    (re.compile(r"HandleUnsubscribe|Handle Unsubscribe"), "udm_unsubscribe", "deregistration"),
    (re.compile(r"Error on QueryAuthSubsData|Return from UDR QueryAuthSubsData error"), "udm_auth_query_error", "authentication_sub"),

    # ===================================================================
    # UDM GIN — SBI HTTP access
    # ===================================================================
    (re.compile(r"\|\s*(?:POST|PUT)\s*\|.*/nudm-ueau/"), "udm_sbi_auth", "authentication_sub"),
    (re.compile(r"\|\s*(?:GET|PUT)\s*\|.*/nudm-sdm/"), "udm_sbi_sdm", "registration"),
    (re.compile(r"\|\s*(?:GET|PUT)\s*\|.*/nudm-uecm/"), "udm_sbi_uecm", "registration"),

    # ===================================================================
    # UDR  (v3.x Handle… + v4.x DataRepo/GIN)
    # ===================================================================
    (re.compile(r"HandleQueryAuthSubsData|Handle QueryAuthSubsData"), "udr_query_auth", "authentication_sub"),
    (re.compile(r"HandleCreateAmfContext|Handle CreateAmfContext"), "udr_create_amf_ctx", "registration"),
    (re.compile(r"QueryAmDataProcedure"), "udr_query_am_data", "registration"),

    # ===================================================================
    # UDR GIN — SBI HTTP access  (URL-path scoped to /nudr-dr/)
    # ===================================================================
    (re.compile(r"\|\s*(?:GET|POST|PUT|PATCH)\s*\|.*/nudr-dr/.*authentication-data"), "udr_sbi_auth_data", "authentication_sub"),
    (re.compile(r"\|\s*(?:GET|POST|PUT|PATCH)\s*\|.*/nudr-dr/.*provisioned-data/am-data"), "udr_sbi_am_data", "registration"),
    (re.compile(r"\|\s*(?:GET|POST|PUT|PATCH)\s*\|.*/nudr-dr/.*provisioned-data/sm"), "udr_sbi_sm_data", "pdu_session"),
    (re.compile(r"\|\s*(?:GET|POST|PUT|PATCH)\s*\|.*/nudr-dr/.*context-data"), "udr_sbi_context", "registration"),
    (re.compile(r"\|\s*(?:GET|POST|PUT|PATCH)\s*\|.*/nudr-dr/.*policy-data"), "udr_sbi_policy", "pdu_session"),
    (re.compile(r"\|\s*(?:GET|POST|PUT|PATCH)\s*\|.*/nudr-dr/.*sdm-subscriptions"), "udr_sbi_sdm_sub", "registration"),
    (re.compile(r"\|\s*(?:GET|POST|PUT|PATCH)\s*\|.*/nudr-dr/.*(?:influenceData|application-data)"), "udr_sbi_influence", "pdu_session"),

    # ===================================================================
    # SMF  (specific-first for overlapping "Send Charging …" variants)
    # ===================================================================
    (re.compile(r"Receive Create SM Context Request"), "smf_receive_create", "pdu_session"),
    (re.compile(r"Receive Update SM Context Request"), "smf_receive_update", "pdu_session"),
    (re.compile(r"Receive Release SM Context Request"), "smf_receive_release", "deregistration"),
    (re.compile(r"HandlePDUSessionSMContextCreate|In HandlePDUSessionSMContextCreate"), "sm_context_create", "pdu_session"),
    (re.compile(r"HandlePDUSessionEstablishmentRequest|In HandlePDUSessionEstablishmentRequest"), "pdu_session_est_req", "pdu_session"),
    (re.compile(r"HandlePDUSessionSMContextUpdate"), "sm_context_update", "pdu_session"),
    (re.compile(r"HandlePDUSessionSMContextRelease|In HandlePDUSessionSMContextRelease"), "sm_context_release", "deregistration"),
    (re.compile(r"Selected UPF"), "smf_selected_upf", "pdu_session"),
    (re.compile(r"Allocated (?:UE IP address|PDUAdress)"), "smf_ip_allocated", "pdu_session"),
    (re.compile(r"Send(?:ing)? PFCP Session Establishment Request"), "pfcp_session_est_req", "pdu_session"),
    (re.compile(r"Received PFCP Session Establishment Accepted Response"), "pfcp_session_est_resp", "pdu_session"),
    (re.compile(r"Send(?:ing)? PFCP Session Modification Request"), "pfcp_session_mod_req", "pdu_session"),
    (re.compile(r"Received PFCP Session Modification Accepted Response"), "pfcp_session_mod_resp", "pdu_session"),
    (re.compile(r"Send(?:ing)? PFCP Session Deletion Request"), "pfcp_session_del_req", "deregistration"),
    (re.compile(r"Received PFCP Session Deletion Accepted Response"), "pfcp_session_del_resp", "deregistration"),
    (re.compile(r"SDM Subscription Successful"), "smf_sdm_subscription", "pdu_session"),
    (re.compile(r"CHF Selection for SMContext"), "smf_chf_selection", "pdu_session"),
    (re.compile(r"Send Charging Data Request\[Termination\]"), "smf_charging_terminate", "deregistration"),
    (re.compile(r"Send Charging Data Request"), "smf_charging_req", "pdu_session"),
    (re.compile(r"Install PCCRule"), "smf_pcc_rule_install", "pdu_session"),
    (re.compile(r"Send NF Discovery Serving UDM"), "smf_nf_disc_udm", "pdu_session"),
    (re.compile(r"SendNFDiscoveryServingAMF"), "smf_nf_disc_amf", "pdu_session"),
    (re.compile(r"Release IP"), "smf_ip_released", "deregistration"),
    (re.compile(r"No Default Data Path"), "smf_no_default_path", "pdu_session"),
    (re.compile(r"Has default path"), "smf_has_default_path", "pdu_session"),
    (re.compile(r"N1N2MessageTransfer.*failed"), "smf_n1n2_transfer_fail", "pdu_session"),
    (re.compile(r"Unexpected state"), "smf_unexpected_state", "pdu_session"),

    # ===================================================================
    # SMF GIN — SBI HTTP access
    # ===================================================================
    (re.compile(r"\|\s*(?:POST|PUT)\s*\|.*/nsmf-pdusession/"), "smf_sbi_pdu_session", "pdu_session"),

    # ===================================================================
    # NRF
    # ===================================================================
    (re.compile(r"Handle NFDiscoveryRequest"), "nrf_discovery", "sbi_discovery"),
    (re.compile(r"Handle NFRegisterRequest"), "nrf_register", "nf_management"),
    (re.compile(r"In HTTPAccessTokenRequest"), "nrf_access_token_req", "sbi_auth"),

    # ===================================================================
    # NRF GIN — SBI HTTP access
    # ===================================================================
    (re.compile(r"\|\s*PUT\s*\|.*/nnrf-nfm/v1/nf-instances"), "nrf_sbi_nf_register", "nf_management"),
    (re.compile(r"\|\s*GET\s*\|.*/nnrf-disc/v1/nf-instances"), "nrf_sbi_nf_discovery", "sbi_discovery"),
    (re.compile(r"\|\s*POST\s*\|.*/oauth2/token"), "nrf_sbi_oauth_token", "sbi_auth"),

    # ===================================================================
    # UPF PFCP
    # ===================================================================
    (re.compile(r"handleAssociationSetupRequest"), "upf_assoc_setup", "pfcp_association"),
    (re.compile(r"New node"), "upf_new_node", "pfcp_association"),
    (re.compile(r"handleSessionEstablishmentRequest"), "upf_session_est_req", "pdu_session"),
    (re.compile(r"New session"), "upf_session_created", "pdu_session"),
    (re.compile(r"handleSessionModificationRequest"), "upf_session_mod_req", "pdu_session"),
    (re.compile(r"handleSessionDeletionRequest"), "upf_session_del_req", "deregistration"),
    (re.compile(r"sess deleted"), "upf_session_deleted", "deregistration"),

    # ===================================================================
    # UERANSIM gNB — NGAP / RRC / SCTP
    # ===================================================================
    (re.compile(r"NG Setup procedure is successful"), "gnb_ng_setup", "gnb_setup"),
    (re.compile(r"SCTP connection established"), "gnb_sctp_connected", "gnb_setup"),
    (re.compile(r"RRC Setup for UE"), "gnb_rrc_setup", "registration"),
    (re.compile(r"Initial NAS message received from UE"), "gnb_initial_nas", "registration"),
    (re.compile(r"Initial Context Setup Request received"), "gnb_initial_ctx_setup", "registration"),
    (re.compile(r"PDU session resource\(s\) setup for UE"), "gnb_pdu_session_setup", "pdu_session"),
    (re.compile(r"UE Context Release Command received"), "gnb_ue_release_cmd", "deregistration"),
    (re.compile(r"Releasing RRC connection for UE"), "gnb_rrc_release", "deregistration"),
    (re.compile(r"UE\[\d+\] new signal detected"), "gnb_ue_detected", "registration"),

    # ===================================================================
    # UERANSIM UE — Registration
    # ===================================================================
    (re.compile(r"Sending Initial Registration"), "ue_sending_reg", "registration"),
    (re.compile(r"UE switches to state \[MM-REGISTER-INITIATED\]"), "ue_reg_initiated", "registration"),
    (re.compile(r"Authentication Request received"), "ue_auth_request", "registration"),
    (re.compile(r"Security Mode Command received"), "ue_sec_mode_cmd", "registration"),
    (re.compile(r"Registration accept received"), "ue_reg_accept", "registration"),
    (re.compile(r"Sending Registration Complete"), "ue_reg_complete", "registration"),
    (re.compile(r"Initial Registration is successful"), "ue_reg_success", "registration"),
    (re.compile(r"Initial Registration failed"), "ue_reg_failed", "registration"),

    # ===================================================================
    # UERANSIM UE — PDU Session
    # ===================================================================
    (re.compile(r"Sending PDU Session Establishment Request"), "ue_pdu_send", "pdu_session"),
    (re.compile(r"PDU Session establishment is successful PSI\[(\d+)\]"), "ue_pdu_success", "pdu_session"),
    (re.compile(r"PDU Session Establishment Reject"), "ue_pdu_reject", "pdu_session"),

    # ===================================================================
    # UERANSIM UE — State changes
    # ===================================================================
    (re.compile(r"UE switches to state \[([A-Z\-/]+)\]"), "ue_state_change", "ue_state"),
    (re.compile(r"RRC connection established"), "ue_rrc_connected", "registration"),
    (re.compile(r"Selected cell plmn"), "ue_cell_selected", "registration"),

    # ===================================================================
    # UERANSIM UE — Deregistration
    # ===================================================================
    (re.compile(r"UE switches to state \[MM-DEREGISTERED/NA\]"), "ue_deregistered", "deregistration"),

    # ===================================================================
    # Generic fallbacks (checked last)
    # ===================================================================
    (re.compile(r"timeout|retransmit", re.IGNORECASE), "retry_or_timeout", "retry_flow"),
    (re.compile(r"handover", re.IGNORECASE), "handover_event", "handover"),
]


def parse_free5gc_line(line: str) -> Optional[Dict]:
    """Parse a free5GC NF log line into structured fields."""
    m = FREE5GC_LINE_RE.match(line)
    if not m:
        return None
    tags_str = m.group("tags")
    return {
        "timestamp": m.group("timestamp"),
        "level": m.group("level"),
        "nf": m.group("nf"),
        "category": m.group("category"),
        "tags": tags_str,
        "message": m.group("message"),
        "format": "free5gc",
    }


def parse_ueransim_line(line: str) -> Optional[Dict]:
    """Parse a UERANSIM log line into structured fields."""
    m = UERANSIM_LINE_RE.match(line)
    if not m:
        return None
    raw_ts = m.group("timestamp").strip()
    iso_ts = raw_ts.replace(" ", "T") + "Z"
    return {
        "timestamp": iso_ts,
        "level": m.group("level"),
        "nf": "UERANSIM",
        "category": m.group("module"),
        "tags": "",
        "message": m.group("message"),
        "format": "ueransim",
    }


def parse_line(line: str) -> Optional[Dict]:
    """Try each parser in order."""
    parsed = parse_free5gc_line(line)
    if parsed:
        return parsed
    parsed = parse_ueransim_line(line)
    if parsed:
        return parsed
    return None


def extract_ids(line: str, tags: str) -> Dict[str, Optional[str]]:
    """Extract all correlation identifiers from tags + message text."""
    supi = None
    amf_ue = None
    ran_ue = None
    pdu_session = None

    m = SUPI_V4_RE.search(tags)
    if m:
        supi = m.group(1)
    if not supi:
        m = SUPI_V3_RE.search(tags)
        if m:
            supi = m.group(1)
    if not supi:
        m = SUPI_INLINE_RE.search(line)
        if m:
            supi = m.group(1)
    if not supi:
        m = SUPI_LOOSE_RE.search(line)
        if m:
            supi = m.group(1)

    m = AMF_UE_V4_RE.search(tags)
    if m:
        ran_ue = m.group(1)
        amf_ue = m.group(2)
    else:
        m = AMF_UE_V3_RE.search(tags)
        if m:
            amf_ue = m.group(1)
        m = RAN_UE_V3_RE.search(tags)
        if m:
            ran_ue = m.group(1)

    if not ran_ue:
        m = UERANSIM_UE_IDX_RE.search(line)
        if m:
            ran_ue = m.group(1)

    m = PDU_SESSION_INLINE_RE.search(line)
    if m:
        pdu_session = m.group(1)
    if not pdu_session:
        m = PDU_SESSION_KV_RE.search(line)
        if m:
            pdu_session = m.group(1)

    return {
        "supi": supi,
        "ran_ue_ngap_id": ran_ue,
        "amf_ue_ngap_id": amf_ue,
        "pdu_session_id": pdu_session,
    }


def classify_event(message: str) -> Optional[Dict[str, str]]:
    """Match a message string against known event patterns."""
    for pattern, event_type, procedure in EVENT_PATTERNS:
        if pattern.search(message):
            return {"event_type": event_type, "procedure_hint": procedure}
    return None


def strongest_ue_key(ids: Dict[str, Optional[str]]) -> str:
    if ids.get("supi"):
        return ids["supi"] or "unknown"
    if ids.get("amf_ue_ngap_id"):
        return f"amfue-{ids['amf_ue_ngap_id']}"
    if ids.get("ran_ue_ngap_id"):
        return f"ranue-{ids['ran_ue_ngap_id']}"
    return "unknown"


def read_lines(path: pathlib.Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = strip_ansi(line.strip())
            if line:
                yield line


def detect_interface_hint(parsed: Dict, message: str) -> str:
    """Infer the 3GPP interface from NF name and log category."""
    cat_lower = parsed.get("category", "").lower()
    if cat_lower in ("ngap", "n2", "sctp"):
        return "n2"
    if cat_lower in ("pfcp", "n4", "perio"):
        return "n4"
    if cat_lower in ("gin", "sbi", "http", "consumer", "datarepo",
                      "ueau", "ueauth", "charging", "disc"):
        return "sbi"
    if cat_lower in ("nas", "gmm", "gsm", "pdusess", "ctx"):
        return "nas"
    if cat_lower in ("rrc",):
        return "rrc"
    if cat_lower in ("gtp5g", "buff"):
        return "n3"
    if "http" in message.lower() or "/n" in message.lower():
        return "sbi"
    return "unknown"


def normalize_log_file(
    path: pathlib.Path, source_container: str, start_event_id: int = 0
) -> Tuple[List[Dict], Dict]:
    """
    Parse a log file and return (events, coverage_stats).
    coverage_stats = {"total_lines": N, "matched_lines": M, "unmatched_lines": U}
    """
    events: List[Dict] = []
    event_id = start_event_id
    total_lines = 0
    parsed_lines = 0
    noise_filtered = 0
    matched_lines = 0

    for line in read_lines(path):
        total_lines += 1
        parsed = parse_line(line)
        if not parsed:
            continue
        parsed_lines += 1

        if NOISE_RE.search(parsed["message"]):
            noise_filtered += 1
            continue

        classification = classify_event(parsed["message"])
        if not classification:
            continue

        matched_lines += 1
        ids = extract_ids(line, parsed.get("tags", ""))
        event = {
            "event_id": event_id,
            "timestamp": parsed["timestamp"],
            "source": source_container,
            "nf": parsed["nf"],
            "category": parsed["category"],
            "level": parsed["level"],
            "interface_hint": detect_interface_hint(parsed, parsed["message"]),
            "event_type": classification["event_type"],
            "procedure_hint": classification["procedure_hint"],
            "ue_key": strongest_ue_key(ids),
            "ids": ids,
            "raw_line": line[:500],
        }
        events.append(event)
        event_id += 1

    useful_lines = parsed_lines - noise_filtered
    coverage = {
        "source": source_container,
        "total_lines": total_lines,
        "parsed_lines": parsed_lines,
        "noise_filtered": noise_filtered,
        "matched_lines": matched_lines,
        "unmatched_lines": useful_lines - matched_lines,
        "unparseable_lines": total_lines - parsed_lines,
        "match_rate": round(matched_lines / total_lines, 4) if total_lines > 0 else 0.0,
        "effective_match_rate": round(
            matched_lines / max(1, useful_lines), 4
        ),
    }
    return events, coverage


def apply_drop_fields(events: List[Dict], drop_fields: List[str]) -> None:
    """Simulate partial observability by zeroing out specified ID fields."""
    for event in events:
        for field in drop_fields:
            if field == "supi":
                event["ids"]["supi"] = None
                if event["ue_key"].startswith("imsi-"):
                    event["ue_key"] = strongest_ue_key(event["ids"])
            elif field in event["ids"]:
                event["ids"][field] = None
                if field == "amf_ue_ngap_id" and event["ue_key"].startswith("amfue-"):
                    event["ue_key"] = strongest_ue_key(event["ids"])
                if field == "ran_ue_ngap_id" and event["ue_key"].startswith("ranue-"):
                    event["ue_key"] = strongest_ue_key(event["ids"])


def load_drop_fields(run_dir: pathlib.Path) -> List[str]:
    meta_path = run_dir / "run_metadata.json"
    if not meta_path.exists():
        return []
    with meta_path.open("r", encoding="utf-8") as f:
        meta = json.load(f)
    return meta.get("scenario", {}).get("capture", {}).get("normalization_drop_fields", [])


def write_jsonl(path: pathlib.Path, events: List[Dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize raw free5gc/UERANSIM logs into events.jsonl.")
    parser.add_argument("--run-dir", required=True, help="Path to experiments/runs/<run_id>.")
    args = parser.parse_args()

    run_dir = pathlib.Path(args.run_dir).resolve()
    logs_dir = run_dir / "raw" / "logs"
    out_dir = run_dir / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not logs_dir.exists():
        raise SystemExit(f"Missing logs directory: {logs_dir}")

    all_events: List[Dict] = []
    all_coverage: List[Dict] = []
    next_event_id = 0

    for log_path in sorted(logs_dir.glob("*.log")):
        container = log_path.stem
        events, coverage = normalize_log_file(
            log_path, source_container=container, start_event_id=next_event_id
        )
        all_events.extend(events)
        all_coverage.append(coverage)
        next_event_id += len(events)
        print(
            f"  {container}: {coverage['matched_lines']}/{coverage['total_lines']} "
            f"lines matched ({coverage['match_rate']:.1%})"
            f"  [noise={coverage['noise_filtered']}, "
            f"effective={coverage['effective_match_rate']:.1%}]"
        )

    pcap_events_path = out_dir / "events_pcap.jsonl"
    pcap_event_count = 0
    if pcap_events_path.exists():
        pcap_events: List[Dict] = []
        with pcap_events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    ev = json.loads(line)
                    ev["event_id"] = next_event_id
                    next_event_id += 1
                    pcap_events.append(ev)
        all_events.extend(pcap_events)
        pcap_event_count = len(pcap_events)
        print(f"  [pcap] Merged {pcap_event_count} pcap events from {pcap_events_path.name}")

    all_events.sort(key=lambda x: x["timestamp"])

    drop_fields = load_drop_fields(run_dir)
    if drop_fields:
        apply_drop_fields(all_events, drop_fields)
        print(f"Applied observability drop: {drop_fields}")

    write_jsonl(out_dir / "events.jsonl", all_events)

    total_matched = sum(c["matched_lines"] for c in all_coverage)
    total_lines = sum(c["total_lines"] for c in all_coverage)
    aggregate_coverage = {
        "event_count": len(all_events),
        "log_events": len(all_events) - pcap_event_count,
        "pcap_events": pcap_event_count,
        "total_lines_all_logs": total_lines,
        "total_matched_lines": total_matched,
        "aggregate_match_rate": round(total_matched / total_lines, 4) if total_lines > 0 else 0.0,
        "per_source": all_coverage,
        "drop_fields_applied": drop_fields,
        "sources": sorted({e["source"] for e in all_events}),
    }

    with (out_dir / "parser_coverage.json").open("w", encoding="utf-8") as f:
        json.dump(aggregate_coverage, f, indent=2)

    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(
            {
                "event_count": len(all_events),
                "log_events": len(all_events) - pcap_event_count,
                "pcap_events": pcap_event_count,
                "drop_fields_applied": drop_fields,
                "sources": sorted({e["source"] for e in all_events}),
                "aggregate_match_rate": aggregate_coverage["aggregate_match_rate"],
            },
            f,
            indent=2,
        )

    print(f"Wrote {len(all_events)} events to {out_dir / 'events.jsonl'}")
    print(f"  (log={len(all_events) - pcap_event_count}, pcap={pcap_event_count})")
    print(f"Parser coverage report: {out_dir / 'parser_coverage.json'}")
    print(f"Aggregate match rate: {aggregate_coverage['aggregate_match_rate']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
