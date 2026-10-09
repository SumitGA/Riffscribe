# The staging VM (ADR-0010): one instance with a floating IP, a firewall that allows SSH only
# from the owner's address and HTTP(S) from anywhere, and a separate data volume for Postgres
# so the instance can be rebuilt without losing data.

resource "openstack_compute_keypair_v2" "admin" {
  name       = "${var.name}-admin"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "openstack_networking_secgroup_v2" "staging" {
  name                 = var.name
  description          = "Riffscribe staging: SSH from the owner, HTTP(S) from anywhere"
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

resource "openstack_networking_secgroup_rule_v2" "web" {
  for_each = {
    http      = { protocol = "tcp", port = 80 }
    https     = { protocol = "tcp", port = 443 }
    https_udp = { protocol = "udp", port = 443 } # HTTP/3
  }
  security_group_id = openstack_networking_secgroup_v2.staging.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = each.value.protocol
  port_range_min    = each.value.port
  port_range_max    = each.value.port
  remote_ip_prefix  = "0.0.0.0/0"
}

resource "openstack_blockstorage_volume_v3" "data" {
  name        = "${var.name}-data"
  size        = var.data_volume_gb
  volume_type = var.volume_type
  lifecycle {
    prevent_destroy = true # Postgres lives here; destroying it needs a deliberate code change
  }
}

resource "openstack_compute_instance_v2" "vm" {
  name            = var.name
  image_name      = var.image_name
  flavor_name     = var.flavor_name
  key_pair        = openstack_compute_keypair_v2.admin.name
  security_groups = [openstack_networking_secgroup_v2.staging.name]
  user_data       = file("${path.module}/cloud-init.yaml")

  network {
    name = var.network_name
  }

  lifecycle {
    ignore_changes = [user_data, image_name] # rebuilds are deliberate (taint), not drift
  }
}

resource "openstack_compute_volume_attach_v2" "data" {
  instance_id = openstack_compute_instance_v2.vm.id
  volume_id   = openstack_blockstorage_volume_v3.data.id
}

resource "openstack_networking_floatingip_v2" "public" {
  pool = var.external_network_name
}

data "openstack_networking_port_v2" "vm" {
  device_id  = openstack_compute_instance_v2.vm.id
  network_id = openstack_compute_instance_v2.vm.network[0].uuid
}

resource "openstack_networking_floatingip_associate_v2" "public" {
  floating_ip = openstack_networking_floatingip_v2.public.address
  port_id     = data.openstack_networking_port_v2.vm.id
}
