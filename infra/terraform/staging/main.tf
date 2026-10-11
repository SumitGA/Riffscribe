# Staging (ADR-0010): one small VM in the home lab, from the shared module.

module "vm" {
  source       = "../modules/riffscribe-vm"
  environment  = "staging"
  name         = "riffscribe-staging"
  vcpus        = 2
  ram_mb       = 3072 # idles at ~1 GB, a transcription adds ~0.4 GB; production gets the room
  network_cidr = "10.20.0.0/24"
  admin_cidr   = var.admin_cidr
}

# The resources were in this root module before the shared module existed (2026-10-11).
moved {
  from = openstack_compute_flavor_v2.staging
  to   = module.vm.openstack_compute_flavor_v2.this
}

moved {
  from = openstack_compute_keypair_v2.admin
  to   = module.vm.openstack_compute_keypair_v2.admin
}

moved {
  from = openstack_networking_network_v2.staging
  to   = module.vm.openstack_networking_network_v2.this
}

moved {
  from = openstack_networking_subnet_v2.staging
  to   = module.vm.openstack_networking_subnet_v2.this
}

moved {
  from = openstack_networking_router_v2.staging
  to   = module.vm.openstack_networking_router_v2.this
}

moved {
  from = openstack_networking_router_interface_v2.staging
  to   = module.vm.openstack_networking_router_interface_v2.this
}

moved {
  from = openstack_networking_secgroup_v2.staging
  to   = module.vm.openstack_networking_secgroup_v2.this
}

moved {
  from = openstack_networking_secgroup_rule_v2.egress
  to   = module.vm.openstack_networking_secgroup_rule_v2.egress
}

moved {
  from = openstack_networking_secgroup_rule_v2.ssh
  to   = module.vm.openstack_networking_secgroup_rule_v2.ssh
}

moved {
  from = openstack_compute_instance_v2.vm
  to   = module.vm.openstack_compute_instance_v2.vm
}

moved {
  from = openstack_networking_floatingip_v2.lan
  to   = module.vm.openstack_networking_floatingip_v2.lan
}

moved {
  from = openstack_networking_floatingip_associate_v2.lan
  to   = module.vm.openstack_networking_floatingip_associate_v2.lan
}
