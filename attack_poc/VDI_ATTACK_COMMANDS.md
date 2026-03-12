# Student VDI Attack Tutorial

Run these commands in order on the VDI.

## 1. Fix the VDI network first

```bash
sudo ip link set enp0s3 up
sudo dhclient -v enp0s3
ip -4 -br a show enp0s3
```

If `enp0s3` does not get an IPv4 address, stop and fix the VM networking before continuing.

## 2. Go to the repo

```bash
cd /opt/free5gc-compose
```

## 3. Make the repo writable for the `ubuntu` user

```bash
sudo chown -R ubuntu:ubuntu /opt/free5gc-compose
```

## 4. Update to the correct branch

```bash
git fetch origin
git switch feat/ieee-10175424 || git switch -c feat/ieee-10175424 --track origin/feat/ieee-10175424
git reset --hard origin/feat/ieee-10175424
chmod +x script/*.sh attack_poc/*.sh
```

## 5. Run the attack

```bash
./attack_poc/run_attack.sh
```

Wait for the script to finish. It now prints a terminal proof summary at the end.

## 6. Print the proof again if needed

```bash
cat attack_poc/captures/latest_attack_proof_report.txt
```

This file is the easiest thing to trust on the VDI if `docker logs` does not show up cleanly in the terminal.

## 7. Optional: capture proof packets

```bash
./attack_poc/run_attack_with_pcap.sh
```

## 8. Return to the normal stack

```bash
./script/rollback-to-normal.sh
```

## 9. Copy-paste block

```bash
sudo ip link set enp0s3 up
sudo dhclient -v enp0s3
ip -4 -br a show enp0s3
cd /opt/free5gc-compose
sudo chown -R ubuntu:ubuntu /opt/free5gc-compose
git fetch origin
git switch feat/ieee-10175424 || git switch -c feat/ieee-10175424 --track origin/feat/ieee-10175424
git reset --hard origin/feat/ieee-10175424
chmod +x script/*.sh attack_poc/*.sh
./attack_poc/run_attack.sh
cat attack_poc/captures/latest_attack_proof_report.txt
```