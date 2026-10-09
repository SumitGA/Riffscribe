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
provider "openstack" {
  cloud = var.cloud
}
