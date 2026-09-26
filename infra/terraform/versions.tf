terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
  # Remote state is strongly recommended before the first apply that allocates an
  # Elastic IP. Losing state here means losing track of an address that, once
  # registered with Dhan, cannot be changed for 7 days.
  #
  # backend "s3" {
  #   bucket = "atom-tfstate-<account>"
  #   key    = "atom/terraform.tfstate"
  #   region = "ap-south-1"
  #   encrypt = true
  #   dynamodb_table = "atom-tflock"
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "atom"
      ManagedBy = "terraform"
      Env       = var.env
    }
  }
}
