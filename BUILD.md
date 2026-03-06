# Building the free5gc OVF/OVA Appliance

This document gives **exact commands** to build the Ubuntu 22.04.5 free5gc-compose OVF/OVA on a clean machine. The result is a VM that boots with the free5gc stack already running.

## Build host requirements

- **OS:** Linux (Ubuntu 20.04/22.04 recommended) or macOS with VirtualBox.
- **RAM:** 8 GB minimum (Packer runs a VM that needs 4 GB).
- **Disk:** 20 GB free for build artifacts and the output VM.
- **Software:** Packer (1.8+), VirtualBox (6.1+), Git.

## Install build dependencies

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install -y virtualbox packer git
```

If Packer is not in your distro repos, install from HashiCorp:

```bash
# Example: install Packer 1.9
wget -q https://releases.hashicorp.com/packer/1.9.4/packer_1.9.4_linux_amd64.zip
unzip packer_1.9.4_linux_amd64.zip
sudo mv packer /usr/local/bin/
```

### macOS

```bash
brew install packer
brew install --cask virtualbox
```

## Clone the repository

```bash
git clone https://github.com/Arjitg450/free5gc-compose.git
cd free5gc-compose
git checkout bootcamp
```

Ensure the `ovf/` directory is present (it is part of this repo). The provision script will clone the same repo into the VM at `/opt/free5gc-compose`; if you build from a fork or branch, push your changes first so the VM clone gets the correct `ovf/` and configs.

## Build the VM with Packer

From the **repository root**:

```bash
cd ovf/packer
```

**If you have Packer 1.7 or newer** (run `packer version` to check; 1.7+ includes the `init` command):

```bash
packer init .
packer build ubuntu-22.04.5-free5gc.pkr.hcl
```

**If you have Packer 1.6.x** (no `init` command — use build only):

```bash
packer build ubuntu-22.04.5-free5gc.pkr.hcl
```

This will:

1. Download the **Ubuntu 22.04.5 live-server** ISO (if not cached).
2. Create a VirtualBox VM, install Ubuntu using autoinstall (user `ubuntu`, password `free5gc`).
3. Run the provision script: Docker, gtp5g, clone of this repo into `/opt/free5gc-compose`, `docker compose pull`, systemd unit, `free5gc-status` and `self-test.sh`.

Build time is typically 20–40 minutes depending on network and host speed.

### Live progress + stuck watchdog (recommended)

Use the watcher script to avoid waiting blindly for `ssh_timeout`:

```bash
cd ovf/packer
./packer-watch.sh --stall-timeout 900
```

This prints continuous progress timestamps and an `idle=<seconds>` watchdog counter.
If you want auto-stop on stalls:

```bash
./packer-watch.sh --stall-timeout 900 --kill-on-stall
```

## Export to OVF/OVA

After the build, the VM is registered in VirtualBox. Export it to OVF or OVA.

### Export to OVA (single file, preferred)

```bash
VBoxManage export ubuntu-22.04.5-free5gc -o ubuntu-22.04.5-free5gc.ova
```

The file `ubuntu-22.04.5-free5gc.ova` is the appliance.

### Export to OVF + VMDK (separate files)

```bash
VBoxManage export ubuntu-22.04.5-free5gc -o ubuntu-22.04.5-free5gc.ovf --ovf20
```

This creates `ubuntu-22.04.5-free5gc.ovf` and one or more `.vmdk` disk images.

## Pinned versions (reproducibility)

| Component        | Version / source |
|-----------------|------------------|
| Ubuntu          | 22.04.5 LTS (live-server amd64)      |
| Docker          | 24.0 (from get.docker.com) |
| Docker Compose  | v2 (plugin, from distro) |
| gtp5g           | Built from https://github.com/free5gc/gtp5g (main) |
| free5gc-compose | https://github.com/Arjitg450/free5gc-compose.git, branch `bootcamp` |

Unattended upgrades are disabled during provisioning so the image does not change over time. See VERIFY.md for recommended VM resources when **running** the imported appliance.

## Optional variables

Variables (with defaults) are in `ubuntu-22.04.5-free5gc.pkr.hcl`. Override at build time with `-var`:

```bash
packer build \
  -var "memory=8192" \
  -var "cpus=4" \
  -var "disk_size=51200" \
  ubuntu-22.04.5-free5gc.pkr.hcl
```

## Troubleshooting

- **Packer fails at SSH:** Ensure the autoinstall `late-commands` set the password correctly; increase `ssh_timeout` in the template if the install is slow.
- **Docker or compose not found in VM:** Re-run the provision step or check `/var/log/syslog` in the build VM.
- **gtp5g build fails:** The VM must have `linux-headers-$(uname -r)`; the provision script installs it. If the kernel was updated after install, rebuild the image.
- **Export fails:** Unregister other VMs with the same name: `VBoxManage unregistervm ubuntu-22.04.5-free5gc --delete` then re-run the build.

- **GRUB edit timing issues:** If boot key injection misses the GRUB editor, increase boot delay: `packer build -var "boot_wait=15s" ubuntu-22.04.5-free5gc.pkr.hcl` or run once with `headless=false` to observe the sequence.
