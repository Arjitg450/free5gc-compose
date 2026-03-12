# Day 2 VDI Student Guide

This guide is only for Day 2 on the VDI appliance. It covers:

- switching the repo to `bootcamp`
- verifying the core is running
- showing a before/after comparison between baseline and secure behavior
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

## 5. Confirm the secure Day 2 default config

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

## 6. Before vs After Comparison

This is the comparison students should be able to show after running both modes.

| Check | Baseline (Before) | Secure (After) |
| --- | --- | --- |
| AMF ciphering priority | `NEA0` first | `NEA2` first |
| UE identity protection | SUCI disabled | SUCI Profile A enabled |
| UE log selection | `Selected integrity[2] ciphering[0]` | `Selected integrity[2] ciphering[2]` |
| AMF identity line | `suci-0-208-93-0000-0-0-0000000001` | `suci-0-208-93-0000-1-1-<encrypted blob>` |
| `strings` on N2-only capture | prints `internet` | no output |

Verified on the VDI during testing:

- baseline UE log: `Selected integrity[2] ciphering[0]`
- secure UE log: `Selected integrity[2] ciphering[2]`
- baseline N2-only pcap: `strings /tmp/day2_baseline_n2.pcap | grep internet` printed `internet`
- secure N2-only pcap: `strings /tmp/day2_secure_n2.pcap | grep internet` printed nothing

## 7. Run the baseline comparison pass

This temporarily downgrades Day 2 so students can see the insecure behavior first.

```bash
cd /opt/free5gc-compose
cp config/amfcfg.yaml /tmp/amfcfg.day2.bak
cp config/uecfg.yaml /tmp/uecfg.day2.bak
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
docker restart amf ueransim
sleep 8
echo free5gc | sudo -S bash -lc 'rm -f /tmp/day2_baseline_n2.pcap /tmp/day2_baseline_n2.pid /tmp/day2_baseline_n2.log; nohup tcpdump -i br-free5gc -w /tmp/day2_baseline_n2.pcap host 10.100.200.12 and host 10.100.200.16 >/tmp/day2_baseline_n2.log 2>&1 & echo $! >/tmp/day2_baseline_n2.pid'
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue_baseline.log 2>&1 &'
sleep 20
echo free5gc | sudo -S bash -lc 'kill $(cat /tmp/day2_baseline_n2.pid)'
docker exec ueransim tail -n 40 /tmp/ue_baseline.log
docker compose logs --since 3m free5gc-amf | grep -E 'SUCI|Registration|Authentication|Security Mode|MobileIdentity5GS'
strings /tmp/day2_baseline_n2.pcap | grep internet
```

Expected baseline proof:

- UE log shows `Selected integrity[2] ciphering[0]`
- AMF log shows `MobileIdentity5GS: SUCI[suci-0-208-93-0000-0-0-0000000001]`
- `strings /tmp/day2_baseline_n2.pcap | grep internet` prints `internet`

## 8. Restore secure mode and run the Day 2 secure pass

Restore the original secure config first:

```bash
cd /opt/free5gc-compose
cp /tmp/amfcfg.day2.bak config/amfcfg.yaml
cp /tmp/uecfg.day2.bak config/uecfg.yaml
```

Then run the secure pass:

```bash
cd /opt/free5gc-compose
docker restart amf ueransim
sleep 8
echo free5gc | sudo -S bash -lc 'rm -f /tmp/day2_secure_n2.pcap /tmp/day2_secure_n2.pid /tmp/day2_secure_n2.log; nohup tcpdump -i br-free5gc -w /tmp/day2_secure_n2.pcap host 10.100.200.12 and host 10.100.200.16 >/tmp/day2_secure_n2.log 2>&1 & echo $! >/tmp/day2_secure_n2.pid'
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue_secure.log 2>&1 &'
sleep 20
echo free5gc | sudo -S bash -lc 'kill $(cat /tmp/day2_secure_n2.pid)'
docker exec ueransim tail -n 40 /tmp/ue_secure.log
docker compose logs --since 3m free5gc-amf | grep -E 'SUCI|Registration|Authentication|Security Mode|MobileIdentity5GS'
strings /tmp/day2_secure_n2.pcap | grep internet
```

Expected secure proof:

- UE log shows `Selected integrity[2] ciphering[2]`
- AMF log shows `MobileIdentity5GS: SUCI[suci-0-208-93-0000-1-1-...]`
- `strings /tmp/day2_secure_n2.pcap | grep internet` prints no output

## 9. Run the Day 2 secure attach only

If you only want the final secure Day 2 attach and not the full comparison, use the secure defaults and run:

