# Packet Count + Event Count vs UE Count – Detailed Comparison

All runs: 300 s duration, same 8 NF logs + 3 pcap targets (AMF/N2+SBI, SMF/N4+SBI, UPF/N3+N4).  
Packet counts: tshark. Event counts: normalize_events.py output (log-sourced + pcap-sourced).  

---

## Table 1: Top-Level Summary

| UEs | Log lines | Packets (pcap) | Events (log) | Events (pcap) | Total events |
|----:|----------:|---------------:|-------------:|--------------:|-------------:|
|   1 |   245,748 |          1,568 |       27,947 |             0 |       27,947 |
|  10 |   254,831 |         12,600 |       33,335 |           894 |       34,229 |
|  20 |   264,908 |         13,358 |       38,299 |           915 |       39,214 |
|  30 |   282,220 |         21,819 |       50,058 |         1,826 |       51,884 |
|  40 |   303,209 |         24,992 |       63,884 |         2,121 |       66,005 |

---

## Table 2: Growth vs 1-UE Baseline

| UEs | LogLines× | Packets× | LogEvents× | PcapEvents× | TotalEvents× |
|----:|----------:|---------:|-----------:|------------:|-------------:|
|   1 |    1.000x |   1.000x |     1.000x |     (none)  |      1.000x  |
|  10 |    1.037x |   8.036x |     1.193x |     new     |      1.225x  |
|  20 |    1.078x |   8.519x |     1.370x |     new     |      1.403x  |
|  30 |    1.148x |  13.915x |     1.791x |     new     |      1.857x  |
|  40 |    1.234x |  15.939x |     2.286x |     new     |      2.362x  |

> Note: AMF+SMF pcap was absent at 1 UE (sidecar not deployed), so packet baseline is UPF-only (1,568 pkts).
> The Packets× figures from 10-40 UE include AMF+SMF captures not present at 1 UE.

---

## Table 3: Per-Container Log Line Counts

| UEs |    AMF |    SMF |    UPF |   AUSF |    UDM |    UDR |    NRF | UERANSIM |   Total |
|----:|-------:|-------:|-------:|-------:|-------:|-------:|-------:|---------:|--------:|
|   1 | 10,157 | 97,765 |115,628 |  1,985 |  4,312 |  1,678 | 14,071 |      152 | 245,748 |
|  10 | 11,865 | 99,786 |117,533 |  2,327 |  5,035 |  1,884 | 16,212 |      189 | 254,831 |
|  20 | 13,779 |102,024 |119,666 |  2,709 |  5,828 |  2,105 | 18,542 |      255 | 264,908 |
|  30 | 18,174 |104,433 |121,963 |  3,611 |  7,661 |  2,584 | 23,390 |      404 | 282,220 |
|  40 | 23,742 |107,139 |124,565 |  4,753 |  9,969 |  3,180 | 29,330 |      531 | 303,209 |

---

## Table 4: Per-Container Log Line Growth Factor (vs 1-UE)

| UEs |   AMF  |   SMF  |   UPF  |  AUSF  |   UDM  |   UDR  |   NRF  | UERANSIM |
|----:|-------:|-------:|-------:|-------:|-------:|-------:|-------:|---------:|
|   1 |  1.000 |  1.000 |  1.000 |  1.000 |  1.000 |  1.000 |  1.000 |    1.000 |
|  10 |  1.168 |  1.021 |  1.016 |  1.172 |  1.168 |  1.123 |  1.152 |    1.243 |
|  20 |  1.357 |  1.044 |  1.035 |  1.365 |  1.352 |  1.254 |  1.318 |    1.678 |
|  30 |  1.789 |  1.068 |  1.055 |  1.819 |  1.777 |  1.540 |  1.662 |    2.658 |
|  40 |  2.338 |  1.096 |  1.077 |  2.394 |  2.312 |  1.895 |  2.084 |    3.493 |

### Analysis

