output "kind_host_public_ip" {
  description = "Public IP of the EC2 instance running kind"
  value       = module.ec2_kind_host.public_ip
}

output "kind_host_instance_id" {
  description = "Instance ID of the EC2 host"
  value       = module.ec2_kind_host.instance_id
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "private_subnets" {
  description = "Private subnet IDs"
  value       = module.vpc.private_subnets
}