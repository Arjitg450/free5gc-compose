variable "iso_url" {
  type        = string
  description = "URL of the Ubuntu 22.04.5 ISO"
  default     = "https://releases.ubuntu.com/22.04/ubuntu-22.04.5-live-server-amd64.iso"
}

variable "iso_checksum" {
  type        = string
  description = "SHA256 checksum of the ISO"
  default     = "sha256:9bc6028870aef3f74f4e16b900008179e78b130e6b0b9a140635434a46aa98b0"
}

variable "vm_name" {
  type        = string
  description = "Name of the output VM"
  default     = "ubuntu-22.04.5-free5gc"
}

variable "memory" {
  type        = number
  description = "VM RAM in MB"
  default     = 4096
}

variable "cpus" {
  type        = number
  description = "Number of vCPUs"
  default     = 2
}

variable "disk_size" {
  type        = number
  description = "Disk size in MB"
  default     = 40960
}

variable "headless" {
  type        = bool
  description = "Run build in headless mode"
  default     = true
}
