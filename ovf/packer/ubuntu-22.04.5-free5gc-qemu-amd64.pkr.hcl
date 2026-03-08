# Packer template: Ubuntu 22.04 AMD64 cloud image + free5gc-compose (QEMU/KVM)
# Uses SMBIOS injection to pass NoCloud datasource URL to cloud-init.
# Build: packer init . && packer build ubuntu-22.04.5-free5gc-qemu-amd64.pkr.hcl

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
  default = "ubuntu-22.04.5-free5gc-amd64"
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

variable "release_version" {
  type    = string
  default = "dev"
}

variable "accelerator" {
  type    = string
  default = "tcg"
}

variable "cpu_model" {
  type    = string
  default = "max"
}

variable "efi_firmware_code" {
  type    = string
  default = "/opt/homebrew/Cellar/qemu/10.2.1/share/qemu/edk2-x86_64-code.fd"
}

variable "efi_firmware_vars" {
  type    = string
  default = "/opt/homebrew/Cellar/qemu/10.2.1/share/qemu/edk2-i386-vars.fd"
}

source "qemu" "ubuntu" {
  iso_url      = "https://cloud-images.ubuntu.com/releases/server/jammy/release/ubuntu-22.04-server-cloudimg-amd64.img"
  iso_checksum = "sha256:e66ef756881b5e682c496112201382abd76291797a7395bf81fd1bd0888f5b6f"
  disk_image   = true

  qemu_binary  = "qemu-system-x86_64"
  accelerator  = var.accelerator
  machine_type = "q35"
  cpu_model    = var.cpu_model

  efi_boot          = true
  efi_firmware_code = var.efi_firmware_code
  efi_firmware_vars = var.efi_firmware_vars

  memory    = var.memory
  cpus      = var.cpus
  disk_size = var.disk_size
  format    = "qcow2"

  output_directory = "output-qemu-amd64"
  vm_name          = "${var.vm_name}.qcow2"

  http_directory = "cloudinit"

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
  name    = "free5gc-qemu-amd64"
  sources = ["source.qemu.ubuntu"]

  provisioner "file" {
    source      = "../scripts"
    destination = "/tmp/free5gc-ovf-scripts"
  }

  provisioner "file" {
    source      = "free5gc-compose-repo.tar"
    destination = "/tmp/free5gc-compose-repo.tar"
  }

  provisioner "file" {
    source      = "free5gc-images-amd64.tar"
    destination = "/tmp/free5gc-images.tar"
  }

  provisioner "shell" {
    execute_command = "echo 'free5gc' | {{ .Vars }} sudo -S -E bash '{{ .Path }}'"
    environment_vars = [
      "REPO_URL=${var.repo_url}",
      "BRANCH=${var.branch}",
      "TARGET_ARCH=amd64",
      "RELEASE_VERSION=${var.release_version}",
      "SUPPORTED_HYPERVISORS=qemu,virtualbox,vmware"
    ]
    script = "../scripts/provision.sh"
  }
}
