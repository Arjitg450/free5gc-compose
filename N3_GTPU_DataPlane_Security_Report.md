# free5GC N3 (gNB ↔ UPF) Data-Plane Security Verification Report

Date: 2026-01-23

## 1. Objective

Determine whether this **free5GC + UERANSIM** deployment provides **data-plane security** (confidentiality/integrity) for **GTP-U user-plane traffic** on the **N3 interface** (between **RAN/gNB** and **UPF**).

Concretely, we check whether N3 traffic is:
- **Plain GTP-U over UDP/2152** (no transport protection), or
- Protected by **IPsec (NDS/IP)** (would appear as **ESP** and/or IKE traffic instead of exposed UDP/2152 flows on the transport network).

## 2. Environment

Workspace: `free5gc-compose/`

Deployment method:
- `docker compose up -d`

Relevant containers:
- `upf` (image: `free5gc/upf:v4.1.0`)
- `ueransim` (image: `free5gc/ueransim:latest`)

Docker network:
- `free5gc-compose_privnet` (bridge `br-free5gc`, subnet `10.100.200.0/24`)

Relevant IPs:
- UPF: `10.100.200.3`
- UERANSIM gNB: `10.100.200.13`

UERANSIM configs:
- gNB: `config/gnbcfg.yaml`
- UE: `config/uecfg.yaml` (APN `internet`)

## 3. Standards context (official 3GPP references)

- **3GPP TS 33.501**: 5G security architecture and procedures. User-plane confidentiality/integrity is primarily handled on the radio side (e.g., PDCP). Network domain protection for inter-node IP transport is addressed separately.
- **3GPP TS 33.210**: **NDS/IP (Network Domain Security for IP networks)**, typically implemented with **IPsec** between network elements when protection is required over untrusted transport.

Important: **GTP-U does not itself provide encryption/integrity at the transport layer**. If N3 requires protection in a non-trusted network, a typical approach is **IPsec (NDS/IP)** (or other transport/network-layer mechanisms) between endpoints.

## 4. Verification method

We verify N3 protection by combining:
1) **Traffic generation**: create an active user-plane flow by establishing a UE PDU session and running ping.
2) **Packet capture**: capture N3 traffic during the user-plane flow.
3) **Protocol indicators**:
   - Unprotected N3 should show **UDP/2152** packets between gNB and UPF.
   - IPsec-protected N3 would typically show **ESP (IP protocol 50)** and/or **IKE** (UDP/500, UDP/4500).

## 5. Steps performed (commands)

### 5.1 Create a UE PDU session (UERANSIM)

The compose service starts the gNB (`nr-gnb`). A UE (`nr-ue`) was started in the same container:

```bash
docker exec -d ueransim sh -lc "./nr-ue -c ./config/uecfg.yaml > /tmp/nr-ue.log 2>&1"
```

UE log confirms:
- Registration succeeded
- PDU session(s) established
- Tunnel interface created:
  - `uesimtun0` with IP `10.60.0.1`

### 5.2 Generate user-plane traffic

```bash
# ICMP traffic via UE tunnel
ping -I uesimtun0 -c 8 8.8.8.8
```

Observed:
- 8/8 replies (active user-plane)

### 5.3 Capture N3 traffic to a pcap

Capture was executed in the UPF network namespace using a temporary container:

```bash
# Start capture in UPF netns
docker run -d --name gtp-capture --net=container:upf \
  -v "$PWD/captures:/captures" nicolaka/netshoot sh -lc \
  "tcpdump -ni eth0 '(host 10.100.200.13 and udp port 2152) or proto 50 or udp port 500 or udp port 4500' -w /captures/gtpu_n3_test.pcap"

# Generate traffic while capture runs
ping -I uesimtun0 -c 8 8.8.8.8

# Stop capture
docker stop -t 1 gtp-capture && docker rm gtp-capture
```

Output artifact:
- `captures/gtpu_n3_test.pcap`

## 6. Results

### 6.1 N3 shows exposed UDP/2152 packets between gNB and UPF

The pcap contains packets of the form:
- `10.100.200.13:2152 → 10.100.200.3:2152` (UDP)
- `10.100.200.3:2152 → 10.100.200.13:2152` (UDP)

This is consistent with **plain GTP-U over UDP/2152** on N3.

### 6.2 No IPsec indicators observed in the capture filter

The capture also matched:
- ESP: `proto 50`
- IKE: `udp/500`
- NAT-T: `udp/4500`

No ESP/IKE packets were observed in this capture; the recorded traffic is UDP/2152 between gNB and UPF.

## 7. Artifact integrity (pcap metadata)

File: `captures/gtpu_n3_test.pcap`

- Packets: 14
- Capture duration: ~6 seconds
- SHA-256: `6fa18ef29d243869063a6e97937f6c6bcab38f8b47d7704e42de8cb57274b8c3`

## 8. How to confirm in Wireshark

Open:
- `captures/gtpu_n3_test.pcap`

Filters to apply:

1) Show N3 UDP/2152 traffic:

```text
(ip.addr == 10.100.200.3 && ip.addr == 10.100.200.13) && udp.port == 2152
```

2) Check for IPsec ESP:

```text
esp
```

3) Check for IKE/NAT-T:

```text
udp.port == 500 || udp.port == 4500
```

Expected for this setup:
- Filter (1) shows packets
- Filters (2) and (3) show none

## 9. Conclusion

For this free5GC + UERANSIM docker-compose deployment, **N3 user-plane traffic between gNB and UPF is carried as plain GTP-U over UDP/2152**. The capture does **not** show IPsec (ESP/IKE), so **data-plane transport protection for N3 is not enabled** in this setup.
