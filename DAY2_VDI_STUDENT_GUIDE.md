# Day 2 VDI Student Guide

This guide is only for Day 2 on the VDI appliance. It covers:

- switching the repo to `bootcamp`
- verifying the core is running
- showing a before/after comparison between baseline and secure behavior
- running the UE attach for Day 2
- proving that authentication and NAS security are working

Run these commands from inside the VDI terminal after logging in as `ubuntu`.

## 1. Recover the VDI network and sync the repo

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

## 2. Switch to the bootcamp branch

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

## 3. Verify the stack is running

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

## 4. Confirm the secure Day 2 default config

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

## 5. What you will see in the comparison

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

## 6. Run the full before/after script

Use the script instead of copy-pasting the long baseline block.

```bash
cd /opt/free5gc-compose
bash script/day2-before-after.sh
```

What the script does:

1. backs up the secure config
2. runs the baseline pass with `NEA0` and SUCI disabled
3. captures `/tmp/day2_baseline_n2.pcap`
4. restores the secure config
5. runs the secure pass with `NEA2` and SUCI enabled
6. captures `/tmp/day2_secure_n2.pcap`
7. leaves the VDI back in the secure state

Expected output from the script:

- baseline UE log shows `Selected integrity[2] ciphering[0]`
- secure UE log shows `Selected integrity[2] ciphering[2]`
- baseline strings check prints `internet`
- secure strings check prints no output

## 7. Inspect the proof files and logs

After the script finishes, inspect the results directly:

```bash
docker exec ueransim grep -E 'Selected integrity|Initial Registration is successful|PDU Session establishment is successful' /tmp/ue_baseline.log /tmp/ue_secure.log
strings /tmp/day2_baseline_n2.pcap | grep internet
strings /tmp/day2_secure_n2.pcap | grep internet
ls -lh /tmp/day2_baseline_n2.pcap /tmp/day2_secure_n2.pcap
```

You should see:

- baseline UE log with `ciphering[0]`
- secure UE log with `ciphering[2]`
- baseline pcap prints `internet`
- secure pcap prints no `internet`

## 8. Run the secure Day 2 attach only

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

## 9. Check the AMF proof

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

## 10. Capture clean proof on the VDI host

Important:

- do not capture the full bridge and then grep for `internet`
- the full bridge also carries internal HTTP/SBI traffic, which includes the word `internet`
- for Day 2 proof, capture only the N2 path between gNB and AMF

Use the files produced by the script:

- `/tmp/day2_baseline_n2.pcap`
- `/tmp/day2_secure_n2.pcap`

Check the proof:

```bash
sudo tcpdump -nn -r /tmp/day2_secure_n2.pcap -c 20
```

Expected:

- the secure pcap shows SCTP packets between `10.100.200.12` and `10.100.200.16`
- the secure pcap does not expose `internet` via `strings`

## 11. What students should conclude

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
