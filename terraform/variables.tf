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