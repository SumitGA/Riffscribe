variable "cloud" {
  description = "Entry in clouds.yaml to use."
  type        = string
  default     = "openstack"
}

variable "name" {
  description = "Prefix for every resource's name."
  type        = string
  default     = "riffscribe-staging"
}

variable "image_name" {
  description = "Ubuntu 24.04 image in your cloud (`openstack image list`)."
  type        = string
}

variable "flavor_name" {
  description = "VM size: 4 vCPU / 8 GB (`openstack flavor list`)."
  type        = string
}

variable "network_name" {
  description = "Private network the VM attaches to (`openstack network list`)."
  type        = string
}

variable "external_network_name" {
  description = "External network that hands out floating IPs."
  type        = string
}

variable "ssh_public_key_path" {
  description = "Public key allowed to log in as `ubuntu`."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "admin_cidr" {
  description = "Where SSH is allowed from: your public IP as a /32 (e.g. 203.0.113.7/32)."
  type        = string
  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0"
    error_message = "admin_cidr must be a CIDR and not the whole internet."
  }
}

variable "data_volume_gb" {
  description = "Size of the separate volume holding Postgres data."
  type        = number
  default     = 20
}

variable "volume_type" {
  description = "Block storage type for the data volume; null uses the cloud's default."
  type        = string
  default     = null
}
