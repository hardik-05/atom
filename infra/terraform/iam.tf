data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# Instance profile — the role that matters most, because a compromise of the
# engine inherits it.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "engine" {
  name = "atom-engine-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.engine.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "engine" {
  name = "atom-engine-policy"
  role = aws_iam_role.engine.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadSecretsByPath"
        Effect = "Allow"
        Action = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = [
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/atom/*"
        ]
      },
      {
        # Write access is narrowed to the daily-session path only. The engine
        # creates and destroys tokens; it must not be able to overwrite a
        # long-lived broker key, which would let a compromise lock the operator
        # out or plant its own credential.
        Sid    = "WriteDailySessionsOnly"
        Effect = "Allow"
        Action = ["ssm:PutParameter", "ssm:DeleteParameter", "ssm:DeleteParameters"]
        Resource = [
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/atom/sessions/*"
        ]
      },
      {
        Sid      = "DecryptWithAtomKey"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:DescribeKey"]
        Resource = [aws_kms_key.atom.arn]
      },
      {
        # Writing the day's broker token to /atom/sessions/* as a SecureString
        # encrypts it with this key. Decrypt alone -- which is all this role had --
        # would have failed the first token exchange with AccessDenied from KMS,
        # an error that names the key and not the thing that was being written.
        #
        # Scoped by encryption context to SSM parameters under /atom/sessions/,
        # so this grant cannot be used to encrypt anything else with the key.
        Sid      = "EncryptDailySessions"
        Effect   = "Allow"
        Action   = ["kms:Encrypt", "kms:GenerateDataKey"]
        Resource = [aws_kms_key.atom.arn]
        Condition = {
          StringLike = {
            "kms:EncryptionContext:PARAMETER_ARN" = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/atom/sessions/*"
          }
        }
      },
      {
        Sid      = "ReadReleases"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.artifacts.arn}/releases/*"]
      },
      {
        Sid    = "AppendLogs"
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.logs.arn,
          "${aws_s3_bucket.logs.arn}/*",
          aws_s3_bucket.archive.arn,
          "${aws_s3_bucket.archive.arn}/*",
        ]
      },
      {
        # Explicit denies, written even though nothing grants these, because a
        # future convenience grant cannot silently override a Deny.
        #
        # ec2:* in particular: the engine must never be able to modify its own
        # networking. Detaching or reassociating an Elastic IP is a week-long
        # outage on Dhan (D-173).
        Sid    = "NeverTouchNetworkingOrDeleteLogs"
        Effect = "Deny"
        Action = [
          "ec2:*",
          "iam:*",
          "s3:DeleteObject",
          "s3:DeleteObjectVersion",
          "s3:PutBucketPolicy",
        ]
        Resource = ["*"]
      },
    ]
  })
}

resource "aws_iam_instance_profile" "engine" {
  name = "atom-engine-profile"
  role = aws_iam_role.engine.name
}

# ---------------------------------------------------------------------------
# Lambda control-plane role.
#
# Scoped by resource tag so it cannot touch any other instance in the account,
# and with no path to broker credentials — which is what bounds the damage of a
# leaked Telegram bot token to "someone can turn a computer on and off".
# ---------------------------------------------------------------------------

resource "aws_iam_role" "control" {
  name = "atom-control-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "control" {
  name = "atom-control-policy"
  role = aws_iam_role.control.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:*"]
      },
      {
        Sid      = "DescribeInstances"
        Effect   = "Allow"
        Action   = ["ec2:DescribeInstances", "ec2:DescribeInstanceStatus"]
        Resource = ["*"] # Describe* cannot be resource-scoped by the API
      },
      {
        Sid    = "StartStopOnlyAtomInstances"
        Effect = "Allow"
        Action = ["ec2:StartInstances", "ec2:StopInstances"]
        Resource = [
          "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/*"
        ]
        Condition = {
          StringEquals = { "aws:ResourceTag/atom:managed" = "true" }
        }
      },
      {
        # Telegram credentials only. No path to /atom/brokers or /atom/sessions.
        Sid    = "TelegramSecretsOnly"
        Effect = "Allow"
        Action = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = [
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/atom/telegram/*"
        ]
      },
      {
        Sid      = "DecryptWithAtomKey"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = [aws_kms_key.atom.arn]
      },
      {
        Sid    = "NoBrokerSecretsEver"
        Effect = "Deny"
        Action = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = [
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/atom/brokers/*",
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/atom/sessions/*",
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/atom/db/*",
        ]
      },
    ]
  })
}
