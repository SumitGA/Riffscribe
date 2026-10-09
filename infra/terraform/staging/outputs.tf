output "lan_ip" {
  description = "The VM's address on the home LAN (SSH and deploys)."
  value       = openstack_networking_floatingip_v2.lan.address
}

output "ssh" {
  description = "Log in to the VM (from the LAN)."
  value       = "ssh ubuntu@${openstack_networking_floatingip_v2.lan.address}"
}
