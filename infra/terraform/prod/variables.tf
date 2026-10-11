variable "cloud" {
  description = "Entry in clouds.yaml to use; must reach the lab's internal API endpoints."
  type        = string
  default     = "homelab-lan"
}

variable "admin_cidr" {
  description = "Where SSH is allowed from: the home LAN (the floating IP is a LAN address)."
  type        = string
  default     = "192.168.0.0/24"
}
