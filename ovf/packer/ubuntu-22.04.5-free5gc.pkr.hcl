# Packer template: Ubuntu 22.04.5 LTS + free5gc-compose OVF appliance
# Build (Packer 1.7+): packer init . && packer build ubuntu-22.04.5-free5gc.pkr.hcl
# Build (Packer 1.6.x): packer build ubuntu-22.04.5-free5gc.pkr.hcl

variable "iso_url" {
  type    = string
  default = "https://releases.ubuntu.com/22.04/ubuntu-22.04.5-live-server-amd64.iso"
}

variable "iso_checksum" {
  type    = string
  default = "sha256:9bc6028870aef3f74f4e16b900008179e78b130e6b0b9a140635434a46aa98b0"
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
  default = 2
}

variable "disk_size" {
  type    = number
  default = 40960
}

variable "headless" {
  type    = bool
  default = true
}

variable "boot_wait" {
  type    = string
  default = "30s"
}

# Give autoinstall time to run late-commands (chpasswd, sshd_config) before Packer
# gives up on SSH auth. Default 10 attempts is too low for Ubuntu autoinstall.
variable "ssh_handshake_attempts" {
  type    = number
  default = 600
}

# Explicit Guest Additions URL avoids "Default Guest Additions ISO" error when
# VirtualBox is from distro repos (no bundled ISO). Packer will download this.
variable "guest_additions_url" {
  type    = string
  default = "https://download.virtualbox.org/virtualbox/6.1.50/VBoxGuestAdditions_6.1.50.iso"
}

variable "guest_additions_sha256" {
  type    = string
  default = "af53e34c5a5ec143f3418ac01d00ed5f33f6b31bfdc92eb4714c99d9bccb6602"
}

source "virtualbox-iso" "ubuntu" {
  iso_url      = var.iso_url
  iso_checksum = var.iso_checksum

  guest_additions_url    = var.guest_additions_url
  guest_additions_sha256 = var.guest_additions_sha256

  guest_os_type = "Ubuntu_64"
  vm_name       = var.vm_name

  cpus   = var.cpus
  memory = var.memory

  disk_size            = var.disk_size
  hard_drive_interface = "sata"

  http_directory = "http"
  boot_wait      = var.boot_wait

  # Ubuntu 22.04 live-server autoinstall (NoCloud over Packer HTTP server)
  boot_command = [
    "<esc><wait>",
    "e<wait>",
    "<down><down><down><end>",
    " autoinstall ds=nocloud-net\\;s=http://{{ .HTTPIP }}:{{ .HTTPPort }}/<enter><wait>",
    "<f10>"
  ]

  shutdown_command = "echo 'free5gc' | sudo -S shutdown -P now"
  headless         = var.headless

  ssh_username            = "ubuntu"
  ssh_password            = "free5gc"
  ssh_timeout             = "45m"
  ssh_handshake_attempts  = var.ssh_handshake_attempts

  vboxmanage = [
    ["modifyvm", "{{ .Name }}", "--natdnshostresolver1", "on"],
    ["modifyvm", "{{ .Name }}", "--nictype1", "virtio"],
    ["modifyvm", "{{ .Name }}", "--audio", "none"]
  ]
}

build {
  name = "free5gc-ovf"

  sources = ["source.virtualbox-iso.ubuntu"]

  provisioner "file" {
    source      = "../scripts"
    destination = "/tmp/free5gc-ovf-scripts"
  }

  provisioner "shell" {
    execute_command = "echo 'free5gc' | {{ .Vars }} sudo -S -E bash '{{ .Path }}'"
    script          = "../scripts/provision.sh"
  }

  # OVF/OVA export: run manually after build (see BUILD.md)
  # VBoxManage export ubuntu-22.04.5-free5gc -o ubuntu-22.04.5-free5gc.ova
}
