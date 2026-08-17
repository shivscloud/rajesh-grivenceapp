output "instance_id" {
  value = aws_instance.kind_host.id
}

output "public_ip" {
  value = aws_instance.kind_host.public_ip
}

output "ssh_command" {
  value = "ssh -i <path-to-key>.pem ubuntu@${aws_instance.kind_host.public_ip}"
}

output "app_url" {
  description = "Open this once bootstrap finishes (check /var/log/user-data.log on the instance for progress)"
  value       = "http://${aws_instance.kind_host.public_ip}:${var.app_node_port_host}"
}
