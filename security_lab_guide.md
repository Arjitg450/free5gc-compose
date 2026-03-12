# 5G Security Student Laboratory Guide

**Topic:** Verifying before-and-after NAS security behavior and UE identity protection (SUCI) in free5GC.

## 1. Lab Objective

In this lab, students demonstrate the difference between an insecure baseline and a secure Day 2 configuration on the VDI appliance.

The comparison is the point of the lab:

- **Before**: `NEA0` is prioritized and SUCI is disabled
- **After**: `NEA2` is prioritized and SUCI Profile A is enabled

## 2. Verified Comparison Summary

These are the exact results verified on the VDI while testing this guide.

| Check | Baseline (Before) | Secure (After) |
| --- | --- | --- |
| UE algorithm line | `Selected integrity[2] ciphering[0]` | `Selected integrity[2] ciphering[2]` |
| AMF identity line | `suci-0-208-93-0000-0-0-0000000001` | `suci-0-208-93-0000-1-1-<encrypted blob>` |
| `strings` on N2-only pcap | prints `internet` | no output |
| Meaning | integrity only, no NAS ciphering | integrity plus NAS ciphering |

## 3. Prerequisites

- VDI accessible with `ssh -F NUL -p 2222 ubuntu@127.0.0.1`
- password `free5gc`
- `bootcamp` branch checked out on `/opt/free5gc-compose`
- Docker stack healthy

Recommended startup commands:

```bash
sudo ip link set enp0s3 up
sudo dhclient -v enp0s3
ip -4 -br a show enp0s3
cd /opt/free5gc-compose
sudo chown -R ubuntu:ubuntu /opt/free5gc-compose
git fetch origin
git switch bootcamp || git switch -c bootcamp --track origin/bootcamp
git reset --hard origin/bootcamp
echo free5gc | sudo -S bash /opt/free5gc-compose/ovf/scripts/branch-switch.sh bootcamp
self-test.sh
docker compose ps
```

## 4. Why host capture is required on this VDI

Do not rely on `tcpdump` inside the `ueransim` container for this VDI image.

Use host capture on `br-free5gc` instead. For a clean NAS comparison, capture only the N2 path between:

- gNB: `10.100.200.12`
- AMF: `10.100.200.16`

That avoids mixing in unrelated SBI/HTTP traffic from the rest of the core.

## 5. Part 1: Baseline Configuration (Before)

### Step 5.1: Back up the secure config

```bash
cd /opt/free5gc-compose
cp config/amfcfg.yaml /tmp/amfcfg.day2.bak
cp config/uecfg.yaml /tmp/uecfg.day2.bak
```

### Step 5.2: Configure AMF for null encryption

```bash
cd /opt/free5gc-compose
python3 - <<'PY'
from pathlib import Path
p = Path('config/amfcfg.yaml')
s = p.read_text()
s = s.replace(
    "    cipheringOrder: # the priority of ciphering algorithms\n      - NEA2\n      - NEA0",
    "    cipheringOrder: # the priority of ciphering algorithms\n      - NEA0\n      - NEA2",
)
p.write_text(s)
PY
```

### Step 5.3: Disable SUCI protection in the UE config

```bash
cd /opt/free5gc-compose
python3 - <<'PY'
from pathlib import Path
p = Path('config/uecfg.yaml')
s = p.read_text()
s = s.replace('\nprotectionScheme: 1\n', '\n# protectionScheme: 1\n')
s = s.replace('\nhomeNetworkPublicKeyId: 1\n', '\n# homeNetworkPublicKeyId: 1\n')
s = s.replace(
    '\nhomeNetworkPublicKey: "5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650"\n',
    '\n# homeNetworkPublicKey: "5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650"\n',
)
p.write_text(s)
PY
```

### Step 5.4: Run and capture the baseline proof