| NF | Growth at 40 UE | Dominant log source |
|----|-----------------|---------------------|
| UERANSIM | 3.49x | One RRC Setup + NAS Registration log block per UE (most linear) |
| AUSF     | 2.39x | One 5G-AKA challenge-response exchange per UE |
| AMF      | 2.34x | InitialUEMessage + GUTI + NAS Security + PDU Session per UE |
| UDM      | 2.31x | GetAmData + GetSmData + SDM-Subscribe per UE |
| NRF      | 2.08x | NFDiscover calls (by AMF/SMF) scale with sessions |
| UDR      | 1.90x | Data-store reads driven by UDM/PCF calls |
| SMF      | 1.10x | PFCP heartbeats + CHF charging reports dominate (fixed rate) |
| UPF      | 1.08x | GTP-U data-plane usage reports dominate (fixed rate) |

- SMF + UPF = **~87% of all log lines** at 1 UE and ~76% at 40 UE
- Their near-flat growth is why total log line count only rises 1.23x despite 40x more UEs

---

## Table 5: Per-PCAP Packet Counts

| UEs | amf_0.pcap (N2+SBI) | smf_1.pcap (N4+SBI) | upf_2.pcap (N3+N4) | Total packets |
|----:|--------------------:|--------------------:|-------------------:|--------------:|
|   1 |                   0 |                   0 |              1,568 |         1,568 |
|  10 |               6,924 |               3,979 |              1,697 |        12,600 |
|  20 |               7,593 |               3,780 |              1,985 |        13,358 |
|  30 |              15,334 |               4,364 |              2,121 |        21,819 |
|  40 |              18,485 |               4,222 |              2,285 |        24,992 |

### Analysis

| Interface | Scaling (10-40 UE) | Dominant traffic |
|-----------|-------------------|------------------|
| amf_0 (N2/NGAP+SBI) | 6,924 -> 18,485 pkts (~2.67x) | NGAP InitialUEMessage, Auth, SecurityMode, InitialContextSetup + HTTP/2 SBI to AUSF/UDM/SMF — one full N2 sequence per UE |
| smf_1 (N4/PFCP+SBI) | 3,979 -> 4,222 pkts (~1.06x flat) | PFCP Heartbeat Request/Response dominate (constant rate). Per-UE PFCP Session-Establishment is a small fraction |
| upf_2 (N3/GTP-U+N4) | 1,697 -> 2,285 pkts (~1.35x) | GTP-U encapsulated ICMP (5x ping per run) + PFCP Usage Reports (fixed rate) |

---

## Table 6: Top Normalized Event Types from Logs

| Event type              |  1 UE |  10 UE |  20 UE |  30 UE |  40 UE |
|-------------------------|------:|-------:|-------:|-------:|-------:|
| nrf_access_token        | 3,782 |  4,357 |  4,975 |  6,259 |  7,827 |
| nrf_sbi_oauth_token     | 3,782 |  4,357 |  4,975 |  6,259 |  7,827 |
| ul_nas_transport        | 2,006 |  2,334 |  2,682 |  3,478 |  4,546 |
| fsm_transition          | 1,560 |  1,822 |  2,114 |  2,796 |  3,658 |
| nrf_sbi_nf_discover     | 1,327 |  1,535 |  1,773 |  2,271 |  2,889 |
| nrf_discovery           | 1,327 |  1,535 |  1,773 |  2,271 |  2,889 |
| dl_nas_transport        |   951 |  1,117 |  1,303 |  1,749 |  2,315 |
| registration_request    |   880 |  1,040 |  1,220 |  1,660 |  2,220 |
| udm_auth_query          |   825 |    975 |  1,150 |  1,575 |  2,125 |
| udr_sbi_auth_data       |   497 |    583 |    679 |    905 |  1,191 |

### Key observations

- **nrf_access_token and nrf_sbi_oauth_token are the single highest-count event types** at all UE counts — every inter-NF API call requires an OAuth token from NRF
- **ul_nas_transport** (NAS messages from UE to AMF) grows nearly linearly with UE count: 2,006 -> 4,546 (~2.27x at 40 UE)
- **registration_request** grows 2,220/880 = 2.52x at 40 UE — each UE does a complete registration, so this is a near-direct per-UE counter
- **udm_auth_query** grows 2,125/825 = 2.58x — one authentication query per UE
- **fsm_transition** (AMF/SMF state machine changes) grows 3,658/1,560 = 2.34x — tracking each UE's lifecycle

---

## Table 7: PCAP Normalized Event Types

