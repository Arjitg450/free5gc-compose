# Day 2 VDI Student Guide

This guide is only for Day 2 on the VDI appliance. It covers:

- switching the repo to `bootcamp`
- verifying the core is running
- running the UE attach for Day 2
- proving that authentication and NAS security are working

Use this on the VDI server exposed on `127.0.0.1:2222`.

## 1. Connect to the VDI

From your host machine:

```bash
ssh -F NUL -p 2222 ubuntu@127.0.0.1
```

Password:

```text
free5gc
```

## 2. Recover the VDI network and sync the repo

If the VDI came up without a usable IP or the repo is owned by `root`, run this first:

```bash
sudo ip link set enp0s3 up
sudo dhclient -v enp0s3
ip -4 -br a show enp0s3
cd /opt/free5gc-compose
sudo chown -R ubuntu:ubuntu /opt/free5gc-compose
git fetch origin
git switch bootcamp || git switch -c bootcamp --track origin/bootcamp
git reset --hard origin/bootcamp
```

Expected:

- `enp0s3` has an IPv4 address
- the repo is writable by `ubuntu`
- `git rev-parse --abbrev-ref HEAD` prints `bootcamp`

If you later need the IEEE branch instead of Day 2 bootcamp, swap `bootcamp` for `feat/ieee-10175424` in the `git switch` and `git reset --hard` commands.

## 3. Switch to the bootcamp branch

On this VDI image, `branch-switch.sh` is present but not executable as a standalone command. Run it through `bash`.

```bash
cd /opt/free5gc-compose
echo free5gc | sudo -S bash /opt/free5gc-compose/ovf/scripts/branch-switch.sh bootcamp
```

Confirm the branch:

```bash
cd /opt/free5gc-compose
git rev-parse --abbrev-ref HEAD
```

Expected:

```text
bootcamp
```

## 4. Verify the stack is running

Run:

```bash
cd /opt/free5gc-compose
self-test.sh
docker compose ps
```

Expected:

- `self-test.sh` prints `PASS`
- the core containers show `Up`
- the `ueransim` container is running

## 5. Confirm the Day 2 security config

Run:

```bash
cd /opt/free5gc-compose
grep -n -A5 'security:' config/amfcfg.yaml
echo '---'
grep -n 'protectionScheme\|homeNetworkPublicKeyId\|homeNetworkPublicKey' config/uecfg.yaml
```

You should see:

- `NIA2` in `integrityOrder`
- `NEA2` before `NEA0` in `cipheringOrder`
- `protectionScheme: 1`
- `homeNetworkPublicKeyId: 1`

## 6. Run the Day 2 UE attach

Restart AMF and gNB first so the logs are clean:

```bash
cd /opt/free5gc-compose
docker restart amf ueransim
sleep 8
```

Start the UE:

```bash
cd /opt/free5gc-compose
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue.log 2>&1 &'
sleep 12
```

Check the UE log:

```bash
docker exec ueransim tail -n 80 /tmp/ue.log
```

Expected proof in the UE log:

```text
Authentication Request received
Received SQN [...]
Security Mode Command received
Selected integrity[2] ciphering[2]
Initial Registration is successful
PDU Session establishment is successful
```

What this means:

- `integrity[2]` means `NIA2`
- `ciphering[2]` means `NEA2`
- the UE was authenticated and NAS ciphering was enabled

## 7. Check the AMF proof

Run:

```bash
cd /opt/free5gc-compose
docker compose logs --since 3m free5gc-amf | grep -E 'SUCI|Registration|Authentication|Security Mode'
```

Expected proof in AMF logs:

```text
MobileIdentity5GS: SUCI[...]
Send Authentication Request
Handle Authentication Response
Send Security Mode Command
Handle Security Mode Complete
Send Registration Accept
Handle Registration Complete
```

What this proves:

- the UE identity arrived as SUCI, not cleartext IMSI
- the AMF executed authentication
- the AMF completed the NAS security mode procedure

## 8. Capture clean proof on the VDI host

Important:

- do not capture the full bridge and then grep for `internet`
- the full bridge also carries internal HTTP/SBI traffic, which includes the word `internet`
- for Day 2 proof, capture only the N2 path between gNB and AMF

Restart AMF and gNB again:

```bash
cd /opt/free5gc-compose
docker restart amf ueransim
sleep 8
```

Start an N2-only capture on the VDI host:

```bash
echo free5gc | sudo -S bash -lc 'rm -f /tmp/day2_n2_only.pcap /tmp/day2_n2_only.pid /tmp/day2_n2_only.log; nohup tcpdump -i br-free5gc -w /tmp/day2_n2_only.pcap host 10.100.200.12 and host 10.100.200.16 >/tmp/day2_n2_only.log 2>&1 & echo $! >/tmp/day2_n2_only.pid'
```

Trigger the UE attach:

```bash
cd /opt/free5gc-compose
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue.log 2>&1 &'
sleep 20
```

Stop the capture:

```bash
echo free5gc | sudo -S bash -lc 'kill $(cat /tmp/day2_n2_only.pid)'
```

Check the proof:

```bash
ls -lh /tmp/day2_n2_only.pcap
strings /tmp/day2_n2_only.pcap | grep internet
sudo tcpdump -nn -r /tmp/day2_n2_only.pcap -c 20
```

Expected:

- the pcap file exists and is non-zero in size
- `strings /tmp/day2_n2_only.pcap | grep internet` prints no output
- `tcpdump -nn -r /tmp/day2_n2_only.pcap -c 20` shows SCTP packets between:
  - `10.100.200.12`
  - `10.100.200.16`

Why this matters:

- the UE still requested a PDU session
- but in the N2-only capture, the readable `internet` string is not visible
- that is the clean proof that the NAS content is no longer exposed in plain text on the control path being tested

## 9. What students should conclude

If all checks above pass, students have proved:

1. the VDI is on the `bootcamp` branch
2. the free5GC stack is healthy
3. the UE completed authentication successfully
4. the AMF saw a SUCI, not a clear IMSI
5. the Security Mode procedure completed
6. the UE negotiated `NIA2` plus `NEA2`
7. the N2 capture does not expose the `internet` string in plain text

That is the Day 2 proof that authentication and NAS security are working.

## 10. One-command proof checklist

If you only want the shortest command set, run these in order:

```bash
cd /opt/free5gc-compose
echo free5gc | sudo -S bash /opt/free5gc-compose/ovf/scripts/branch-switch.sh bootcamp
self-test.sh
docker restart amf ueransim
sleep 8
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue.log 2>&1 &'
sleep 12
docker exec ueransim tail -n 80 /tmp/ue.log
docker compose logs --since 3m free5gc-amf | grep -E 'SUCI|Registration|Authentication|Security Mode'
echo free5gc | sudo -S bash -lc 'rm -f /tmp/day2_n2_only.pcap /tmp/day2_n2_only.pid /tmp/day2_n2_only.log; nohup tcpdump -i br-free5gc -w /tmp/day2_n2_only.pcap host 10.100.200.12 and host 10.100.200.16 >/tmp/day2_n2_only.log 2>&1 & echo $! >/tmp/day2_n2_only.pid'
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue.log 2>&1 &'
sleep 20
echo free5gc | sudo -S bash -lc 'kill $(cat /tmp/day2_n2_only.pid)'
strings /tmp/day2_n2_only.pcap | grep internet
sudo tcpdump -nn -r /tmp/day2_n2_only.pcap -c 20
```

