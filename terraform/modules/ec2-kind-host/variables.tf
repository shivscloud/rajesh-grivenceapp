variable "vpc_id" {
  description = "Existing VPC ID to deploy into"
  type        = string
}

variable "subnet_id" {
  description = "Existing (public) subnet ID inside the VPC to launch the EC2 instance in"
  type        = string
}

variable "key_name" {
  description = "Name of an existing EC2 key pair for SSH access"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type. Restricted to the org's allowed list."
  type        = string
  default     = "t3.small"

  validation {
    condition = contains([
      "t2.nano", "t2.micro", "t2.small", "t2.medium",
      "t3.nano", "t3.micro", "t3.small", "t3.medium"
    ], var.instance_type)
    error_message = "instance_type must be one of: t2.nano, t2.micro, t2.small, t2.medium, t3.nano, t3.micro, t3.small, t3.medium."
  }
}

variable "ami_id" {
  description = "AMI ID to use. Leave null to auto-select the latest Ubuntu 22.04 AMI (allowed OS)."
  type        = string
  default     = null
}

variable "allowed_ssh_cidr" {
  description = "CIDR allowed to SSH into the instance (lock this down to your IP/office range)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "app_node_port_host" {
  description = "Host port on the EC2 instance that maps to the frontend-service NodePort (30080) inside kind"
  type        = number
  default     = 8080
}

variable "allowed_app_cidr" {
  description = "CIDR allowed to reach the application port"
  type        = string
  default     = "0.0.0.0/0"
}

variable "repo_url" {
  description = "Git repo to clone and deploy"
  type        = string
  default     = "https://github.com/shivscloud/rajesh-grivenceapp.git"
}

variable "name_prefix" {
  description = "Prefix for resource names/tags"
  type        = string
  default     = "rajesh-grievanceapp-kind"
}

variable "k8s_namespace" {
  description = "Kubernetes namespace the Helm release is installed into"
  type        = string
  default     = "grievance-system"
}

variable "helm_release_name" {
  description = "Helm release name"
  type        = string
  default     = "rajeshapp"
}

variable "helm_chart_path" {
  description = "Path to the Helm chart within the cloned repo (relative to the repo root, resolved on the instance)"
  type        = string
  default     = "helm/rajeshapp"
}
