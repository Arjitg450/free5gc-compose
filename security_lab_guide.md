# 5G Security Student Laboratory Guide

**Topic:** Verifying before-and-after NAS security behavior and UE identity protection (SUCI) in free5GC.

## 1. Lab Objective

In this lab, students demonstrate the difference between an insecure baseline and a secure Day 2 configuration on the VDI appliance.

The comparison is the point of the lab:

- **Before**: `NEA0` is prioritized and SUCI is disabled
- **After**: `NEA2` is prioritized and SUCI Profile A is enabled

## 2. Use the Day 2 runner script

Run this from inside the VDI after switching the repo to `bootcamp`:

```bash
cd /opt/free5gc-compose
bash script/day2-before-after.sh
```

The script:

1. backs up the secure config
2. runs the baseline comparison pass
3. captures `/tmp/day2_baseline_n2.pcap`
4. restores the secure config
5. runs the secure comparison pass
6. captures `/tmp/day2_secure_n2.pcap`
7. leaves the VDI back in the secure state

## 3. Verified Comparison Summary

These are the exact results verified on the VDI while testing this guide.

| Check | Baseline (Before) | Secure (After) |
| --- | --- | --- |
| UE algorithm line | `Selected integrity[2] ciphering[0]` | `Selected integrity[2] ciphering[2]` |
| AMF identity line | `suci-0-208-93-0000-0-0-0000000001` | `suci-0-208-93-0000-1-1-<encrypted blob>` |
| `strings` on N2-only pcap | prints `internet` | no output |
| Meaning | integrity only, no NAS ciphering | integrity plus NAS ciphering |

## 4. Prerequisites

- VDI accessible and logged in as `ubuntu`
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

## 5. Why host capture is required on this VDI

Do not rely on `tcpdump` inside the `ueransim` container for this VDI image.

Use host capture on `br-free5gc` instead. For a clean NAS comparison, capture only the N2 path between:

- gNB: `10.100.200.12`
- AMF: `10.100.200.16`

That avoids mixing in unrelated SBI/HTTP traffic from the rest of the core.

## 6. Inspect the proof after the script runs

Run:

```bash
docker exec ueransim grep -E 'Selected integrity|Initial Registration is successful|PDU Session establishment is successful' /tmp/ue_baseline.log /tmp/ue_secure.log
docker compose logs --since 5m free5gc-amf | grep -E 'MobileIdentity5GS|Authentication|Security Mode|Registration'
strings /tmp/day2_baseline_n2.pcap | grep internet
strings /tmp/day2_secure_n2.pcap | grep internet
ls -lh /tmp/day2_baseline_n2.pcap /tmp/day2_secure_n2.pcap
```

Expected:

- baseline log shows `ciphering[0]`
- secure log shows `ciphering[2]`
- baseline pcap prints `internet`
- secure pcap prints no `internet`

## 7. Success Criteria

The lab is successful when all of these are true:

- baseline run completed registration and PDU setup
- secure run completed registration and PDU setup
- baseline run showed `ciphering[0]`
- secure run showed `ciphering[2]`
- baseline capture printed `internet`
- secure capture printed nothing for `grep internet`

## 8. Cleanup

The script already restores the secure config before it exits. If needed, you can re-verify the final secure state with:

```bash
cd /opt/free5gc-compose
self-test.sh
docker restart amf ueransim
sleep 8
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue_final_verify.log 2>&1 &'
sleep 12
docker exec ueransim grep -E 'Selected integrity|Initial Registration is successful|PDU Session establishment is successful' /tmp/ue_final_verify.log
```
