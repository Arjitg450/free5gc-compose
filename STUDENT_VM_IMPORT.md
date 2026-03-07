# Student VM Import Guide

This guide is for students who were given prebuilt VM artifacts. It is not a build guide. You should **download the correct architecture** and import it into your hypervisor.

## 1. Choose the correct asset

| Your machine | Download this |
| --- | --- |
| Apple Silicon Mac | `arm64` artifact set |
| Intel/AMD laptop or desktop | `amd64` artifact set |

Do not mix them. A converted disk format does **not** change CPU architecture.

## 2. Hypervisor compatibility

| Asset | Best use | Notes |
| --- | --- | --- |
| `.qcow2` | QEMU | Canonical image format |
| `.vmdk` | VMware | Can also be attached to some VirtualBox VMs manually |
| `.ova` | VirtualBox or VMware import | Convenience package for students |

## 3. Minimum VM settings

- RAM: 4 GB minimum, 8 GB recommended
- vCPUs: 2 minimum, 4 recommended
- Disk: use the full imported appliance disk
- Network: NAT is sufficient for the lab unless your instructor asks otherwise

## 4. Import steps

### VirtualBox

1. Open **File -> Import Appliance**.
2. Select the architecture-matching `.ova`.
3. Keep EFI enabled if VirtualBox shows firmware settings.
4. Import and start the VM.

Manual VirtualBox path:

1. Create a new VM with the matching architecture and Ubuntu/Linux guest type.
2. Enable EFI.
3. Attach the matching `.vdi` as the primary disk.
4. Start the VM.

### VMware

1. Open the architecture-matching `.ova` directly, or create a VM and attach the matching `.vmdk`.
2. Keep UEFI firmware enabled.
3. Start the VM.

### QEMU

Boot the architecture-matching `.qcow2` with the correct QEMU binary for your host.

Examples:

```bash
# ARM64 host example
qemu-system-aarch64 \
  -machine virt \
  -cpu host \
  -smp 4 \
  -m 4096 \
  -drive if=virtio,file=free5gc-lab-vX.Y.Z-arm64.qcow2,format=qcow2
```

```bash
# AMD64 host example
qemu-system-x86_64 \
  -machine q35 \
  -cpu host \
  -smp 4 \
  -m 4096 \
  -drive if=virtio,file=free5gc-lab-vX.Y.Z-amd64.qcow2,format=qcow2
```

## 5. Login and first boot

- Username: `ubuntu`
- Password: `free5gc`

After first boot, wait **2-5 minutes** for Docker and the free5GC stack to settle.

Check health:

```bash
free5gc-status
self-test.sh
cat /etc/free5gc-release
```

Expected:
- `free5gc-status` shows the stack running
- `self-test.sh` prints `PASS`

## 6. Bootcamp workflow

Use the bootcamp branch by default. The VM should already start there.

Run the manual lab from:
[`5G_E2E_free5GC_UERANSIM_Report.md`](./5G_E2E_free5GC_UERANSIM_Report.md)

Important expected outcomes:
- UE registration succeeds
- PDU session succeeds
- `uesimtun0` appears
- `ping -I uesimtun0 8.8.8.8` works
- `curl --interface uesimtun0 -I http://example.com` works

## 7. IEEE attack workflow

Switch branches:

```bash
sudo /usr/local/bin/branch-switch.sh ieee-10175424
```

Then run the attack workflow from:
[`attack_poc/README.md`](./attack_poc/README.md)

Expected outcomes:
- attack stack starts
- both UEs receive slice IPs
- proof pcap/report are created under `attack_poc/captures/`

## 8. Switching back

Return to bootcamp:

```bash
sudo /usr/local/bin/branch-switch.sh bootcamp
```

Then re-check:

```bash
free5gc-status
docker exec ueransim bash -lc 'which curl'
```

The `ueransim` container should still contain `curl`, so the HTTP step in the bootcamp guide continues to work after branch switching.

## 9. Troubleshooting

Useful commands:

```bash
journalctl -u free5gc-compose -n 100
free5gc-status
lsmod | grep gtp5g
docker compose -f /opt/free5gc-compose/docker-compose.yaml --project-directory /opt/free5gc-compose ps
```

If the wrong branch is active, switch explicitly with `branch-switch.sh`.

If the stack needs a restart:

```bash
sudo systemctl restart free5gc-compose
```
