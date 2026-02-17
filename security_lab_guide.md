# 5G Security Student Laboratory Guide

**Topic:** Verifying NAS Security (Encryption) and UE Identity Protection (SUCI) in free5GC.

## 1. Lab Objective

In this lab, you will demonstrate the difference between an **Insecure (Baseline)** 5G network and a **Secure** 5G network. You will configure the AMF and UE to switch between these states and capture network traffic (PCAP) to prove that security features are working.

## 2. Prerequisites

* **Environment**: A working instance of `free5gc-compose` with `ueransim`.
* **Tools**: `docker`, `docker-compose`, `tcpdump` (inside containers), `wireshark` or `tshark`.

---

## 3. Part 1: Baseline Configuration (The "Vulnerable" Setup)

### Step 3.1: Configure AMF for Null Encryption

Open `config/amfcfg.yaml`. Locate the `security` section and prioritize `NEA0` (Null Encryption).

```yaml
  security:
    integrityOrder:
      - NIA2
    cipheringOrder:
      - NEA0  # <-- Priority 1: Null Encryption (No Security)
      - NEA2
```

### Step 3.2: Configure UE to Disable Protection

Open `config/uecfg.yaml`. Comment out or remove the SUCI protection parameters.

```yaml
# SUCI Protection Scheme
# protectionScheme: 1
# homeNetworkPublicKeyId: 1
# homeNetworkPublicKey: "..."
```

### Step 3.3: Run & Capture Evidence

Run the following commands to start the capture and register the UE.

```bash
# 1. Restart Core Network & UE Simulator
cd free5gc-compose
docker restart amf ueransim

# 2. Start Packet Capture (Background)
# We capture on 'any' interface inside the UE container to see the traffic.
docker exec ueransim tcpdump -i any -w /ueransim/baseline.pcap &

# 3. Register the UE
docker exec ueransim ./nr-ue -c ./config/uecfg.yaml

# 4. Stop Capture (After registration completes ~10s)
docker exec ueransim pkill tcpdump
docker cp ueransim:/ueransim/baseline.pcap captures/baseline.pcap
```

### Step 3.4: Verification (The "Leak")

**Evidence 1: Cleartext Identity (IMSI)**

* **Log**: Check `captures/amf_baseline.log`. You will see `MobileIdentity5GS: SUPI[imsi-20893...]`.
* **Wireshark**: Open `baseline.pcap`. Filter: `nas_5gs.mm.message_type == 0x41` (Registration Request).
  * Expand `5GS Mobile Identity`.
  * **Observation**: `Protection scheme Id: NULL scheme (0)`.
  * **Result**: The IMSI (Subscriber ID) is visible in plain text.

**Evidence 2: Readable Data ("internet")**

* **Command Line Test**: Run `strings captures/baseline.pcap | grep "internet"`.
* **Result**: You will see the word `internet` printed multiple times. This confirms user activity (requesting the "internet" slice) is readable.

---

## 4. Part 2: Secure Configuration (The "Protected" Setup)

### Step 4.1: Configure AMF for AES Encryption

Open `config/amfcfg.yaml`. Change `cipheringOrder` to prioritize `NEA2` (AES-128).

```yaml
    cipheringOrder:
      - NEA2  # <-- Priority 1: AES 128-bit Encryption
      - NEA0
```

### Step 4.2: Configure UE for SUCI (Identity Protection)

Open `config/uecfg.yaml`. Enable Profile A using the Public Key from `udmcfg.yaml`.

```yaml
# SUCI Protection Scheme
protectionScheme: 1 # Profile A
# Home Network Public Key ID (matching UDM)
homeNetworkPublicKeyId: 1
# Home Network Public Key (Profile A from UDM)
homeNetworkPublicKey: "5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650"
```

### Step 4.3: Run & Capture Evidence

Repeat the execution steps from Part 1, but save the file as `secure.pcap`.

```bash
docker restart amf ueransim
docker exec ueransim tcpdump -i any -w /ueransim/secure.pcap &
docker exec ueransim ./nr-ue -c ./config/uecfg.yaml
# ... (wait 10s) ...
docker exec ueransim pkill tcpdump
docker cp ueransim:/ueransim/secure.pcap captures/secure.pcap
```

### Step 4.4: Verification (The "Shield")

**Evidence 1: Concealed Identity (SUCI)**

* **Log**: Check AMF/UE logs. You will see `MobileIdentity5GS: SUCI[...]`.
* **Wireshark**: Open `secure.pcap`. Filter: `nas_5gs.mm.suci.scheme_id`.
  * **Observation**: Value is `1` (ECIES Profile A).
  * **Result**: The IMSI is hidden. You only see a random `Scheme output` blob.

**Evidence 2: Hidden Data (No "internet")**

* **Command Line Test**: Run `strings captures/secure.pcap | grep "internet"`.
* **Result**: **NO OUTPUT**. The text "internet" has been encrypted into random bytes.

---

## 5. Reference: What Success Looks Like

### A. Wireshark Packet Detail: Registration Request

**Baseline (Insecure)**

```text
5GS mobile identity
    .000 .... = SUPI format: IMSI (0)
    .... .000 = Protection scheme Id: NULL scheme (0)  <-- VULNERABLE
    Mobile Country Code (MCC): 208
    Identity: 0000000001 (Cleartext)
```

**Secure (Protected)**

```text
5GS mobile identity
    .... .001 = Type of identity: SUCI (1)             <-- SECURE
    .... 0001 = Protection scheme Id: ECIES scheme profile A (1)
    Scheme output: a02b905a... (Encrypted Ciphertext)
```

### B. Wireshark Packet Detail: Security Mode Command

**Baseline (Insecure)**

```text
NAS security algorithms
    Type of ciphering algorithm: 5G-EA0 (null) (0)     <-- NO ENCRYPTION
```

**Secure (Protected)**

```text
NAS security algorithms

### C. Actual AMF Log Evidence (Traceability)

**Baseline (Insecure) Log:**
> From `amf_baseline.log`. Note the Cleartext SUPI.
```text
[INFO][AMF][Gmm] ... RegistrationType: Initial Registration
[INFO][AMF][Gmm] ... MobileIdentity5GS: SUCI[suci-0-208-93-0000-0-0-0000000001]
                                          ^-- Scheme 0 (Null)      ^-- Identity (Cleartext)
```

**Secure (Protected) Log:**
> From `amf_secure.log`. Note the Encrypted SUCI.

```text
[INFO][AMF][Gmm] ... RegistrationType: Initial Registration
[INFO][AMF][Gmm] ... MobileIdentity5GS: SUCI[suci-0-208-93-0000-1-0-1abad1c69619...]
                                          ^-- Scheme 1 (Profile A) ^-- Identity (Encrypted Blob)
```
