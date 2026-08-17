terraform {
  required_version = ">= 1.5.0"
  backend "s3" {
    bucket  = "rajesh-grievanceapp-tfstate"   # must match the CLI-created bucket below
    key     = "rajeshnew/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
    # dynamodb_table = "rajesh-grievanceapp-tf-lock"   # uncomment — see locking note below
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}


module "vpc" {
  source = "../../modules/vpc"

  name     = "${var.project_name}-${var.environment}"
  vpc_cidr = var.vpc_cidr
}

module "ec2_kind_host" {
  source = "../../modules/ec2-kind-host"

  name_prefix            = "${var.project_name}-${var.environment}-kind"
  vpc_id                 = module.vpc.vpc_id
  subnet_id              = module.vpc.public_subnets[0]
  key_name               = var.key_name
  allowed_ssh_cidr       = var.allowed_ssh_cidr
  allowed_app_cidr       = var.allowed_app_cidr
  app_node_port_host     = var.app_node_port_host
  repo_url               = var.repo_url
  k8s_namespace          = var.k8s_namespace
  helm_release_name      = var.helm_release_name
  helm_chart_path        = var.helm_chart_path
}

