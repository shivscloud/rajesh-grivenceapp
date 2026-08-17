# Production environment configuration
# Copy values from your actual AWS setup

aws_region   = "us-east-1"
environment  = "prod"
project_name = "rajesh-grievanceapp"

# EC2 Configuration (REQUIRED - update these)
key_name           = "rajesh-app-prod-key"  # Auto-created by workflow if missing
allowed_ssh_cidr   = "0.0.0.0/0"                # TODO: restrict to your IP
allowed_app_cidr   = "0.0.0.0/0"               # Or restrict to specific IPs

# Application Configuration
app_node_port_host = 8080
k8s_namespace      = "grievance-system"
helm_release_name  = "rajeshapp"
helm_chart_path    = "helm/rajeshapp"

# VPC Configuration
vpc_cidr = "10.0.0.0/16"

# EKS Configuration
cluster_name = "rajesh-grievanceapp-prod"

# Repository URL
repo_url = "https://github.com/shivscloud/rajesh-grivenceapp.git"
