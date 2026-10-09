variable "cloud" {
  description = "Entry in clouds.yaml to use; must reach the lab's internal API endpoints."
  type        = string
  default     = "homelab-lan"
}

variable "name" {
  description = "Prefix for every resource's name."
  type        = string
  default     = "riffscribe-staging"
}

variable "image_name" {
  description = "Ubuntu 24.04 image in the cloud (`openstack image list`)."
  type        = string
  default     = "ubuntu-24.04"
}

variable "vcpus" {
  description = "VM size: vCPUs."
  type        = number
  default     = 4
}

variable "ram_mb" {
  description = "VM size: RAM in MB (the lab host also runs OpenStack; leave it headroom)."
  type        = number
  default     = 6144
}

variable "disk_gb" {
  description = "VM size: root disk in GB. Postgres lives here (no block storage in the lab)."
  type        = number
  default     = 40
}

variable "external_network_name" {
  description = "External network for the router gateway and the floating IP (`openstack network list --external`)."
  type        = string
  default     = "public1"
}

variable "network_cidr" {
  description = "Staging's own private network."
  type        = string
  default     = "10.20.0.0/24"
}

variable "dns_nameservers" {
  description = "DNS servers handed to the VM."
  type        = list(string)
  default     = ["1.1.1.1", "8.8.8.8"]
}

variable "ssh_public_key_path" {
  description = "Public key allowed to log in as `ubuntu`."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "admin_cidr" {
  description = "Where SSH is allowed from: the home LAN (the floating IP is a LAN address)."
  type        = string
  default     = "192.168.0.0/24"
  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0"
    error_message = "admin_cidr must be a CIDR and not the whole internet."
  }
}
