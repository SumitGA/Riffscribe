output "public_ip" {
  description = "Point the DNS A record for api-staging.<your domain> here."
  value       = openstack_networking_floatingip_v2.public.address
}

output "ssh" {
  description = "Log in to the VM."
  value       = "ssh ubuntu@${openstack_networking_floatingip_v2.public.address}"
}