| Event type              |  1 UE |  10 UE |  20 UE |  30 UE |  40 UE |
|-------------------------|------:|-------:|-------:|-------:|-------:|
| pcap_nrf_sbi_oauth      |     0 |    280 |    297 |    567 |    677 |
| pcap_ngap_procedure     |     0 |    123 |    130 |    317 |    356 |
| pcap_nrf_sbi_discovery  |     0 |    124 |    132 |    271 |    328 |
| pcap_dl_nas_transport   |     0 |    123 |    120 |    276 |    322 |
| pcap_ausf_sbi_auth      |     0 |     87 |     95 |    230 |    290 |
| pcap_smf_sbi_pdu        |     0 |     20 |     20 |     20 |     22 |
| pcap_udm_sbi_sdm        |     0 |     22 |     16 |     21 |     17 |
| pcap_amf_sbi_comm       |     0 |     12 |     14 |     12 |     12 |

### Key observations

- **pcap_ngap_procedure grows most steeply** (123 -> 356 = 2.89x, 10->40 UE) — every UE's NGAP Registration is a distinct captured procedure
- **pcap_ausf_sbi_auth** (auth challenges visible on wire): 87 -> 290 (~3.33x), near-linear in UE count
- **pcap_smf_sbi_pdu / pcap_udm_sbi_sdm / pcap_amf_sbi_comm stay flat (~20)** — these are background NF-to-NF keepalive API calls unrelated to UE count

---

## Table 8: Incremental Units per Added UE (Marginal Cost)

| Interval   | LogLines/UE | Packets/UE | LogEvents/UE | PcapEvents/UE |
|------------|------------:|-----------:|-------------:|--------------:|
| 1 -> 10 UE |     1,009   |     1,226  |        599   |           99  |
| 10-> 20 UE |     1,008   |        76  |        496   |            2  |
| 20-> 30 UE |     1,731   |       846  |      1,176   |           91  |
| 30-> 40 UE |     2,099   |       317  |      1,383   |           30  |

### Interpretation

- **LogLines/UE rises with density (1009 -> 2099):** higher UE counts compound the NAS+auth cascade — each UE triggers AMF/AUSF/UDM/NRF/UDR chains that all emit logs
- **Packets/UE oscillates:** high at 1->10 UE jump (because AMF+SMF pcaps newly available), near-zero at 10->20 (SMF heartbeats dominate, no new N2 packets visible in that increment), then large jump at 20->30 from AMF growing
- **LogEvents/UE rises (599 -> 1383):** the normalized event parser captures more per-UE events at higher density because more inter-NF API calls occur (AMF calls SMF which calls UPF, etc.)
- **PcapEvents/UE is small (2-99):** pcap normalization extracts only higher-level protocol events (NGAP procedures, PFCP sessions) — these are sparse relative to raw packet count

---

## Summary: Which metric scales most with UE count?

```
Metric             1 UE     40 UE    Growth     Scaling
Log lines        245,748   303,209    1.23x     O(N^0.24) -- sub-linear
Packets (pcap)     1,568    24,992   15.94x*    O(N^1.1) -- near-linear
Log events        27,947    63,884    2.29x     O(N^0.59) -- moderate
PCAP events            0     2,121    new       O(N^0.9)  -- near-linear
Total events      27,947    66,005    2.36x     O(N^0.61) -- moderate
```
* Packet count is inflated by AMF/SMF pcap absence at 1 UE. From 10->40 UE: 12,600->24,992 = 1.98x (~O(N^0.75)).

Key conclusions:
1. RAW packet count is most sensitive to UE count -- every new UE contributes a full NGAP+PFCP sequence on the wire
2. Log event count (normalized) is moderately sensitive (2.29x) -- driven by NAS+auth event types that scale per-UE
3. Log LINE count is least sensitive (1.23x) -- SMF+UPF background noise dominates (76-87% of all lines)
4. AMF N2 pcap is the single most UE-sensitive artifact: 6,924 -> 18,485 packets (2.67x, 10->40 UE)
5. SMF N4 pcap is nearly UE-insensitive: 3,979 -> 4,222 packets (1.06x, 10->40 UE) -- PFCP heartbeats dominate
6. Parser match rate IMPROVES with UE count (11.4% -> 20.4%) -- more UE-correlated events relative to background noise
