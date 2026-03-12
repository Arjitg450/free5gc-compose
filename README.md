# free5GC compose

This repository is a Docker Compose deployment of [free5GC](https://github.com/free5gc/free5gc) for stage 3. It is inspired by [free5gc-docker-compose](https://github.com/calee0219/free5gc-docker-compose) and [docker-free5gc](https://github.com/abousselmi/docker-free5gc).

The repo now has two supported lab modes:

- Normal mode: the stock single-UPF stack from [docker-compose.yaml](./docker-compose.yaml)
- Attack PoC mode: the compromised-SMF topology from [attack_poc/docker-compose-attack.yaml](./attack_poc/docker-compose-attack.yaml)

Both modes intentionally use the same `10.100.200.0/24` lab subnet and bridge, so they are treated as mutually exclusive lab states. Use the wrapper scripts in `script/` or the matching `make` targets to switch modes safely.

## Prerequisites

- [GTP5G kernel module](https://github.com/free5gc/gtp5g): needed to run the UPF. UPF currently supports GTP5G `v0.9.5`.
- [Docker Engine](https://docs.docker.com/engine/install): needed to run the free5GC containers.
- [Docker Compose v2](https://docs.docker.com/compose/install): required because the repo uses `docker compose`.
- `bash`, `ip`, and `dhclient` inside the lab VM if you want to use the NIC recovery helper.

Note: some CPUs do not support MongoDB releases above `4.4` because of AVX requirements. Check with `grep avx /proc/cpuinfo`. A workaround is discussed [here](https://github.com/free5gc/free5gc-compose/issues/30#issuecomment-897627049).

## Lab Workflows

### Mode commands

Use either the scripts or the `make` targets:

```bash
./script/normal-up.sh
./script/normal-down.sh
./script/attack-up.sh
./script/attack-down.sh
./script/rollback-to-normal.sh
./script/fix-enp0s3.sh
./script/fix-vdi-network.sh
```

```bash
make normal-up
make normal-down
make attack-up
make attack-down
make rollback-normal
make fix-enp0s3
make fix-vdi-network
```

The wrappers do four things before startup:

1. Check that Docker and `docker compose` are available.
2. Warn if `enp0s3` is missing, down, or lacks IPv4.
3. Inspect Docker networks that already claim `10.100.200.0/24`.
4. Automatically bring down only this repo's known conflicting projects (`free5gc-normal`, `free5gc-attack`, `free5gc-compose`, `attack_poc`) and remove only this repo's orphaned networks.

If the overlap belongs to an unrelated Docker network on the host, the scripts stop and print the exact inspection commands instead of deleting anything.

### Normal mode

```bash
./script/normal-up.sh
```

This starts the stock root compose stack with deterministic project/network naming:

- Compose project: `free5gc-normal`
- Shared lab network: `free5gc-lab-net`
- Root MongoDB volume: `free5gc-compose_dbdata`

Useful verification commands:

```bash
docker compose --project-name free5gc-normal --project-directory . -f docker-compose.yaml ps
docker network inspect free5gc-lab-net
docker logs amf --tail 20
docker logs smf --tail 20
```

To stop normal mode:

```bash
./script/normal-down.sh
```

### Attack PoC mode

Build the compromised SMF image once if it is not already present:

```bash
./attack_poc/build_compromised_smf.sh
```

Then switch into attack mode:

```bash
./script/attack-up.sh
```

This wrapper safely brings down normal mode first if it owns the conflicting subnet, then starts the attack topology with:

- Compose project: `free5gc-attack`
- Shared lab network: `free5gc-lab-net`
- Attack MongoDB volume: `attack_poc_dbdata`

Useful verification commands:

```bash
docker compose --project-name free5gc-attack --project-directory . -f attack_poc/docker-compose-attack.yaml ps
docker logs smf --tail 40 | grep -i ATTACK
docker logs ueransim-gnb --tail 20
docker logs ueransim-ue1 --tail 20
docker logs ueransim-ue2 --tail 20
```

To stop attack mode:

```bash
./script/attack-down.sh
```

### Switching Between Modes Safely

Do not run the root stack and the attack PoC stack side by side. They reuse container names, the same lab bridge, and the same lab subnet.

Use these transitions instead:

```bash
# normal -> attack
./script/attack-up.sh

# attack -> normal
./script/rollback-to-normal.sh
```

You no longer need to remember whether the old conflicting project was `free5gc-compose` or `attack_poc`; the wrappers check and clean both of those legacy project names automatically when they belong to this repo.

### Single-command attack tutorial

If you want the attack lab walkthrough as a separate markdown file for the current VM or VDI workspace, use [attack_poc/SINGLE_COMMAND_ATTACK_TUTORIAL.md](./attack_poc/SINGLE_COMMAND_ATTACK_TUTORIAL.md). It documents the existing one-command attack entrypoint:

```bash
./attack_poc/run_attack.sh
```

### VDI command-only tutorial

If you only want the exact command list to run in the VDI, use [attack_poc/VDI_ATTACK_COMMANDS.md](./attack_poc/VDI_ATTACK_COMMANDS.md).

### How To Inspect Conflicting Docker Networks

Use these commands before manual cleanup or when a wrapper reports an unrelated overlap:

```bash
docker network ls
docker network inspect free5gc-lab-net
docker network inspect free5gc-compose_privnet
docker network inspect attack_poc_privnet
docker ps -a --filter network=free5gc-lab-net
docker ps -a --filter network=free5gc-compose_privnet
docker ps -a --filter network=attack_poc_privnet
```

If the overlap belongs to something outside this repo, inspect that network first and remove it yourself only if you know it is safe.

### Fix `enp0s3` If VM Networking Is Down

If the VM loses its management IP or SSH access because `enp0s3` is down, run:

```bash
sudo ./script/fix-enp0s3.sh
```

The helper will:

1. Check that `enp0s3` exists.
2. Bring it up if it is down.
3. Run `dhclient -v enp0s3` if no IPv4 address is present.
4. Print the final state with `ip -4 -br a show enp0s3`.

If your VM uses another NIC name, pass it explicitly:

```bash
sudo ./script/fix-vdi-network.sh eth0
```

## Pull Or Build Images

### Pull images from Docker Hub

```bash
docker compose pull
```

### Optional: build images from local sources

```bash
git clone https://github.com/free5gc/free5gc-compose.git
cd free5gc-compose

cd base
git clone --recursive -j "$(nproc)" https://github.com/free5gc/free5gc.git
cd ..

make all
docker compose -f docker-compose-build.yaml build

# Example: build a single NF image
docker compose -f docker-compose-build.yaml build free5gc-amf
```

Dangling images may be created during local builds. Remove them periodically if needed:

```bash
docker rmi $(docker images -f "dangling=true" -q)
```

## Manual Compose Usage

The wrapper scripts are the recommended entrypoint for the lab because they handle mode switching and subnet preflight. If you need direct Compose commands, use the deterministic project names shown below:

```bash
# stock stack
docker compose --project-name free5gc-normal --project-directory . -f docker-compose.yaml up -d

# attack stack
docker compose --project-name free5gc-attack --project-directory . -f attack_poc/docker-compose-attack.yaml up -d
```

## Troubleshooting

See [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for the Docker network overlap workflow, `enp0s3` recovery, MongoDB recovery, and log inspection commands.

## Integration with External gNB or UE

### UERANSIM Notes

The integration with [UERANSIM](https://github.com/aligungr/UERANSIM) is documented [here](https://free5gc.org/guide/5-install-ueransim/). This [issue](https://github.com/free5gc/free5gc-compose/issues/28) also has useful notes.

#### Option 1: Run UE inside the gNB container

```bash
docker exec -it ueransim bash
./nr-ue -c config/uecfg.yaml
```

#### Option 2: Run UE in a separate container

By default, the `ueransim` service in [docker-compose.yaml](./docker-compose.yaml) acts only as a gNB. To add a UE service:

1. Create a subscriber through the WebUI.
2. Copy the `UE ID` field.
3. Set `supi` in [config/uecfg.yaml](./config/uecfg.yaml) to that UE ID.
4. Set `linkIp` in [config/gnbcfg.yaml](./config/gnbcfg.yaml) to `gnb.free5gc.org`.
5. Add a UE service to [docker-compose.yaml](./docker-compose.yaml) using `privnet`.
6. Start normal mode with `./script/normal-up.sh`.

## Integration of WebUI with Nginx Reverse Proxy

Guidance for putting Nginx in front of the WebUI is available [here](https://github.com/free5gc/free5gc-compose/issues/55#issuecomment-1146648600).

## ULCL Configuration

To start the core with an I-UPF and PSA-UPF ULCL configuration:

```bash
docker compose -f docker-compose-ulcl.yaml up
```

This configuration was tested with [free5gc-compose v4.0.0](https://github.com/free5gc/free5gc-compose/tree/v4.0.0). See [config/ULCL](./config/ULCL).

## Prometheus and Grafana

To start the core with Prometheus and Grafana:

```bash
docker compose -f docker-compose.yaml -f docker-compose-prometheus.yaml up
```

Make sure metrics are enabled in the NF configuration first.

## Reference

- https://github.com/open5gs/nextepc/tree/master/docker
- https://github.com/abousselmi/docker-free5gc