```bash
cd /opt/free5gc-compose
docker restart amf ueransim
sleep 8
echo free5gc | sudo -S bash -lc 'rm -f /tmp/day2_baseline_n2.pcap /tmp/day2_baseline_n2.pid /tmp/day2_baseline_n2.log; nohup tcpdump -i br-free5gc -w /tmp/day2_baseline_n2.pcap host 10.100.200.12 and host 10.100.200.16 >/tmp/day2_baseline_n2.log 2>&1 & echo $! >/tmp/day2_baseline_n2.pid'
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue_baseline.log 2>&1 &'
sleep 20
echo free5gc | sudo -S bash -lc 'kill $(cat /tmp/day2_baseline_n2.pid)'
```

### Step 5.5: Verify the baseline proof

```bash
docker exec ueransim tail -n 40 /tmp/ue_baseline.log
docker compose logs --since 3m free5gc-amf | grep -E 'SUCI|Registration|Authentication|Security Mode|MobileIdentity5GS'
strings /tmp/day2_baseline_n2.pcap | grep internet
```

Expected baseline proof:

- UE log contains `Selected integrity[2] ciphering[0]`
- AMF log contains `MobileIdentity5GS: SUCI[suci-0-208-93-0000-0-0-0000000001]`
- `strings /tmp/day2_baseline_n2.pcap | grep internet` prints `internet`

## 6. Part 2: Secure Configuration (After)

### Step 6.1: Restore the original secure config

```bash
cd /opt/free5gc-compose
cp /tmp/amfcfg.day2.bak config/amfcfg.yaml
cp /tmp/uecfg.day2.bak config/uecfg.yaml
```

### Step 6.2: Run and capture the secure proof

```bash
cd /opt/free5gc-compose
docker restart amf ueransim
sleep 8
echo free5gc | sudo -S bash -lc 'rm -f /tmp/day2_secure_n2.pcap /tmp/day2_secure_n2.pid /tmp/day2_secure_n2.log; nohup tcpdump -i br-free5gc -w /tmp/day2_secure_n2.pcap host 10.100.200.12 and host 10.100.200.16 >/tmp/day2_secure_n2.log 2>&1 & echo $! >/tmp/day2_secure_n2.pid'
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue_secure.log 2>&1 &'
sleep 20
echo free5gc | sudo -S bash -lc 'kill $(cat /tmp/day2_secure_n2.pid)'
```

### Step 6.3: Verify the secure proof

```bash
docker exec ueransim tail -n 40 /tmp/ue_secure.log
docker compose logs --since 3m free5gc-amf | grep -E 'SUCI|Registration|Authentication|Security Mode|MobileIdentity5GS'
strings /tmp/day2_secure_n2.pcap | grep internet
```

Expected secure proof:

- UE log contains `Selected integrity[2] ciphering[2]`
- AMF log contains `MobileIdentity5GS: SUCI[suci-0-208-93-0000-1-1-...]`
- `strings /tmp/day2_secure_n2.pcap | grep internet` prints no output

## 7. Final Before/After Check

Run these together to show the comparison cleanly:

```bash
docker exec ueransim grep -E 'Selected integrity|Initial Registration is successful|PDU Session establishment is successful' /tmp/ue_baseline.log /tmp/ue_secure.log
strings /tmp/day2_baseline_n2.pcap | grep internet
strings /tmp/day2_secure_n2.pcap | grep internet
ls -lh /tmp/day2_baseline_n2.pcap /tmp/day2_secure_n2.pcap
```

Students should be able to explain:

1. Why `ciphering[0]` means the baseline is weak
2. Why `ciphering[2]` means the secure run is protected
3. Why scheme `0` reveals the clear subscriber identity form
4. Why scheme `1` conceals the identity using SUCI Profile A
5. Why the DNN string is visible before but not after

## 8. Success Criteria

The lab is successful when all of these are true:

- baseline run completed registration and PDU setup
- secure run completed registration and PDU setup
- baseline run showed `ciphering[0]`
- secure run showed `ciphering[2]`
- baseline capture printed `internet`
- secure capture printed nothing for `grep internet`

## 9. Cleanup

After the comparison, keep the secure config in place:

```bash
cd /opt/free5gc-compose
cp /tmp/amfcfg.day2.bak config/amfcfg.yaml
cp /tmp/uecfg.day2.bak config/uecfg.yaml
docker restart amf ueransim
sleep 8
self-test.sh
```
