output "lan_ip" {
  description = "The VM's address on the home LAN (SSH and deploys)."
  value       = module.vm.lan_ip
}

output "ssh" {
  description = "Log in to the VM (from the LAN)."
  value       = module.vm.ssh
}
