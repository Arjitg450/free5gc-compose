# Troubleshooting

## Docker network overlap on `10.100.200.0/24`

The stock stack and the attack PoC both use the same lab subnet, `10.100.200.0/24`, on the bridge `br-free5gc`. Use the repo wrappers instead of raw `docker compose up` when switching modes:

```bash
./script/normal-up.sh
./script/attack-up.sh
./script/rollback-to-normal.sh
```

Those wrappers will:

- inspect Docker networks already using `10.100.200.0/24`
- stop only this repo's known conflicting projects
- remove only this repo's orphaned networks
- refuse to delete unrelated Docker networks on the host

### Inspect conflicting networks manually

```bash
docker network ls
docker network inspect free5gc-lab-net
docker network inspect free5gc-compose_privnet
docker network inspect attack_poc_privnet
docker ps -a --filter network=free5gc-lab-net
docker ps -a --filter network=free5gc-compose_privnet
docker ps -a --filter network=attack_poc_privnet
```

If the overlap belongs to an unrelated network, remove it manually only after confirming it is safe.

## Safe mode switching

### Start normal mode

```bash
./script/normal-up.sh
```

### Stop normal mode

```bash
./script/normal-down.sh
```

### Start attack mode

```bash
./attack_poc/build_compromised_smf.sh
./script/attack-up.sh
```

### Stop attack mode

```bash
./script/attack-down.sh
```

### Roll back from attack mode to normal mode

```bash
./script/rollback-to-normal.sh
```

## Fix `enp0s3` when the VM loses networking

If the VM NIC is down or has no IPv4 address, use:

```bash
sudo ./script/fix-enp0s3.sh
```

If the VDI also fails with `Could not resolve host` while running `branch-switch.sh`, use:

```bash
sudo ./script/fix-vdi-network.sh
```

`fix-vdi-network.sh` restores the NIC, refreshes DHCP, checks the default route, repairs DNS, and verifies name resolution before you retry the branch switch.

If your NIC uses another name, pass it explicitly:

```bash
sudo ./script/fix-vdi-network.sh eth0
```

## Verify stack health

### Normal mode

```bash
docker compose --project-name free5gc-normal --project-directory . -f docker-compose.yaml ps
docker logs amf --tail 20
docker logs smf --tail 20
docker network inspect free5gc-lab-net
```

### Attack mode

```bash
docker compose --project-name free5gc-attack --project-directory . -f attack_poc/docker-compose-attack.yaml ps
docker logs smf --tail 40 | grep -i ATTACK
docker logs ueransim-gnb --tail 20
docker logs ueransim-ue1 --tail 20
docker logs ueransim-ue2 --tail 20
```

## Drop data from MongoDB

Sometimes you need to drop the database:

```bash
docker exec -it mongodb mongosh
use free5gc
db.dropDatabase()
exit
```

## Inspect service logs

Use `docker logs` for individual services. Example:

```bash
docker logs smf
```

## MongoDB WiredTiger recovery

If MongoDB fails with WiredTiger corruption errors, recreate the volume for the affected mode.

### Root stack volume

```bash
./script/normal-down.sh
docker volume rm free5gc-compose_dbdata
./script/normal-up.sh
```

### Attack stack volume

```bash
./script/attack-down.sh
docker volume rm attack_poc_dbdata
./script/attack-up.sh
```