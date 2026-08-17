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

