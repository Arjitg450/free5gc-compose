# Multi-UE log verification

How to confirm from logs that a run used **multiple UEs at the same time** with **different IPs** (not a single UE repeatedly).

## 1. UERANSIM log (`ueransim.log`)

- **Multiple UEs at once**: Look for several `UE[N] new signal detected` and `RRC Setup for UE[N]` in a short time window.
- Example (S2 run): At `11:47:34` you see UE[3]–UE[12] detected and RRC Setup for all 10 within ~1 second → **10 UEs in parallel**.

```
[ngap] [debug] UE[3] new signal detected
[ngap] [debug] UE[4] new signal detected
...
[rrc] [info] RRC Setup for UE[3]
[rrc] [info] RRC Setup for UE[4]
...
[ngap] [info] PDU session resource(s) setup for UE[11] count[1]
[ngap] [info] PDU session resource(s) setup for UE[12] count[1]
```

## 2. AMF log (`amf.log`)

- **Multiple UE contexts**: Look for multiple `New AmfUe [supi:][guti:...]` and `Handle InitialUEMessage` in a short window.
- Each distinct GUTI is one UE. Example (S2): 10 entries with `guti:20893cafe0000000004` through `20893cafe000000000d` → **10 different UEs**.

## 3. SMF log (`smf.log`)

- **Different SUPIs**: Search for `supi:imsi-` — you should see more than one IMSI (e.g. `imsi-208930000000001`, `imsi-208930000000002`, …).
- **Different UE IPs**: Search for `Allocated UE IP address:` — you should see multiple IPs (e.g. `10.60.0.1`, `10.60.0.2`, `10.61.0.1`, …).
- **Correct mapping**: Each SUPI gets its own PDU address; same SUPI can have two sessions (two DNNs) so two IPs (e.g. 10.60.0.x and 10.61.0.x) per UE is normal.

Example:

```
Allocated UE IP address: 10.60.0.1   → supi:imsi-208930000000001
Allocated UE IP address: 10.61.0.1   → supi:imsi-208930000000001 (same UE, 2nd PDU session)
Allocated UE IP address: 10.60.0.4   → supi:imsi-208930000000002
Allocated UE IP address: 10.61.0.5   → supi:imsi-208930000000002
```

## 4. UPF log (`upf.log`)

- **Multiple PFCP sessions**: Look for multiple `New session` lines with different `CPSEID`/`UPSEID` (e.g. `CPSEID:0x8`, `0x9`, …).
- Each session corresponds to a PDU session (one or two per UE depending on DNNs).

## S2_moderate_interleave run (20260218_171713) – summary

| Check              | Result |
|--------------------|--------|
| UERANSIM multi-UE  | ✅ UE[3]–UE[12] (10 UEs) detected and RRC setup in same window |
| AMF multi-UE       | ✅ 10× `New AmfUe` with distinct GUTIs (4–d) at 11:47:34–35 |
| SMF different SUPI | ✅ At least 2 SUPIs: `imsi-208930000000001`, `imsi-208930000000002` |
| SMF different IPs  | ✅ Multiple IPs: 10.60.0.1–10.60.0.5, 10.61.0.1–10.61.0.7 |
| UPF multi-session  | ✅ Multiple “New session” (CPSEID 0x1–0xc) |

**Conclusion**: The S2 run is **multi-UE**: multiple UEs attach in parallel, and the core assigns **different IPs** per UE (and per PDU session). UERANSIM with `-n 10` uses one config and auto-increments IMSI (base, base+1, … base+9), so 10 distinct SUPIs are expected; in this log slice we see at least two SUPIs and many distinct IPs and PFCP sessions.

## Single-UE vs multi-UE (quick diff)

- **Single-UE** (e.g. S1): One `New AmfUe`, one SUPI in SMF, one or two IPs (e.g. 10.60.0.1, 10.61.0.1), one/two PFCP sessions.
- **Multi-UE**: Several `New AmfUe` in a short window, several SUPIs in SMF, many different IPs (10.60.0.x and 10.61.0.x), many PFCP sessions.
