terraform {
  required_version = ">= 1.5.0"
  backend "s3" {
    bucket  = "rajesh-grievanceapp-tfstate"   # must match the CLI-created bucket below
    key     = "eks/terraform.tfstate"
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

module "eks" {
  source = "../../modules/eks"
  public_subnet_ids  =  module.vpc.public_subnets
  cluster_name       = var.cluster_name
  vpc_id             = module.vpc.vpc_id
  # private_subnet_ids = module.vpc.private_subnets
}