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

# Region was previously implicit (picked up from the AWS_REGION env var set
# by CI's configure-aws-credentials step) - made explicit here so `terraform
# apply` behaves identically in CI and when a person runs it locally with
# no env vars set. Must stay us-east-1 to match the S3 backend bucket
# above and the AWS_REGION used in .github/workflows/infrastructure.yml
# and .github/workflows/deploy.yml.
provider "aws" {
  region = var.aws_region
}

module "vpc" {
  source = "./modules/vpc"

  name     = "${var.project_name}-${var.environment}"
  vpc_cidr = var.vpc_cidr
}

/*
module "eks" {
  source = "../../modules/eks"
  public_subnet_ids  =  module.vpc.public_subnets
  cluster_name       = var.cluster_name
  vpc_id             = module.vpc.vpc_id
  # private_subnet_ids = module.vpc.private_subnets
} */
