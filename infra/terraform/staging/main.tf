# The staging VM in the home lab (ADR-0010): its own flavor, network and router (SNAT to the
# LAN), and a floating IP that is a LAN address. The internet never connects in: the VM's
# cloudflared opens an outbound Cloudflare Tunnel, so the security group only allows SSH from
# the LAN. The lab has no block storage, so Postgres lives on the root disk and the nightly
# R2 backup is the safety net.

resource "openstack_compute_flavor_v2" "staging" {
  name      = "${var.name}.vm"
  vcpus     = var.vcpus
  ram       = var.ram_mb
  disk      = var.disk_gb
  is_public = true
}

resource "openstack_compute_keypair_v2" "admin" {
  name       = "${var.name}-admin"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

data "openstack_networking_network_v2" "external" {
  name     = var.external_network_name
  external = true
}

resource "openstack_networking_network_v2" "staging" {
  name = "${var.name}-net"
}

resource "openstack_networking_subnet_v2" "staging" {
  name            = "${var.name}-subnet"
  network_id      = openstack_networking_network_v2.staging.id
  cidr            = var.network_cidr
  dns_nameservers = var.dns_nameservers
}

resource "openstack_networking_router_v2" "staging" {
  name                = "${var.name}-router"
  external_network_id = data.openstack_networking_network_v2.external.id
}

resource "openstack_networking_router_interface_v2" "staging" {
  router_id = openstack_networking_router_v2.staging.id
  subnet_id = openstack_networking_subnet_v2.staging.id
}

resource "openstack_networking_secgroup_v2" "staging" {
  name                 = var.name
  description          = "Riffscribe staging: SSH from the LAN; everything else leaves via the tunnel"
  delete_default_rules = true
}

resource "openstack_networking_secgroup_rule_v2" "egress" {
  for_each          = toset(["IPv4", "IPv6"])
  security_group_id = openstack_networking_secgroup_v2.staging.id
  direction         = "egress"
  ethertype         = each.value
}

resource "openstack_networking_secgroup_rule_v2" "ssh" {
  security_group_id = openstack_networking_secgroup_v2.staging.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = var.admin_cidr
}

resource "openstack_compute_instance_v2" "vm" {
  name            = var.name
  image_name      = var.image_name
  flavor_id       = openstack_compute_flavor_v2.staging.id
  key_pair        = openstack_compute_keypair_v2.admin.name
  security_groups = [openstack_networking_secgroup_v2.staging.name]
  user_data       = file("${path.module}/cloud-init.yaml")

  network {
    uuid = openstack_networking_network_v2.staging.id
  }

  depends_on = [openstack_networking_router_interface_v2.staging] # outbound access at first boot

  lifecycle {
    ignore_changes = [user_data, image_name] # rebuilds are deliberate (-replace), not drift
  }
}

resource "openstack_networking_floatingip_v2" "lan" {
  pool = var.external_network_name
}

data "openstack_networking_port_v2" "vm" {
  device_id  = openstack_compute_instance_v2.vm.id
  network_id = openstack_networking_network_v2.staging.id
}

resource "openstack_networking_floatingip_associate_v2" "lan" {
  floating_ip = openstack_networking_floatingip_v2.lan.address
  port_id     = data.openstack_networking_port_v2.vm.id
}
