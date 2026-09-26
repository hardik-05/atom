resource "aws_kms_key" "atom" {
  description             = "ATOM secrets and logs. Customer-managed so kms:Decrypt is an auditable, revocable grant rather than an ambient capability."
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = { Name = "atom-cmk" }
}

resource "aws_kms_alias" "atom" {
  name          = "alias/atom"
  target_key_id = aws_kms_key.atom.key_id
}

# --------------------------------------------------------------- logs, rolling

resource "aws_s3_bucket" "logs" {
  bucket = "atom-logs-${data.aws_caller_identity.current.account_id}-${var.env}"
  tags   = { Name = "atom-logs" }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.atom.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    id     = "expire-30-days"
    status = "Enabled"
    filter {}
    expiration { days = 30 }
  }
}

# --------------------------------------------------- archive, permanent

resource "aws_s3_bucket" "archive" {
  bucket = "atom-logs-archive-${data.aws_caller_identity.current.account_id}-${var.env}"
  tags   = { Name = "atom-logs-archive" }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "archive" {
  bucket = aws_s3_bucket.archive.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.atom.arn
    }
    bucket_key_enabled = true
  }
}

# Object Lock in governance mode: deletion needs a separate privileged action, not
# the engine's credentials. A compromised engine can append misleading new logs;
# it cannot remove old ones — and appending is detectable by comparing copies
# while silent deletion is not.
resource "aws_s3_bucket_object_lock_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = 3650
    }
  }
  depends_on = [aws_s3_bucket_versioning.archive]
}

resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    id     = "deep-archive-immediately"
    status = "Enabled"
    filter {}
    transition {
      days          = 0
      storage_class = "DEEP_ARCHIVE"
    }
  }
}
