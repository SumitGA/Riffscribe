# Production (ADR-0012): its own VM in the home lab, from the shared module; nothing is shared
# with staging (own network, flavor, keys, and on the VM its own database, tunnel and bucket).

module "vm" {
  source       = "../modules/riffscribe-vm"
  environment  = "prod"
  name         = "riffscribe-prod"
  vcpus        = 4
  ram_mb       = 6144
  network_cidr = "10.30.0.0/24"
  admin_cidr   = var.admin_cidr
}
