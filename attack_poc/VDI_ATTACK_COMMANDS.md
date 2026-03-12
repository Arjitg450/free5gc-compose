# Student VDI Attack Tutorial

This is the single tutorial to use on the VDI. Follow it in order.

## 1. Fix the VDI network first

Run these commands exactly on the VDI:

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

Run these commands exactly:

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

That command builds the compromised SMF if needed, switches the lab into attack mode, provisions the UEs, waits for registration, and runs the built-in verification.

## 6. Verify that the attack ran

Run these commands:

```bash
docker compose --project-name free5gc-attack --project-directory . -f attack_poc/docker-compose-attack.yaml ps
docker logs smf --tail 50 | grep -i ATTACK
docker logs ueransim-gnb --tail 20
docker logs ueransim-ue1 --tail 20
docker logs ueransim-ue2 --tail 20
```

If the attack worked, you should see `ATTACK` lines in the SMF logs.

## 7. Optional: capture proof packets

If you also want a pcap proof run, use:

```bash
./attack_poc/run_attack_with_pcap.sh
```

## 8. Return to the normal stack

When you are done, run:

```bash
./script/rollback-to-normal.sh
```

## 9. Copy-paste block

If you want one block to paste line by line on an older VDI:

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
```