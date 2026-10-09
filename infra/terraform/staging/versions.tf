terraform {
  required_version = ">= 1.6"
  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 3.0"
    }
  }
  # State stays in a local, git-ignored file for now (TD-30).
}

# Credentials come from clouds.yaml (~/.config/openstack/clouds.yaml), never from this repo.
# The lab's public endpoints sit behind Cloudflare's proxy, which doesn't forward OpenStack's
# ports, so every call uses the internal endpoints over the LAN (the provider ignores
# clouds.yaml's `interface`).
provider "openstack" {
  cloud         = var.cloud
  endpoint_type = "internal"
}