```bash
cd /opt/free5gc-compose
docker restart amf ueransim
sleep 8
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue.log 2>&1 &'
sleep 12
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

## 10. Check the AMF proof

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

## 11. Capture clean proof on the VDI host

Important:

- do not capture the full bridge and then grep for `internet`
- the full bridge also carries internal HTTP/SBI traffic, which includes the word `internet`
- for Day 2 proof, capture only the N2 path between gNB and AMF

Use either `/tmp/day2_baseline_n2.pcap` or `/tmp/day2_secure_n2.pcap` from the comparison steps above.

Check the proof:

```bash
ls -lh /tmp/day2_baseline_n2.pcap /tmp/day2_secure_n2.pcap
strings /tmp/day2_baseline_n2.pcap | grep internet
strings /tmp/day2_secure_n2.pcap | grep internet
sudo tcpdump -nn -r /tmp/day2_secure_n2.pcap -c 20
```

Expected:

- baseline pcap is non-zero and prints `internet`
- secure pcap is non-zero and prints no `internet`
- `tcpdump -nn -r /tmp/day2_secure_n2.pcap -c 20` shows SCTP packets between `10.100.200.12` and `10.100.200.16`

## 12. What students should conclude

If all checks above pass, students have proved both sides of the comparison:

- baseline: NAS messages were only integrity protected and the requested DNN name stayed visible on the N2 capture
- secure: NAS messages were encrypted with `NEA2` and the requested DNN name was no longer visible on the N2 capture

Students have also proved:

1. the VDI is on the `bootcamp` branch
2. the free5GC stack is healthy
3. the UE completed authentication successfully in both runs
4. the AMF saw scheme `0` in the baseline run and scheme `1` in the secure run
5. the Security Mode procedure completed in both runs
6. the secure run negotiated `NIA2` plus `NEA2`

## 13. One-command proof checklist

If you only want the shortest command set, run these in order:

```bash
cd /opt/free5gc-compose
echo free5gc | sudo -S bash /opt/free5gc-compose/ovf/scripts/branch-switch.sh bootcamp
self-test.sh
cp config/amfcfg.yaml /tmp/amfcfg.day2.bak
cp config/uecfg.yaml /tmp/uecfg.day2.bak
python3 - <<'PY'
from pathlib import Path
p = Path('config/amfcfg.yaml')
s = p.read_text().replace(
    "    cipheringOrder: # the priority of ciphering algorithms\n      - NEA2\n      - NEA0",
    "    cipheringOrder: # the priority of ciphering algorithms\n      - NEA0\n      - NEA2",
)
p.write_text(s)
PY
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
docker restart amf ueransim
sleep 8
echo free5gc | sudo -S bash -lc 'rm -f /tmp/day2_baseline_n2.pcap /tmp/day2_baseline_n2.pid; nohup tcpdump -i br-free5gc -w /tmp/day2_baseline_n2.pcap host 10.100.200.12 and host 10.100.200.16 >/tmp/day2_baseline_n2.log 2>&1 & echo $! >/tmp/day2_baseline_n2.pid'
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue_baseline.log 2>&1 &'
sleep 20
echo free5gc | sudo -S bash -lc 'kill $(cat /tmp/day2_baseline_n2.pid)'
cp /tmp/amfcfg.day2.bak config/amfcfg.yaml
cp /tmp/uecfg.day2.bak config/uecfg.yaml
docker restart amf ueransim
sleep 8
echo free5gc | sudo -S bash -lc 'rm -f /tmp/day2_secure_n2.pcap /tmp/day2_secure_n2.pid; nohup tcpdump -i br-free5gc -w /tmp/day2_secure_n2.pcap host 10.100.200.12 and host 10.100.200.16 >/tmp/day2_secure_n2.log 2>&1 & echo $! >/tmp/day2_secure_n2.pid'
docker exec -d ueransim bash -lc 'cd /ueransim && nohup ./nr-ue -c ./config/uecfg.yaml >/tmp/ue_secure.log 2>&1 &'
sleep 20
echo free5gc | sudo -S bash -lc 'kill $(cat /tmp/day2_secure_n2.pid)'
docker exec ueransim grep -E 'Selected integrity|Initial Registration is successful|PDU Session establishment is successful' /tmp/ue_baseline.log /tmp/ue_secure.log
docker compose logs --since 5m free5gc-amf | grep -E 'MobileIdentity5GS|Authentication|Security Mode|Registration'
strings /tmp/day2_baseline_n2.pcap | grep internet
strings /tmp/day2_secure_n2.pcap | grep internet
```
