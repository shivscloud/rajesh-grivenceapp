 backend "s3" {
    bucket  = "rajesh-grievanceapp-tfstate"   # must match the CLI-created bucket below
    key     = "eks/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
    # dynamodb_table = "rajesh-grievanceapp-tf-lock"   # uncomment — see locking note below
  }
