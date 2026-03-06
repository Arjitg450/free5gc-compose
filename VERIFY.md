# Verifying the free5gc OVF/OVA Appliance

This document describes how to **import** the built appliance and **validate** that the free5gc-compose stack runs correctly with zero manual steps after first boot.

## Credentials (documented)

| Item      | Value                          |
|-----------|--------------------------------|
| Username  | `ubuntu`                       |
| Password  | `free5gc`                      |
| Auto-login| Not enabled by default; log in with the above. |

## VM resource requirements

|          | Minimum       | Recommended   |
|----------|---------------|---------------|
| RAM      | 4 GB          | 8 GB         |
| vCPUs    | 2             | 4            |
| Disk     | 25 GB         | 40 GB        |

Below minimum, containers may fail to start or the system may be unstable.

## Import steps

### VirtualBox

1. **File → Import Appliance…**
2. Choose `ubuntu-22.04.5-free5gc.ova` (or the `.ovf` file if you exported OVF only).
3. Adjust VM settings if desired (e.g. RAM to 8 GB); leave network as NAT or Bridged.
4. Click **Import**.
5. Start the VM.

### VMware

1. Use **File → Open** (or **Import**) and select the `.ovf` or `.ova` file.
2. Follow the import wizard; adjust resources as above.
3. Power on the VM.

## First boot and stack startup

1. Boot the VM and wait for the login prompt (or console).
2. Log in as `ubuntu` / `free5gc`.
3. The **free5gc-compose** stack is started by systemd service `free5gc-compose.service` after `network-online` and `docker.service`. Allow **2–5 minutes** after boot for all containers to come up.
4. Check status:

   ```bash
   free5gc-status
   ```

   You should see `docker compose ps` with containers in **Up** or **Up (healthy)** state.

5. Run the self-test:

   ```bash
   self-test.sh
   ```

   Expected output: **PASS** (exit code 0).

## Exact verification commands

Run these on the imported VM after first boot (allow a few minutes for the stack to start):

```bash
# 1. Service is enabled and has run
systemctl status free5gc-compose

# 2. Docker is running
docker info

# 3. Compose stack status and logs
free5gc-status

# 4. Self-test (must print PASS and exit 0)
self-test.sh
echo "Exit code: $?"
```

## Branch switch (bootcamp ↔ ieee-10175424)

Default branch at first boot is **bootcamp** (main `docker-compose.yaml`). To use the IEEE attack PoC stack:

```bash
cd /opt/free5gc-compose
sudo ./ovf/scripts/branch-switch.sh ieee-10175424
sudo systemctl restart free5gc-compose
```

Then run the attack stack (if not auto-started by the service):

```bash
cd /opt/free5gc-compose
docker compose -f attack_poc/docker-compose-attack.yaml --project-name attack_poc --project-directory . up -d
# Provision subscribers and run attack as per attack_poc/EDUCATIONAL_GUIDE.md
```

To switch back to bootcamp:

```bash
sudo ./ovf/scripts/branch-switch.sh bootcamp
sudo systemctl restart free5gc-compose
```

## Logs and troubleshooting

| What to check | Command |
|---------------|--------|
| systemd unit  | `journalctl -u free5gc-compose -n 100` |
| Docker        | `sudo systemctl status docker` |
| Compose stack | `free5gc-status` |
| Single NF     | `docker compose -f /opt/free5gc-compose/docker-compose.yaml --project-directory /opt/free5gc-compose logs --tail 50 <service>` |
| gtp5g module  | `lsmod \| grep gtp5g` |

If containers are **Exited** or **Restarting**:

1. Ensure **gtp5g** is loaded: `lsmod | grep gtp5g`; if missing, `sudo modprobe gtp5g`.
2. Check **free5gc-status** for NF logs (AMF, SMF, UPF, ueransim).
3. Restart the stack: `sudo systemctl restart free5gc-compose`, then wait 2–3 minutes and run **free5gc-status** again.

## Optional: UE ping test (bootcamp)

To validate data plane with a UE attach and ping:

1. Start the UE inside the ueransim container (see `5G_E2E_free5GC_UERANSIM_Report.md`):

   ```bash
   docker exec -it ueransim bash -lc "nohup ./nr-ue -c config/uecfg.yaml > /tmp/ue.log 2>&1 &"
   ```

2. Wait ~30 seconds, then:

   ```bash
   docker exec ueransim ping -I uesimtun0 -c 4 8.8.8.8
   ```

3. Or run self-test with UE ping enabled (after UE is up):

   ```bash
   RUN_UE_PING=1 self-test.sh
   ```

## Success criteria

- **Fresh VM import → first boot → within a few minutes the stack is running.**
- **free5gc-status** shows expected containers **Up** (or **Up (healthy)**).
- **self-test.sh** returns **PASS** and exit code 0.
- No missing dependency errors at runtime (Docker, gtp5g, images pre-pulled).
- A person with only the OVA and this VERIFY.md can reproduce the above steps and see success.
