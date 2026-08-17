terraform {
  required_version = ">= 1.5"
}

module "vpc" {
  source = "../../modules/vpc"

  name     = "${var.project_name}-${var.environment}"
  vpc_cidr = var.vpc_cidr
}

module "eks" {
  source = "../../modules/eks"

  cluster_name       = var.cluster_name
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnets
}
