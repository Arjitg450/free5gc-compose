# Single-Command Attack Tutorial

This tutorial is for the existing one-command attack entrypoint already present in the repo:

```bash
./attack_poc/run_attack.sh
```

Use this when you want the attack lab to build the compromised SMF, switch from normal mode to attack mode safely, provision the two UEs, wait for registration, and run the attack verification in one go.

## What this command does

`./attack_poc/run_attack.sh` performs these steps automatically:

1. Builds `free5gc/smf:compromised` if needed.
2. Safely switches the lab into attack mode by calling `./script/attack-up.sh`.
3. Verifies that the attack topology is running.
4. Waits for MongoDB and provisions the UE subscribers.
5. Waits for UE registration and PDU sessions.
6. Runs `./attack_poc/verify_attack.sh`.

## Before you run it

Make sure the following are already available inside the current VM or VDI:

- Docker daemon is running.
- `docker compose` works.
- The `gtp5g` kernel module is loaded.
- Your VM still has network connectivity.

If the VM lost management networking because `enp0s3` is down, fix it first:

```bash
sudo ./script/fix-enp0s3.sh
```

## Single-command run

From the repo root:

```bash
cd free5gc-compose
./attack_poc/run_attack.sh
```

## Expected result

If the run is successful, you should see:

- the compromised SMF image build complete
- the attack stack come up under project `free5gc-attack`
- UE1 and UE2 provisioning succeed
- SMF logs include `ATTACK` lines
- `./attack_poc/verify_attack.sh` complete without manual Docker cleanup

Useful checks after the script finishes:

```bash
docker compose --project-name free5gc-attack --project-directory . -f attack_poc/docker-compose-attack.yaml ps
docker logs smf --tail 50 | grep -i ATTACK
docker logs ueransim-gnb --tail 20
docker logs ueransim-ue1 --tail 20
docker logs ueransim-ue2 --tail 20
```

## Roll back to normal mode

When you are done, return to the stock deployment with:

```bash
./script/rollback-to-normal.sh
```

## If you want packet-capture proof

The single-command tutorial above is for the normal attack demo entrypoint. If you specifically want a pcap-producing proof run, use the existing capture wrapper instead:

```bash
./attack_poc/run_attack_with_pcap.sh
```

That wrapper executes the capture workflow with `sudo` and writes proof artifacts into `attack_poc/captures/`.

## Troubleshooting

If the command stops before startup, it is usually one of these:

- Docker is not running.
- Another Docker network outside this repo is already using `10.100.200.0/24`.
- `enp0s3` is down or missing an IPv4 address.
- The VM does not currently have enough resources for the full topology.

Useful inspection commands:

```bash
docker network ls
docker network inspect free5gc-lab-net
docker ps -a --filter network=free5gc-lab-net
./script/attack-down.sh
./script/attack-up.sh
```