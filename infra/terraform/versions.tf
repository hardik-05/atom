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
  # Remote state, enabled before the first apply.
  #
  # Losing this file means losing track of an Elastic IP that, once registered
  # with Dhan, cannot be changed for 7 days (D-173). Terraform would no longer
  # know the address exists; the next apply would allocate a second one and
  # leave the first billing, unmanaged, and still whitelisted at the broker.
  # Versioning on the bucket means a corrupted state is recoverable rather than
  # merely lost.
  #
  # `use_lockfile` is S3-native locking, available since Terraform 1.10. It
  # replaces the DynamoDB table the older pattern required: one less resource to
  # create, pay for and forget to restore during a rebuild.
  #
  # SSE-S3 rather than the project's own KMS key on purpose -- that key is
  # created BY this configuration, so encrypting this configuration's state with
  # it would be circular: the state needed to find the key would itself need the
  # key to read.
  backend "s3" {
    bucket       = "atom-tfstate-905221883695"
    key          = "atom/terraform.tfstate"
    region       = "ap-south-1"
    encrypt      = true
    use_lockfile = true
  }
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
