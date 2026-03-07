# Packer template: Ubuntu 22.04 ARM64 cloud image + free5gc-compose (QEMU/HVF)
# Uses SMBIOS injection to pass NoCloud datasource URL to cloud-init.
# No ISO installer, no keyboard input, no CIDATA ISO mount issues.
# Build: packer init . && packer build ubuntu-22.04.5-free5gc-qemu.pkr.hcl

packer {
  required_plugins {
    qemu = {
      version = ">= 1.1.0"
      source  = "github.com/hashicorp/qemu"
    }
  }
}

variable "vm_name" {
  type    = string
  default = "ubuntu-22.04.5-free5gc"
}

variable "memory" {
  type    = number
  default = 4096
}

variable "cpus" {
  type    = number
  default = 4
}

variable "disk_size" {
  type    = string
  default = "40G"
}

variable "repo_url" {
  type    = string
  default = "https://github.com/Arjitg450/free5gc-compose.git"
}

variable "branch" {
  type    = string
  default = "bootcamp"
}

source "qemu" "ubuntu" {
  # Ubuntu 22.04 ARM64 cloud image (pre-installed, no ISO installer)
  iso_url      = "https://cloud-images.ubuntu.com/releases/jammy/release/ubuntu-22.04-server-cloudimg-arm64.img"
  iso_checksum = "sha256:0bdc35735c490ed1cf04f93b104fdf19eff7e5f4777d4dfdf777bc374ac32db8"
  disk_image   = true

  # Apple Silicon: HVF acceleration, native ARM64
  qemu_binary  = "qemu-system-aarch64"
  accelerator  = "hvf"
  machine_type = "virt"
  cpu_model    = "host"

  # ARM64 EFI firmware
  efi_boot          = true
  efi_firmware_code = "/opt/homebrew/share/qemu/edk2-aarch64-code.fd"
  efi_firmware_vars = "/opt/homebrew/share/qemu/edk2-arm-vars.fd"

  memory    = var.memory
  cpus      = var.cpus
  disk_size = var.disk_size
  format    = "qcow2"

  output_directory = "output-qemu"
  vm_name          = "${var.vm_name}.qcow2"

  # Serve cloud-init user-data/meta-data via Packer's HTTP server
  http_directory = "cloudinit"

  # SMBIOS injection: tells cloud-init to use nocloud datasource from Packer's HTTP server.
  # This is the reliable way to seed cloud-init on QEMU - no CIDATA ISO needed.
  qemuargs = [
    ["-smbios", "type=1,serial=ds=nocloud-net;s=http://{{ .HTTPIP }}:{{ .HTTPPort }}/"]
  ]

  boot_wait    = "5s"
  boot_command = ["<wait>"]

  net_device = "virtio-net"
  headless   = true

  ssh_username           = "ubuntu"
  ssh_password           = "free5gc"
  ssh_timeout            = "10m"
  ssh_handshake_attempts = 100

  shutdown_command = "echo 'free5gc' | sudo -S shutdown -P now"
}

build {
  name    = "free5gc-qemu"
  sources = ["source.qemu.ubuntu"]

  provisioner "file" {
    source      = "../scripts"
    destination = "/tmp/free5gc-ovf-scripts"
  }

  provisioner "file" {
    source      = "../../"
    destination = "/tmp"
  }

  provisioner "shell" {
    execute_command  = "echo 'free5gc' | {{ .Vars }} sudo -S -E bash '{{ .Path }}'"
    environment_vars = [
      "REPO_URL=${var.repo_url}",
      "BRANCH=${var.branch}"
    ]
    script = "../scripts/provision.sh"
  }
}
