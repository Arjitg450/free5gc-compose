# 5G End-to-End Lab: free5GC + UERANSIM

> **Purpose**: This document is a self-contained, step-by-step lab guide for deploying a 5G standalone core network (free5GC) with a simulated RAN and UE (UERANSIM) using Docker Compose. It is designed for students who want to **build**, **understand**, and **debug** a working 5G system.

> **Structure**: The lab is split into **Day 1** (setup, PDU sessions, data plane) and **Day 2** (authentication deep-dive, NAS security, advanced signaling). Complete Day 1 first.

---

## Table of Contents

- [Step 0 — Docker Setup (Mandatory First Step)](#step-0--docker-setup-mandatory-first-step)
- [Step 1 — Environment Setup](#step-1--environment-setup)
- [Step 2 — Understanding the 5G Core Architecture](#step-2--understanding-the-5g-core-architecture)
- **Day 1: Setup and PDU Sessions**
  - [Step 3 — Start the 5G Core](#step-3--start-the-5g-core)
  - [Step 4 — gNB Connection (NG Setup)](#step-4--gnb-connection-ng-setup)
  - [Step 5 — UE Registration and PDU Session Establishment](#step-5--ue-registration-and-pdu-session-establishment)
  - [Step 6 — PFCP Interaction (SMF ↔ UPF)](#step-6--pfcp-interaction-smf--upf)
  - [Step 7 — Tunneling in 5G (GTP-U)](#step-7--tunneling-in-5g-gtp-u)
  - [Step 8 — Forwarding Setup](#step-8--forwarding-setup)
  - [Step 9 — Data-Plane Verification](#step-9--data-plane-verification)
  - [Step 10 — Deregistration](#step-10--deregistration)
- **Day 2: Authentication and Signaling Deep-Dive**
  - [Step 11 — UE and Core Authentication Flow](#step-11--ue-and-core-authentication-flow)
  - [Step 12 — NAS Message Protection](#step-12--nas-message-protection)
- [Wireshark Capture Analysis](#wireshark-capture-analysis)
- [NF Logs Reference](#nf-logs-reference)
- [Troubleshooting](#troubleshooting)
- [Validation Checklist](#validation-checklist)

---

## Step 0 — Docker Setup (Mandatory First Step)

Docker and Docker Compose are the foundation of this lab. Every 5G network function (NF) runs as a Docker container. **Do not skip this step.**

### 0.1 Install Docker Engine

```bash
# Download and run the official install script
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Allow your user to run Docker without sudo
sudo usermod -aG docker $USER
newgrp docker

# Verify Docker is running
docker --version
# Expected: Docker version 20.10+ (e.g., 29.1.3)
```

### 0.2 Verify Docker Compose

Docker Compose v2 ships as a Docker plugin. Confirm it is available:

```bash
docker compose version
# Expected: Docker Compose version v2.x.x (e.g., v5.0.0)
```

If this command fails, install the plugin manually:

```bash
sudo apt-get update
sudo apt-get install -y docker-compose-plugin
```

### 0.3 Check Port Availability

The core network uses several ports. Before starting, verify nothing else is using them:

```bash
# Check critical ports: MongoDB (27017), AMF SCTP (38412), WebUI (5000)
sudo ss -tlnp | grep -E '27017|38412|5000'
```

If any port is already in use, identify and stop the conflicting process:

```bash
# Find the process using a specific port (example: 27017)
sudo lsof -i :27017

# Stop it (replace <PID> with the actual process ID)
sudo kill <PID>

# Or if it is a systemd service (e.g., a local MongoDB)
sudo systemctl stop mongod
```

### 0.4 Verify Docker Networking

Ensure the Docker bridge driver works correctly:

```bash
docker network ls
# You should see at least 'bridge', 'host', and 'none'
```

**Checkpoint**: Docker Engine v20.10+ is installed, Docker Compose v2 is available, and critical ports are free. Proceed to Step 1.

---

## Step 1 — Environment Setup

### 1.1 System Requirements

| Requirement       | Minimum                                      |
| ----------------- | -------------------------------------------- |
| **OS**            | Ubuntu 20.04 or 22.04 LTS (x86_64)          |
| **Kernel**        | 5.0+ (required for gtp5g kernel module)      |
| **RAM**           | 4 GB (8 GB recommended)                      |
| **Disk**          | 10 GB free space                             |
| **Privileges**    | Root or sudo access                          |
| **Packages**      | `git`, `make`, `gcc`                         |

Check your kernel version:

```bash
uname -r
# Expected: 5.x.x (e.g., 5.15.0-164-generic)
```

Install build dependencies:

```bash
sudo apt update && sudo apt install -y git make gcc
```

### 1.2 Install gtp5g Kernel Module

The UPF requires the `gtp5g` kernel module to perform GTP-U packet encapsulation and decapsulation in kernel space. Without it, the UPF container will fail to start.

```bash
# Clone the gtp5g repository
git clone https://github.com/free5gc/gtp5g.git
cd gtp5g

# Build the kernel module
make

# Install it
sudo make install

# Load the module into the running kernel
sudo modprobe gtp5g

# Verify it is loaded
lsmod | grep gtp5g
# Expected: a line starting with 'gtp5g'
```

> **Why this matters**: The gtp5g module creates a kernel-level network device that handles GTP-U encapsulation. The UPF uses this to tunnel user-plane packets between the gNB and the data network. Without it, you get the error: `open Gtp5g: operation not supported`.

### 1.3 Clone free5GC Compose

```bash

git clone https://github.com/free5gc/free5gc-compose.git
cd free5gc-compose
```

### 1.4 Understand the Network Configuration

All containers share a single Docker bridge network called `privnet`:

| Parameter     | Value               |
| ------------- | ------------------- |
| **Subnet**    | `10.100.200.0/24`   |
| **Bridge**    | `br-free5gc`        |
| **DNS**       | `*.free5gc.org`     |

Each container resolves other NFs via DNS aliases (e.g., `amf.free5gc.org`, `upf.free5gc.org`). This mimics real network resolution.

### 1.5 Verify Configuration Files

The `config/` directory contains YAML configuration for every NF and UERANSIM:

```bash
ls config/
```

Key files to understand:

| File              | Purpose                                          |
| ----------------- | ------------------------------------------------ |
| `amfcfg.yaml`     | AMF — PLMN, TAC, security algorithms, SBI        |
| `smfcfg.yaml`     | SMF — PFCP, UPF selection, IP pools, slices       |
| `upfcfg.yaml`     | UPF — PFCP listener, GTP-U interface, DNN pools   |
| `gnbcfg.yaml`     | gNB — MCC/MNC, AMF address, slices                |
| `uecfg.yaml`      | UE — SUPI, keys, sessions, security algorithms    |

### 1.6 Verify SUCI Protection Scheme (Profile A vs Profile B)

The UE configuration includes a SUCI (Subscription Concealed Identifier) protection scheme. This must match the UDM configuration.

In `config/uecfg.yaml`:

```yaml
protectionScheme: 1            # 1 = Profile A (ECIES with Curve25519)
homeNetworkPublicKeyId: 1      # Must match the key ID in UDM
homeNetworkPublicKey: "5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650"
```

- **Profile A**: Uses ECIES with Curve25519 (X25519). This is the default in free5GC.
- **Profile B**: Uses ECIES with secp256r1 (P-256).

> **Mismatch check**: If the UE uses Profile A but the UDM expects Profile B (or vice versa), registration will fail at the SUCI de-concealment step. Ensure both sides use the same profile and key.

**Checkpoint**: gtp5g is loaded, repository is cloned, and configuration files are verified. Proceed to Step 2.

---

## Step 2 — Understanding the 5G Core Architecture

Before starting the core, understand what each container does and how they interact.

### 2.1 Network Functions and Their Roles

```
┌──────────────────────────────────────────────────────────────────────┐
│                          5G Core Network                             │
│                                                                      │
│  ┌─────┐   ┌──────┐   ┌──────┐   ┌─────┐   ┌──────┐   ┌─────┐     │
│  │ NRF │   │ AUSF │   │ UDM  │   │ UDR │   │ NSSF │   │ PCF │     │
│  └──┬──┘   └──┬───┘   └──┬───┘   └──┬──┘   └──┬───┘   └──┬──┘     │
│     │ SBI     │ SBI      │ SBI      │ SBI     │ SBI      │ SBI     │
│     └────┬────┴──────────┴──────────┴─────────┴──────────┘          │
│          │                                                           │
│     ┌────┴────┐         ┌──────┐                                    │
│     │   AMF   │◄──N11──►│  SMF │                                    │
│     └────┬────┘         └──┬───┘                                    │
│          │ N2 (NGAP/SCTP)  │ N4 (PFCP/UDP)                         │
│          │                 │                                         │
│     ┌────┴────┐         ┌──┴───┐                                    │
│     │   gNB   │◄──N3───►│  UPF │──── N6 ────► Internet             │
│     └────┬────┘ (GTP-U)  └──────┘                                    │
│          │ (Radio)                                                    │
│     ┌────┴────┐                                                      │
│     │   UE    │                                                      │
│     └─────────┘                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 NF Descriptions

| NF       | Full Name                           | Role                                                                                   |
| -------- | ----------------------------------- | --------------------------------------------------------------------------------------- |
| **AMF**  | Access and Mobility Management      | Handles UE registration, authentication orchestration, mobility, and NAS signaling      |
| **SMF**  | Session Management Function         | Manages PDU sessions, selects UPF, installs forwarding rules via PFCP                   |
| **UPF**  | User Plane Function                 | Encapsulates/decapsulates GTP-U, routes user traffic, applies forwarding rules          |
| **NRF**  | Network Repository Function         | Service registry — all NFs register here and discover each other                        |
| **AUSF** | Authentication Server Function      | Executes 5G-AKA authentication, derives authentication vectors                          |
| **UDM**  | Unified Data Management             | Manages subscriber data, generates authentication credentials, SUCI de-concealment      |
| **UDR**  | Unified Data Repository             | Database backend for UDM, PCF, and NEF (stores subscription and policy data)            |
| **NSSF** | Network Slice Selection Function    | Selects the appropriate network slice for a UE                                          |
| **PCF**  | Policy Control Function             | Provides policy rules (QoS, charging) to SMF and AMF                                   |
| **CHF**  | Charging Function                   | Handles online/offline charging for data usage                                          |
| **WebUI**| Web Console                         | Browser-based interface for managing subscribers (add/edit UE profiles)                  |

### 2.3 Key Interfaces in This Lab

| Interface | Between         | Protocol       | Port    | Purpose                                      |
| --------- | --------------- | -------------- | ------- | -------------------------------------------- |
| **N2**    | gNB ↔ AMF       | NGAP over SCTP | 38412   | Control-plane signaling (RAN ↔ Core)         |
| **N3**    | gNB ↔ UPF       | GTP-U over UDP | 2152    | User-plane data tunnel                       |
| **N4**    | SMF ↔ UPF       | PFCP over UDP  | 8805    | Session management and forwarding rules      |
| **N6**    | UPF ↔ Internet  | IP             | —       | External data network access                 |
| **N11**   | AMF ↔ SMF       | HTTP/2 (SBI)   | 8000    | PDU session context management               |
| **SBI**   | All NFs ↔ NRF   | HTTP (REST)    | 8000    | Service registration and discovery           |

---

# Day 1: Setup, PDU Sessions, and Data Plane

---

## Step 3 — Start the 5G Core

### 3.1 Pull Images and Start All Containers

```bash
cd /opt/free5gc-compose

# Pull the latest container images
docker compose pull

# Start the entire 5G core in detached mode
docker compose up -d
```

### 3.2 Verify All Containers Are Running

```bash
docker compose ps
```

**Expected output**: All containers should show `Up` or `Up (healthy)` status:

```
NAME              STATUS
db                Up (healthy)
free5gc-amf       Up (healthy)
free5gc-ausf      Up (healthy)
free5gc-nrf       Up (healthy)
free5gc-nssf      Up (healthy)
free5gc-pcf       Up (healthy)
free5gc-smf       Up (healthy)
free5gc-udm       Up (healthy)
free5gc-udr       Up (healthy)
free5gc-upf       Up
free5gc-chf       Up (healthy)
free5gc-webui     Up (healthy)
ueransim          Up
```

If any container shows `Exited` or `Restarting`, check its logs:

```bash
docker compose logs <container-name>
# Example: docker compose logs free5gc-upf
```

### 3.3 Verify the Docker Network

```bash
docker network inspect free5gc-compose_privnet | grep -A 5 "Subnet"
# Expected: "Subnet": "10.100.200.0/24"
```
see the Troublshooting section for any problem

### 3.4 Access the WebUI (Optional)

The WebUI lets you manage subscriber profiles in a browser:

```
URL:      http://localhost:5000
Username: admin
Password: free5gc
```

A default subscriber (`imsi-208930000000001`) is pre-configured. You can verify its Key, OPC, and session settings here.

**Checkpoint**: All containers are running and the network is operational. Proceed to Step 4.

---

## Step 4 — gNB Connection (NG Setup)

The gNB (simulated by UERANSIM) must first connect to the AMF over the N2 interface before any UE can register. This is the **NG Setup** procedure.

### 4.1 What Happens During NG Setup

1. The gNB opens an **SCTP** connection to `amf.free5gc.org:38412`.
2. The gNB sends an **NG Setup Request** containing its identity (gNB ID), supported PLMN(s), and TAC.
3. The AMF validates the request — checks that the PLMN (MCC=208, MNC=93) and TAC (000001) match its configuration.
4. The AMF responds with an **NG Setup Response**, confirming the connection.

### 4.2 Verify NG Setup

The UERANSIM container starts the gNB automatically. Restart it to capture fresh logs:

```bash
docker compose restart ueransim
```

Wait 5 seconds, then check both sides:

**gNB side (UERANSIM logs):**

```bash
docker compose logs --since 1m ueransim
```

Expected output:

```
[sctp] [info] SCTP connection established (10.100.200.16:38412)
[ngap] [debug] Sending NG Setup Request
[ngap] [debug] NG Setup Response received
[ngap] [info] NG Setup procedure is successful
```

**AMF side (free5gc-amf logs):**

```bash
docker compose logs --since 1m free5gc-amf
```

Expected output:

```
[INFO][AMF][Ngap] [AMF] SCTP Accept from: 10.100.200.13:xxxxx
[INFO][AMF][Ngap] Create a new NG connection for: 10.100.200.13:xxxxx
[INFO][AMF][Ngap][ran_addr:10.100.200.13:xxxxx] Handle NGSetupRequest
[INFO][AMF][Ngap][ran_addr:10.100.200.13:xxxxx] Send NG-Setup response
```

> **What you learned**: The gNB establishes an SCTP association with the AMF. SCTP (not TCP) is used because it supports multi-streaming and is resilient to head-of-line blocking — critical for control-plane signaling in telecom.

**Checkpoint**: gNB is connected to the AMF. The N2 interface is operational.

---

## Step 5 — UE Registration and PDU Session Establishment

### 5.1 Start the UE Simulation

Start the UE process inside the UERANSIM container:

```bash
docker exec -it ueransim bash -lc "nohup ./nr-ue -c config/uecfg.yaml > /tmp/ue.log 2>&1 &"
```

Wait 3–5 seconds for the procedures to complete, then view the UE log:

```bash
docker exec -it ueransim cat /tmp/ue.log
```

### 5.2 What Happens During UE Registration (Overview for Day 1)

The registration procedure involves several NAS (Non-Access Stratum) message exchanges between the UE and the AMF. Here is the simplified flow:

```
UE                          gNB                         AMF
│                            │                            │
│──── Registration Request ──►──── Initial UE Message ───►│
│                            │                            │
│                            │                            ├──► AUSF/UDM
│                            │                            │    (Auth vectors)
│                            │                            │
│◄── Authentication Request ─◄──── Downlink NAS ─────────│
│──── Authentication Response►──── Uplink NAS ───────────►│
│                            │                            │
│◄── Security Mode Command ──◄──── Downlink NAS ─────────│
│──── Security Mode Complete ►──── Uplink NAS ───────────►│
│                            │                            │
│◄── Registration Accept ────◄──── Initial Context Setup ─│
│──── Registration Complete ─►──── Uplink NAS ───────────►│
│                            │                            │
│──── PDU Session Est. Req. ─►──── Uplink NAS ───────────►│──► SMF
│                            │                            │     │
│                            │                            │     ├──► UPF (PFCP)
│                            │                            │     │
│◄── PDU Session Est. Accept ◄──── Downlink NAS ─────────│◄── SMF
│                            │                            │
```

> **Day 2 note**: The authentication and security mode procedures are explained in detail in Steps 11 and 12. For Day 1, focus on getting the UE registered and a PDU session established.

### 5.3 Verify UE Registration

**UE logs:**

```bash
docker exec ueransim tail -n 30 /tmp/ue.log
```

Expected output:

```
[nas] [debug] Sending Initial Registration
[nas] [debug] Authentication Request received
[nas] [debug] Security Mode Command received
[nas] [debug] Registration accept received
[nas] [info] Initial Registration is successful
[nas] [info] UE switches to state [MM-REGISTERED/NORMAL-SERVICE]
```

**AMF logs:**

```bash
docker compose logs --since 2m free5gc-amf | grep -E "Registration|Authentication|Security"
```

Expected output:

```
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000001] Handle Registration Request
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000001] Send Authentication Request
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000001] Send Security Mode Command
[INFO][AMF][Gmm][supi:SUPI:imsi-208930000000001] Send Registration Accept
```

### 5.4 Verify PDU Session Establishment

After registration, the UE automatically requests a PDU session (configured in `uecfg.yaml`).

**UE logs:**

```
[nas] [debug] Sending PDU Session Establishment Request
[nas] [debug] PDU Session Establishment Accept received
[app] [info] Connection setup for PDU session[1] is successful, TUN interface[uesimtun0, 10.60.0.x] is up.
```

**SMF logs:**

```bash
docker compose logs --since 2m free5gc-smf | grep -i "pdusess"
```

Expected output:

```
[INFO][SMF][PduSess] Handle PDU Session Establishment Request
[INFO][SMF][PduSess] Selected UPF[10.100.200.3]
[INFO][SMF][PduSess] Sending PFCP Session Establishment Request
[INFO][SMF][PduSess] Received PFCP Session Establishment Response
```

**What happened**:
1. The UE sent a PDU Session Establishment Request (NAS message) to the AMF.
2. The AMF forwarded it to the SMF (N11 interface).
3. The SMF selected the UPF based on the DNN (`internet`) and slice (SST=1, SD=010203).
4. The SMF sent a PFCP Session Establishment Request to the UPF (N4 interface).
5. The UPF created the GTP-U tunnel, allocated an IP address (from the 10.60.0.0/16 pool), and replied.
6. The SMF informed the AMF, which relayed the PDU Session Establishment Accept back to the UE.
7. The UE created the `uesimtun0` tunnel interface with the assigned IP.

**Checkpoint**: UE is registered and a PDU session is active. The `uesimtun0` interface is up.

---

## Step 6 — PFCP Interaction (SMF ↔ UPF)

PFCP (Packet Forwarding Control Protocol) is used on the **N4 interface** between the SMF and UPF. It is the mechanism by which the control plane tells the user plane *what to do* with packets.

### 6.1 What is PFCP?

PFCP (defined in 3GPP TS 29.244) separates the control plane from the user plane. The SMF uses PFCP to:

1. **Establish sessions**: Create a forwarding context on the UPF for a specific PDU session.
2. **Install rules**: Tell the UPF how to handle packets — which packets to forward, where to send them, and what QoS to apply.
3. **Modify sessions**: Update rules when mobility or QoS changes occur.
4. **Delete sessions**: Clean up when a PDU session ends.

### 6.2 PFCP Session Establishment in Detail

When the SMF receives a PDU Session Establishment Request, it sends a **PFCP Session Establishment Request** to the UPF. This request contains:

| Rule Type        | Purpose                                                                     |
| ---------------- | --------------------------------------------------------------------------- |
| **PDR** (Packet Detection Rule) | Defines *which* packets to match (e.g., by GTP TEID, source interface)  |
| **FAR** (Forwarding Action Rule) | Defines *what to do* with matched packets (forward, drop, buffer)       |
| **QER** (QoS Enforcement Rule)   | Defines QoS parameters (MBR, GBR) to enforce on matched traffic        |
| **URR** (Usage Reporting Rule)   | Defines when to report usage (volume thresholds, time periods)          |

**Simplified rule flow for an uplink packet (UE → Internet)**:

```
UE packet → gNB → [GTP-U encap] → UPF
                                     │
                               PDR matches (GTP TEID, N3 source)
                                     │
                               FAR says: decapsulate GTP, forward to N6
                                     │
                               QER enforces: rate limit
                                     │
                                     ▼
                                  Internet
```

### 6.3 Verify PFCP in Logs

**UPF logs (session creation):**

```bash
docker compose logs --since 2m free5gc-upf | grep -i "pfcp\|session"
```

Expected:

```
[INFO][UPF][PFCP] handleSessionEstablishmentRequest
[INFO][UPF][PFCP][CPSEID:0x3][UPSEID:0x1] New session
[INFO][UPF][Perio] new ticker [10s]
```

- **CPSEID**: Control Plane Session Endpoint ID (SMF's identifier for this session).
- **UPSEID**: User Plane Session Endpoint ID (UPF's identifier for this session).
- **new ticker [10s]**: The UPF starts periodic usage reporting every 10 seconds (configured by `urrPeriod: 10` in `smfcfg.yaml`).

### 6.4 PFCP Association

Before any sessions can be created, the SMF and UPF must establish a **PFCP Association**. This happens automatically at startup:

```bash
docker compose logs free5gc-smf | grep -i "association"
docker compose logs free5gc-upf | grep -i "association"
```

Expected:

```
# SMF side
[INFO][SMF][PFCP] Sending PFCP Association Setup Request to UPF[upf.free5gc.org]

# UPF side
[INFO][UPF][PFCP] handleAssociationSetupRequest
```

> **Key concept**: PFCP is to the user plane what SQL is to a database — the control plane sends *instructions* (rules), and the user plane *executes* them on live traffic.

---

## Step 7 — Tunneling in 5G (GTP-U)

### 7.1 What is Tunneling?

Tunneling is the process of **encapsulating one packet inside another**. In 5G, the user's IP packet (e.g., an ICMP ping to 8.8.8.8) is wrapped inside a GTP-U header and a UDP/IP header for transport between network elements.

### 7.2 GTP-U (GPRS Tunneling Protocol — User Plane)

GTP-U (defined in 3GPP TS 29.281) is the tunneling protocol used on the **N3 interface** (gNB ↔ UPF) and **N9 interface** (UPF ↔ UPF, in multi-UPF scenarios).

**Packet structure on the N3 interface**:

```
┌──────────────────────────────────────────────────┐
│ Outer IP Header (gNB IP ↔ UPF IP)               │
├──────────────────────────────────────────────────┤
│ UDP Header (src port: dynamic, dst port: 2152)   │
├──────────────────────────────────────────────────┤
│ GTP-U Header (TEID identifies the tunnel)        │
├──────────────────────────────────────────────────┤
│ Inner IP Header (UE IP: 10.60.0.x ↔ 8.8.8.8)   │
├──────────────────────────────────────────────────┤
│ Inner Payload (e.g., ICMP Echo Request)          │
└──────────────────────────────────────────────────┘
```

### 7.3 Why is Tunneling Required?

1. **UE Mobility**: The UE's IP address (10.60.0.x) stays the same even when the UE moves between gNBs. Only the outer IP header changes — the tunnel endpoint is updated, not the UE's address.
2. **Separation of User and Transport Planes**: The inner packet (user traffic) is independent of the transport network topology.
3. **Multi-tenancy**: Different tunnels (identified by TEIDs) can carry traffic for different UEs over the same physical links.

### 7.4 TEID (Tunnel Endpoint Identifier)

Each GTP-U tunnel is identified by a **TEID** — a 32-bit number assigned during PDU session establishment. There are two TEIDs per session:

- **Uplink TEID**: Assigned by the UPF, used by the gNB when sending packets toward the core.
- **Downlink TEID**: Assigned by the gNB, used by the UPF when sending packets toward the UE.

### 7.5 Relevance to This Lab

In this Docker-based lab:

- The gNB (UERANSIM) and UPF communicate over the `privnet` Docker bridge.
- GTP-U packets travel as **plain UDP/2152** between their container IPs (no IPsec).
- The `gtp5g` kernel module handles GTP-U encapsulation/decapsulation inside the UPF container.
- The `uesimtun0` interface on the UERANSIM side represents the UE's end of the tunnel.

> **Security note**: In this lab, N3 traffic is **not encrypted**. In a production deployment, IPsec (per 3GPP TS 33.210 NDS/IP) would typically protect the N3 interface when it traverses untrusted transport.

---

## Step 8 — Forwarding Setup

### 8.1 How Forwarding Rules Are Configured

During PDU session establishment, the SMF installs **Packet Detection Rules (PDRs)** and **Forwarding Action Rules (FARs)** on the UPF via PFCP. These rules tell the UPF how to handle each packet:

**Uplink (UE → Internet)**:
1. PDR: Match packets arriving on the N3 interface with a specific GTP TEID.
2. FAR: Decapsulate the GTP-U header and forward the inner IP packet to the N6 interface (Internet).

**Downlink (Internet → UE)**:
1. PDR: Match packets arriving on the N6 interface destined for the UE's IP (10.60.0.x).
2. FAR: Encapsulate in a GTP-U header (with the downlink TEID) and forward to the gNB via N3.

### 8.2 Where Rules Are Installed

Rules are installed on the **UPF** only. The SMF is the controller; the UPF is the data-plane executor.

### 8.3 NAT and IP Forwarding in the UPF

The UPF container runs an iptables script (`config/upf-iptables.sh`) at startup:

```bash
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
iptables -I FORWARD 1 -j ACCEPT
```

- **MASQUERADE**: Translates the UE's private IP (10.60.0.x) to the UPF's container IP when packets leave toward the Internet. This is NAT (Network Address Translation).
- **FORWARD ACCEPT**: Allows IP forwarding through the UPF container so packets can transit between the GTP tunnel interface and eth0.

### 8.4 End-to-End Traffic Flow After Session Establishment

```
UE (10.60.0.x)
  │ ping 8.8.8.8
  ▼
uesimtun0 (TUN device in UERANSIM)
  │ Inner: 10.60.0.x → 8.8.8.8
  ▼
UERANSIM nr-ue process
  │ GTP-U encapsulate (add TEID, UDP:2152, outer IP)
  ▼
gNB (10.100.200.13) ──N3──► UPF (10.100.200.3)
                               │ GTP-U decapsulate
                               │ Inner: 10.60.0.x → 8.8.8.8
                               │ NAT: UPF-IP → 8.8.8.8
                               ▼
                           Internet (via eth0 + Docker NAT)
                               │
                           Reply: 8.8.8.8 → UPF-IP
                               │ Reverse NAT: → 10.60.0.x
                               │ GTP-U encapsulate (downlink TEID)
                               ▼
UPF (10.100.200.3) ──N3──► gNB (10.100.200.13)
                               │ GTP-U decapsulate
                               ▼
                           uesimtun0 → UE receives reply
```

---

## Step 9 — Data-Plane Verification

### 9.1 Ping Test

Verify the UE can reach the Internet through the 5G tunnel:

```bash
docker exec -it ueransim ping -c 4 -I uesimtun0 8.8.8.8
```

Expected output:

```
PING 8.8.8.8 (8.8.8.8) from 10.60.0.x uesimtun0: 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=111 time=18.4 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=111 time=17.9 ms
--- 8.8.8.8 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss
```

### 9.2 HTTP Test

```bash
docker exec -it ueransim curl --interface uesimtun0 -I http://example.com
```

Expected output:

```
HTTP/1.1 200 OK
Content-Type: text/html
Server: cloudflare
```

### 9.3 Verify the Tunnel Interface

```bash
docker exec ueransim ip -d a show uesimtun0
```

Expected output:

```
7: uesimtun0: <POINTOPOINT,PROMISC,NOTRAILERS,UP,LOWER_UP> mtu 1400 state UNKNOWN
    link/none
    inet 10.60.0.x/16 scope global uesimtun0
```

- `POINTOPOINT`: This is a point-to-point tunnel (not broadcast).
- `mtu 1400`: Reduced from 1500 to account for GTP-U encapsulation overhead.
- `inet 10.60.0.x/16`: The IP assigned by the SMF from the pool configured in `smfcfg.yaml`.

### 9.4 Verify Traffic Statistics

```bash
docker exec ueransim ip -s link show uesimtun0
```

The RX/TX counters should increase as you run ping and curl, proving data traversal through the 5G core.

### 9.5 Verify UPF Usage Reporting

While data flows, the UPF periodically reports usage statistics to the SMF:

```bash
docker compose logs --tail 20 free5gc-upf | grep -i "report"
```

Expected:

```
[INFO][UPF][PFCP] serveUSAReport
[INFO][UPF][PFCP] handleSessionReportResponse
```

This confirms the UPF is actively monitoring and reporting data usage for the PDU session.

**Checkpoint**: Data flows end-to-end through the 5G core. The UE can reach the Internet.

---

## Step 10 — Deregistration

### 10.1 Deregistration Flow

When the UE disconnects, a cleanup process ensures all resources are released:

```
UE                          gNB                    AMF              SMF              UPF
│                            │                      │                │                │
│── Deregistration Request ─►│── UL NAS Transport ─►│                │                │
│                            │                      │                │                │
│                            │                      │── Release SM ─►│                │
│                            │                      │   Context Req  │                │
│                            │                      │                │── PFCP Session ►│
│                            │                      │                │   Deletion Req  │
│                            │                      │                │                │
│                            │                      │                │◄─ PFCP Session ─│
│                            │                      │                │   Deletion Resp │
│                            │                      │                │                │
│                            │                      │◄─ Release SM ──│                │
│                            │                      │   Context Resp │                │
│                            │                      │                │                │
│◄─ Deregistration Accept ──◄│◄─ DL NAS Transport ─│                │                │
│                            │                      │                │                │
│                            │◄─ UE Context Release │                │                │
│                            │         Command      │                │                │
│                            │── UE Context Release►│                │                │
│                            │         Complete     │                │                │
```

### 10.2 Trigger Deregistration

Stop the UE process gracefully:

```bash
docker exec -it ueransim pkill -2 nr-ue
```

The signal `-2` (SIGINT) triggers a graceful deregistration, not just a kill.

### 10.3 Verify Deregistration in Logs

**UE teardown logs:**

```bash
docker exec ueransim tail -n 20 /tmp/ue.log
```

Expected:

```
[nas] [info] UE switches to state [MM-DEREGISTERED/PLMN-SEARCH]
```

**Core-side teardown logs:**

```bash
docker compose logs --since 1m free5gc-amf free5gc-smf free5gc-upf | grep -iE "deregist|release|delet"
```

Expected:

```
[INFO][AMF][Gmm] Handle event[Gmm Message], transition from [Deregistered] to [Deregistered]
[INFO][SMF][PduSess] Receive Release SM Context Request
[INFO][SMF][PduSess] Sending PFCP Session Deletion Request
[INFO][UPF][PFCP] handleSessionDeletionRequest
[INFO][UPF][PFCP][CPSEID:0x2][UPSEID:0x2] sess deleted
```

### 10.4 What Got Cleaned Up

| Resource                     | Cleaned by | How                                        |
| ---------------------------- | ---------- | ------------------------------------------ |
| NAS security context         | AMF        | Context removed from AMF state             |
| PDU session                  | SMF        | Session released, IP returned to pool      |
| GTP-U tunnel (forwarding)    | UPF        | PFCP Session Deletion removes PDR/FAR/QER  |
| `uesimtun0` interface        | UERANSIM   | TUN device destroyed in UE process         |
| Usage reporting ticker        | UPF        | Periodic reporting stops                   |

**Checkpoint**: Day 1 is complete. The UE registered, established a PDU session, exchanged data, and deregistered cleanly.

---

# Day 2: Authentication and Signaling Deep-Dive

---

## Step 11 — UE and Core Authentication Flow

### 11.1 Why Authentication Matters

In 5G, **mutual authentication** is mandatory. Both the UE and the network must prove their identities to each other. 

### 11.2 5G-AKA Authentication Protocol

free5GC uses **5G-AKA** (Authentication and Key Agreement), defined in 3GPP TS 33.501. The protocol involves four NFs:

```
UE            AMF            AUSF           UDM
│              │               │              │
│─ Reg Req ───►│               │              │
│  (SUCI)      │               │              │
│              │── Nausf_Auth ─►│              │
│              │   (SUCI)      │── Nudm_Auth ─►│
│              │               │   (SUCI)     │
│              │               │              │─ De-conceal SUCI → SUPI
│              │               │              │─ Generate AV (RAND, AUTN, XRES*, KAUSF)
│              │               │              │
│              │               │◄─ AV ────────│
│              │               │              │
│              │               │─ Derive HXRES*
│              │               │─ Store XRES*
│              │               │
│              │◄─ AV (RAND, ──│
│              │   AUTN, HXRES*)
│              │               │
│◄─ Auth Req ──│               │
│  (RAND, AUTN)│               │
│              │               │
│─ Verify AUTN (network auth) │
│─ Compute RES*│               │
│              │               │
│── Auth Resp ►│               │
│  (RES*)      │               │
│              │── Nausf_Auth ─►│
│              │   (RES*)      │─ Compare RES* with XRES*
│              │               │
│              │◄─ Success ────│
│              │   (KSEAF)     │
```

### 11.3 Key Entities Explained

| Entity      | What it is                                                                                  |
| ----------- | ------------------------------------------------------------------------------------------- |
| **SUPI**    | Subscription Permanent Identifier (`imsi-208930000000001`). Never sent in cleartext.       |
| **SUCI**    | Subscription Concealed Identifier. Encrypted form of SUPI using the home network public key.|
| **RAND**    | 128-bit random challenge generated by the UDM.                                             |
| **AUTN**    | Authentication Token — allows the UE to verify the network is legitimate.                  |
| **RES\***   | Response — computed by the UE from RAND and the permanent key K.                           |
| **XRES\***  | Expected Response — computed by the UDM. If RES* matches XRES*, the UE is authenticated.  |
| **KAUSF**   | Key derived at AUSF, root of the session key hierarchy.                                    |

### 11.4 Key Derivation Hierarchy

Starting from the permanent key `K` stored on the USIM and in the UDM:

```
K (permanent key: 8baf473f2f8fd09487cccbd7097c6862)
├── CK (Cipher Key, 128-bit)
├── IK (Integrity Key, 128-bit)
│
└── KAUSF (derived from CK||IK at AUSF)
    └── KSEAF (derived from KAUSF at SEAF/AMF)
        └── KAMF (derived from KSEAF)
            ├── KNASint (NAS integrity key)
            ├── KNASenc (NAS encryption key)
            ├── KgNB   (derived for AS security)
            │   ├── KRRCint (RRC integrity)
            │   ├── KRRCenc (RRC encryption)
            │   └── KUPint / KUPenc (user plane)
            └── KN3IWF (for non-3GPP access)
```

### 11.5 Verify in Logs

**UE side — authentication challenge:**

```bash
docker exec ueransim grep -i "auth\|sqn" /tmp/ue.log
```

Expected:

```
[nas] [debug] Authentication Request received
[nas] [debug] Received SQN [000000000037]
[nas] [debug] SQN-MS [000000000000]
```

- **SQN (Sequence Number)**: Prevents replay attacks. The network's SQN must be within an acceptable range of the UE's stored SQN-MS.

### 11.6 Role of Each NF in Authentication

| NF       | Role                                                                                    |
| -------- | --------------------------------------------------------------------------------------- |
| **AMF**  | Orchestrator — receives Registration Request, delegates auth to AUSF, enforces result   |
| **AUSF** | Authentication server — generates HXRES*, verifies RES* against XRES*                   |
| **UDM**  | Credential manager — de-conceals SUCI, generates authentication vectors from K and OP   |
| **UDR**  | Data store — provides subscription data (K, OP, SQN) to UDM on request                  |

---

## Step 12 — NAS Message Protection

### 12.1 What is NAS Security?

NAS (Non-Access Stratum) is the signaling layer between the UE and the AMF. After authentication, NAS messages must be **integrity protected** and optionally **encrypted** to prevent tampering and eavesdropping.

### 12.2 Security Mode Command (SMC) Procedure

After successful authentication, the AMF sends a **Security Mode Command** to the UE:

```
AMF ──── Security Mode Command ────► UE
         (selected algorithms,
          key set identifier,
          replayed UE security capabilities)

AMF ◄─── Security Mode Complete ◄─── UE
         (integrity protected with new keys)
```

### 12.3 Algorithm Configuration in This Lab

**AMF configuration** (`config/amfcfg.yaml`):

```yaml
security:
  integrityOrder:
    - NIA2         # 128-NIA2 (AES-CMAC) — preferred
  cipheringOrder:
    - NEA2         # 128-NEA2 (AES-CTR) — preferred
    - NEA0         # Null encryption — fallback
```

**UE configuration** (`config/uecfg.yaml`):

```yaml
integrity:
  IA1: true    # 128-NIA1 (SNOW 3G)
  IA2: true    # 128-NIA2 (AES)
  IA3: true    # 128-NIA3 (ZUC)

ciphering:
  EA1: true    # 128-NEA1 (SNOW 3G)
  EA2: true    # 128-NEA2 (AES)
  EA3: true    # 128-NEA3 (ZUC)
```

**Negotiation result** (AMF picks highest priority from its list that the UE supports):

| Protection   | Selected Algorithm | Meaning                                    |
| ------------ | ------------------ | ------------------------------------------ |
| Integrity    | NIA2               | 128-NIA2 — AES-128 in CMAC mode           |
| Ciphering    | NEA0 or NEA2       | Depends on AMF priority and UE capability  |

### 12.4 Understanding Null Encryption (NEA0) and Null Integrity (NIA0)

| Algorithm | What it means                                                                      |
| --------- | ---------------------------------------------------------------------------------- |
| **NEA0**  | Null encryption — NAS messages are **not encrypted** (sent in cleartext)           |
| **NIA0**  | Null integrity — NAS messages are **not integrity protected** (no MAC)             |

> **Important**: In this lab, the AMF's `cipheringOrder` lists NEA2 first, with NEA0 as fallback. The actual selection depends on the negotiation. Check the UE logs for the definitive answer:
>
> ```
> [nas] [debug] Selected integrity[2] ciphering[0]
> ```
>
> - `integrity[2]` = NIA2 (AES-CMAC) — integrity **is** protected.
> - `ciphering[0]` = NEA0 (null) — encryption **is not** applied.

**What this means practically**:
- All NAS messages after SMC carry a **MAC (Message Authentication Code)** — any tampering is detected.
- NAS message **content is visible** in a packet capture (since NEA0 means no encryption).
- This is acceptable for a lab. In production, NEA2 (or NEA1/NEA3) should be enforced.

### 12.5 When Does NAS Protection Apply?

| NAS Message                       | Integrity | Encryption | Notes                                     |
| --------------------------------- | --------- | ---------- | ----------------------------------------- |
| Registration Request (initial)    | No        | No         | No security context yet                   |
| Authentication Request/Response   | No        | No         | Security context being established         |
| Security Mode Command             | Yes       | No         | AMF applies integrity; UE verifies         |
| Security Mode Complete            | Yes       | Yes*       | First message with full protection         |
| Registration Accept               | Yes       | Yes*       | Protected with negotiated algorithms       |
| PDU Session Establishment Req/Acc | Yes       | Yes*       | Protected under existing context           |
| Deregistration Request/Accept     | Yes       | Yes*       | Protected until session teardown           |

\* Encryption applies only if a non-null algorithm (NEA1/NEA2/NEA3) was negotiated.

### 12.6 UE Identity Protection (SUCI)

The UE never sends its SUPI (permanent identity) in cleartext over the air. Instead:

1. The UE encrypts the MSIN portion of SUPI using the **home network public key** → produces the **SUCI**.
2. The SUCI is sent in the Registration Request.
3. The UDM **de-conceals** SUCI → recovers SUPI using the corresponding private key.

Configuration in `uecfg.yaml`:

```yaml
protectionScheme: 1    # Profile A (ECIES with Curve25519)
homeNetworkPublicKeyId: 1
homeNetworkPublicKey: "5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650"
```

> **Why this matters**: Even if an attacker captures the Registration Request, they cannot extract the permanent subscriber identity without the home network's private key.

---

## Wireshark Capture Analysis

This section explains how to capture and analyze 5G signaling and data-plane traffic using Wireshark or tcpdump.

### Capture Setup

Capture traffic on the Docker bridge network to see all inter-container communication:

```bash
# Find the bridge interface name
docker network inspect free5gc-compose_privnet | grep "com.docker.network.bridge.name"
# Expected: "br-free5gc"

# Start a capture (run in a separate terminal)
sudo tcpdump -i br-free5gc -w ~/capture_5g.pcap
```

Alternatively, capture inside a specific container's network namespace:

```bash
# Capture N3 traffic (gNB ↔ UPF) from the UPF's perspective
docker run -d --name capture --net=container:upf \
  -v "$PWD/captures:/captures" nicolaka/netshoot \
  tcpdump -ni eth0 -w /captures/n3_capture.pcap

# Generate traffic, then stop capture
docker exec -it ueransim ping -c 10 -I uesimtun0 8.8.8.8
docker stop -t 1 capture && docker rm capture
```

### What to Look For in the Capture

Open the pcap in Wireshark and use these display filters:

#### 1. NGAP Messages (N2: gNB ↔ AMF)

```
ngap
```

You should see:
- **NGSetupRequest** / **NGSetupResponse**: gNB connecting to AMF.
- **InitialUEMessage**: UE's first Registration Request arriving at AMF.
- **DownlinkNASTransport** / **UplinkNASTransport**: NAS messages carried over NGAP.
- **InitialContextSetupRequest** / **Response**: AMF setting up UE context on gNB.
- **UEContextReleaseCommand** / **Complete**: Cleanup during deregistration.

#### 2. NAS Messages (UE ↔ AMF, carried inside NGAP)

```
nas-5gs
```

You should see:
- **Registration Request** (with SUCI — encrypted identity).
- **Authentication Request** (RAND, AUTN challenge).
- **Authentication Response** (RES*).
- **Security Mode Command** (selected algorithms).
- **Security Mode Complete**.
- **Registration Accept** (GUTI, allowed NSSAI).
- **PDU Session Establishment Request/Accept**.
- **Deregistration Request/Accept**.

> **Tip**: After the Security Mode Command, NAS messages will show integrity protection. If NEA0 is used, the NAS payload is still readable. If NEA2 is used, the payload appears encrypted.

#### 3. PFCP Packets (N4: SMF ↔ UPF)

```
pfcp
```

You should see:
- **PFCP Association Setup Request/Response**: SMF ↔ UPF handshake at startup.
- **PFCP Session Establishment Request/Response**: PDU session rules being installed.
- **PFCP Session Report Request/Response**: Usage reports from UPF to SMF.
- **PFCP Session Deletion Request/Response**: Cleanup during deregistration.

#### 4. GTP-U Packets (N3: gNB ↔ UPF)

```
gtp
```

You should see:
- **GTP-U** packets with inner IP payload (e.g., ICMP ping packets).
- TEID values identifying specific tunnels.
- The inner source IP is the UE's IP (10.60.0.x), and the inner destination is the external host (e.g., 8.8.8.8).

#### 5. Combined Filter — Full Session Lifecycle

```
ngap || nas-5gs || pfcp || gtp
```

### Expected Message Sequence in Wireshark

| # | Protocol | Message                              | Direction          |
|---|----------|--------------------------------------|--------------------|
| 1 | SCTP     | INIT / INIT-ACK / COOKIE             | gNB → AMF          |
| 2 | NGAP     | NGSetupRequest                       | gNB → AMF          |
| 3 | NGAP     | NGSetupResponse                      | AMF → gNB          |
| 4 | NGAP     | InitialUEMessage (Registration Req)  | gNB → AMF          |
| 5 | NAS      | Authentication Request               | AMF → UE           |
| 6 | NAS      | Authentication Response              | UE → AMF           |
| 7 | NAS      | Security Mode Command                | AMF → UE           |
| 8 | NAS      | Security Mode Complete               | UE → AMF           |
| 9 | NGAP     | InitialContextSetupRequest (Reg Acc) | AMF → gNB          |
| 10| NAS      | Registration Complete                | UE → AMF           |
| 11| NAS      | PDU Session Establishment Request    | UE → AMF → SMF     |
| 12| PFCP     | Session Establishment Request        | SMF → UPF          |
| 13| PFCP     | Session Establishment Response       | UPF → SMF          |
| 14| NAS      | PDU Session Establishment Accept     | SMF → AMF → UE     |
| 15| GTP-U    | User data (ICMP, HTTP, etc.)         | UE ↔ UPF           |
| 16| PFCP     | Session Report (usage)               | UPF → SMF          |
| 17| NAS      | Deregistration Request               | UE → AMF           |
| 18| PFCP     | Session Deletion Request             | SMF → UPF          |
| 19| PFCP     | Session Deletion Response            | UPF → SMF          |
| 20| NAS      | Deregistration Accept                | AMF → UE           |
| 21| NGAP     | UEContextReleaseCommand              | AMF → gNB          |

---

## NF Logs Reference

This section describes what to expect in the logs of each NF during the major procedures: **Registration**, **Authentication**, **PDU Session Establishment**, and **Deregistration**.

### How to View Logs

```bash
# View last 50 lines of a specific NF
docker compose logs --tail 50 <service-name>

# Follow logs in real time
docker compose logs -f <service-name>

# Filter logs since a time window
docker compose logs --since 2m <service-name>
```

### AMF Logs (`free5gc-amf`)

| Procedure        | Log Pattern                                                                 |
| ---------------- | --------------------------------------------------------------------------- |
| Registration     | `Handle Registration Request` → `Send Registration Accept`                 |
| Authentication   | `Send Authentication Request` → `Handle Authentication Response`            |
| Security Mode    | `Send Security Mode Command` → `Handle Security Mode Complete`              |
| PDU Session      | `Handle PDU Session Establishment Request` (forwards to SMF via N11)        |
| Deregistration   | `Handle Deregistration Request` → `UE Context Release`                      |

**Common error patterns**:
- `Authentication failed`: Key/OP/OPC mismatch between UE config and WebUI subscriber data.
- `T3560 expired`: AMF retransmission timer expired — UE did not respond to Auth/SMC.
- `unknown PLMN`: gNB's PLMN does not match AMF's `plmnSupportList`.

### SMF Logs (`free5gc-smf`)

| Procedure        | Log Pattern                                                                  |
| ---------------- | ---------------------------------------------------------------------------- |
| PDU Session Est. | `Handle PDU Session Establishment Request` → `Selected UPF` → `Sending PFCP`|
| PFCP Session     | `Sending PFCP Session Establishment Request` → `Received Response`           |
| Usage Reporting  | `build MultiUnitUsageFromUsageReport`                                        |
| Session Release  | `Receive Release SM Context Request` → `Sending PFCP Session Deletion`       |

**Common error patterns**:
- `PFCP Association failed`: UPF is not reachable or not started.
- `T3580 expired`: SMF retransmission timer expired — UPF did not respond to PFCP.
- `No available UPF`: No UPF matches the requested DNN/slice combination.

### UPF Logs (`free5gc-upf`)

| Procedure        | Log Pattern                                                                  |
| ---------------- | ---------------------------------------------------------------------------- |
| PFCP Association | `handleAssociationSetupRequest`                                              |
| Session Creation | `handleSessionEstablishmentRequest` → `New session` with CPSEID/UPSEID      |
| Usage Reporting  | `serveUSAReport` → `handleSessionReportResponse`                             |
| Session Deletion | `handleSessionDeletionRequest` → `sess deleted`                              |

**Common error patterns**:
- `open Gtp5g: operation not supported`: gtp5g kernel module not loaded.
- `PFCP heartbeat timeout`: SMF ↔ UPF communication lost.
- No logs after startup: Container may be crashing — check with `docker compose ps`.

### NRF Logs (`free5gc-nrf`)

| Procedure        | Log Pattern                                                                  |
| ---------------- | ---------------------------------------------------------------------------- |
| NF Registration  | `Handle NFRegisterRequest` for each NF (AMF, SMF, UPF, AUSF, etc.)         |
| NF Discovery     | `Handle NFDiscoveryRequest` when one NF looks up another                     |
| Heartbeat        | `Handle NFUpdate` — periodic keepalive from registered NFs                   |

**Common error patterns**:
- `NFRegister failed`: NF cannot reach NRF — check network connectivity and `nrfUri` config.
- `OAuth token validation failed`: Certificate mismatch if TLS is enabled.

### AUSF Logs (`free5gc-ausf`)

| Procedure        | Log Pattern                                                                  |
| ---------------- | ---------------------------------------------------------------------------- |
| Authentication   | `HandleUeAuthPostRequest` → `Use5gAkaComfirmRequest`                         |
| Success          | `5G AKA confirmation succeeded`                                              |

**Common error patterns**:
- `Authentication vector request failed`: Cannot reach UDM.
- `MAC failure`: Key mismatch between UE and subscriber database.

### UDM Logs (`free5gc-udm`)

| Procedure        | Log Pattern                                                                  |
| ---------------- | ---------------------------------------------------------------------------- |
| Auth Vector Gen. | `HandleGenerateAuthDataRequest` → generates RAND, AUTN, XRES*, KAUSF       |
| SUCI De-conceal  | `HandleDeconcealment` → recovers SUPI from SUCI                              |
| Subscriber Data  | `HandleGetAmData`, `HandleGetSmData`                                         |

**Common error patterns**:
- `SUCI de-concealment failed`: Profile A/B mismatch or wrong home network public key.
- `Subscriber not found`: SUPI not registered in WebUI/UDR.

---

## Troubleshooting

### Issue 1: Port Already in Use

**Symptom**: `docker compose up` fails with `bind: address already in use`.

**Fix**:

```bash
# Identify what is using the port
sudo ss -tlnp | grep <port>
sudo lsof -i :<port>

# Kill the offending process
sudo kill <PID>

# Or stop the Docker stack and remove old containers
docker compose down
docker compose up -d
```

### Issue 2: Docker Container Crashes (Restart Loop)

**Symptom**: A container shows `Restarting` in `docker compose ps`.

**Fix**:

```bash
# Check the crash logs
docker compose logs <container-name>

# Common causes:
# 1. gtp5g not loaded (UPF crash) → sudo modprobe gtp5g
# 2. MongoDB not ready (NRF/UDR crash) → wait and restart
# 3. Config file error → check YAML syntax in config/

# Force recreate
docker compose down
docker compose up -d
```

### Issue 3: Algorithm Mismatch (UE Cannot Register)

**Symptom**: UE logs show `Security Mode Command received` but registration fails, or AMF logs show `Algorithm negotiation failed`.

**Cause**: The AMF's `integrityOrder` or `cipheringOrder` does not overlap with the UE's supported algorithms.

**Fix**: Ensure at least one algorithm is common:

- AMF (`amfcfg.yaml`): `integrityOrder: [NIA2]`, `cipheringOrder: [NEA2, NEA0]`
- UE (`uecfg.yaml`): `integrity: {IA2: true}`, `ciphering: {EA2: true}`

Both support NIA2/NEA2, so negotiation succeeds.

### Issue 4: Profile A vs Profile B Mismatch

**Symptom**: UE registration fails at the authentication step. UDM logs show `SUCI de-concealment failed`.

**Cause**: The UE's `protectionScheme` and `homeNetworkPublicKey` do not match the UDM's configuration.

**Fix**: Verify both sides use the same SUCI protection profile:

```bash
# Check UE config
grep -A 3 "protectionScheme" config/uecfg.yaml

# Check UDM config (look for homeNetworkPublicKey settings)
docker compose logs free5gc-udm | grep -i "key\|profile\|scheme"
```

Ensure `protectionScheme`, `homeNetworkPublicKeyId`, and `homeNetworkPublicKey` are consistent.

### Issue 5: UE Not Registering

**Symptom**: UE logs show `Sending Initial Registration` but never receive `Registration Accept`.

**Checklist**:

```bash
# 1. Is the gNB connected to the AMF?
docker compose logs --since 2m ueransim | grep "NG Setup"
# Must show "NG Setup procedure is successful"

# 2. Is the AMF running?
docker compose ps free5gc-amf
# Must show "Up"

# 3. Does the PLMN match?
# gNB config (gnbcfg.yaml): mcc=208, mnc=93
# AMF config (amfcfg.yaml): mcc=208, mnc=93
# UE config (uecfg.yaml): mcc=208, mnc=93
# All three must match.

# 4. Is the subscriber provisioned?
# Check WebUI at http://localhost:5000
# SUPI: imsi-208930000000001 must exist with correct Key and OPC.

# 5. Check AMF logs for the specific error
docker compose logs --since 2m free5gc-amf | grep -i "error\|fail\|reject"
```

### Issue 6: SMF-UPF PFCP Failure

**Symptom**: UE registers but PDU session fails. SMF logs show `T3580 expired` or `PFCP Association failed`.

**Checklist**:

```bash
# 1. Is the UPF running?
docker compose ps free5gc-upf
# Must show "Up" (not "Restarting")

# 2. Is gtp5g loaded?
lsmod | grep gtp5g
# Must show "gtp5g"

# 3. Can SMF reach UPF?
docker exec free5gc-smf ping -c 2 upf.free5gc.org
# Must succeed

# 4. Check UPF logs for PFCP association
docker compose logs free5gc-upf | grep -i "association"
# Must show "handleAssociationSetupRequest"

# 5. Check SMF logs
docker compose logs free5gc-smf | grep -i "pfcp\|error"
```

### Issue 7: No Internet Connectivity After PDU Session

**Symptom**: `uesimtun0` is up and has an IP, but `ping -I uesimtun0 8.8.8.8` fails.

**Checklist**:

```bash
# 1. Verify the tunnel interface
docker exec ueransim ip a show uesimtun0
# Must show an IP like 10.60.0.x

# 2. Check if UPF has IP forwarding enabled
docker exec free5gc-upf sysctl net.ipv4.ip_forward
# Must be 1

# 3. Check iptables NAT rules in UPF
docker exec free5gc-upf iptables -t nat -L POSTROUTING -n -v
# Must show a MASQUERADE rule on eth0

# 4. Check if the host has IP forwarding
sysctl net.ipv4.ip_forward
# Must be 1. If not: sudo sysctl -w net.ipv4.ip_forward=1

# 5. Test DNS resolution via the tunnel
docker exec ueransim nslookup example.com
# If ping works by IP but not by name, it is a DNS issue

# 6. Check Docker's NAT
sudo iptables -t nat -L -n | grep 10.100.200
```

### Quick Diagnostic Commands Summary

| What to Check             | Command                                                     |
| ------------------------- | ----------------------------------------------------------- |
| All container status      | `docker compose ps`                                         |
| Specific NF logs          | `docker compose logs --tail 50 <service>`                   |
| gtp5g module              | `lsmod \| grep gtp5g`                                      |
| Network connectivity      | `docker exec <container> ping -c 2 <target>`               |
| Port usage                | `sudo ss -tlnp \| grep <port>`                             |
| Docker network            | `docker network inspect free5gc-compose_privnet`            |
| UE tunnel interface       | `docker exec ueransim ip a show uesimtun0`                  |
| UPF iptables              | `docker exec free5gc-upf iptables -t nat -L -n`            |
| Subscriber data           | WebUI at `http://localhost:5000`                            |

---

## Validation Checklist

**Before considering this lab complete, ask someone else (a classmate) to follow these steps from scratch and confirm they can:**

### Setup Validation

- [ ] Install Docker and Docker Compose on a fresh Ubuntu system
- [ ] Load the gtp5g kernel module without errors
- [ ] Clone the repository and start all containers
- [ ] See all containers in `Up` or `Up (healthy)` state
- [ ] Access the WebUI at `http://localhost:5000`

### Functional Validation

- [ ] Verify gNB NG Setup is successful (UERANSIM and AMF logs)
- [ ] Start UE and see successful registration
- [ ] Verify PDU session establishment (UE, SMF, and UPF logs)
- [ ] Ping 8.8.8.8 through `uesimtun0` with 0% packet loss
- [ ] Curl an HTTP endpoint through `uesimtun0`
- [ ] Trigger deregistration and verify PFCP session deletion in logs

### Conceptual Validation (Can the student explain?)

- [ ] What is the role of each NF (AMF, SMF, UPF, NRF, AUSF, UDM)?
- [ ] What interface connects the gNB to the AMF? (N2 / NGAP / SCTP)
- [ ] What is PFCP and what does it carry? (SMF → UPF forwarding rules)
- [ ] Why is GTP-U tunneling needed? (Mobility, separation of planes)
- [ ] What is the difference between NEA0 and NEA2? (Null vs AES encryption)
- [ ] What happens during deregistration? (PFCP session deletion, resource cleanup)

### Troubleshooting Validation

- [ ] Student can diagnose a "port already in use" error
- [ ] Student can check if gtp5g is loaded and load it if missing
- [ ] Student can identify which container is failing from `docker compose ps`
- [ ] Student can read NF logs to find the root cause of a registration failure

### Identifying Missing Steps

If the student gets stuck at any point:
1. Note which step was unclear.
2. Note what assumption was made that was not documented.
3. Update this document to fill the gap.

> **A guide is only as good as its ability to work for someone who did not write it.**
