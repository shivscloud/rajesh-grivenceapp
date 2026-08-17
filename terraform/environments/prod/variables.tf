variable "aws_region" {
  description = "AWS region"
  type        = string
  # Must match the S3 backend bucket's region in main.tf and the
  # AWS_REGION used by .github/workflows/infrastructure.yml + deploy.yml.
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Project name"
  type        = string
  default     = "rajesh-grievanceapp"
}

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "rajesh-grievanceapp-prod"
}

variable "vpc_cidr" {
  description = "VPC CIDR block"
  type        = string
  default     = "10.0.0.0/16"
}

variable "key_name" {
  description = "EC2 key pair name for SSH access"
  type        = string
}

variable "allowed_ssh_cidr" {
  description = "CIDR allowed to SSH to the instance"
  type        = string
  default     = "0.0.0.0/0"
}

variable "allowed_app_cidr" {
  description = "CIDR allowed to access the application"
  type        = string
  default     = "0.0.0.0/0"
}

variable "app_node_port_host" {
  description = "Host port mapped to the app NodePort"
  type        = number
  default     = 8080
}

variable "repo_url" {
  description = "Git repository URL to clone on the instance"
  type        = string
  default     = "https://github.com/shivscloud/rajesh-grivenceapp.git"
}

variable "k8s_namespace" {
  description = "Kubernetes namespace for the app"
  type        = string
  default     = "grievance-system"
}

variable "helm_release_name" {
  description = "Helm release name"
  type        = string
  default     = "rajeshapp"
}

variable "helm_chart_path" {
  description = "Path to Helm chart in the repo"
  type        = string
  default     = "helm/rajeshapp"
}