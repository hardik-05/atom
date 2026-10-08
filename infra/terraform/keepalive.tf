# ---------------------------------------------------------------------------
# Database keep-alive.
#
# Supabase's free tier pauses a project after about a week without activity, and
# the EC2 instance -- stopped by its idle timer most of the time -- cannot be what
# keeps it awake. A paused database took the console down on 2026-10-08: the
# pooler answered "tenant/user not found", the engine's startup pool check failed
# and Caddy served 502.
#
# One `SELECT now()` a day, as `atom_keepalive`: a login role with no membership
# and no grants, whose DSN sits at its own SSM path. This function never holds the
# engine's credential, and the credential it does hold can read nothing.
# ---------------------------------------------------------------------------

# pg8000 is installed into the package directory by build.py at plan time; the
# `external` data source runs it, so a fresh clone needs no separate build step.
data "external" "keepalive_build" {
  program = ["python", "${path.module}/../lambda/keepalive/build.py"]
}

data "archive_file" "keepalive" {
  type        = "zip"
  source_dir  = data.external.keepalive_build.result.dir
  excludes    = [".requirements.sha256"]
  output_path = "${path.module}/.build/atom-keepalive.zip"
}

resource "aws_ssm_parameter" "keepalive_dsn" {
  name   = "/atom/keepalive/db_dsn"
  type   = "SecureString"
  key_id = aws_kms_key.atom.arn
  value  = "set-me" # `python -m atom.cli db-keepalive-login` sets the real value

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_iam_role" "keepalive" {
  name = "atom-keepalive-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "keepalive" {
  name = "atom-keepalive-policy"
  role = aws_iam_role.keepalive.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.keepalive.arn}:*"]
      },
      {
        # This one parameter. Not /atom/db/*, not /atom/brokers/*.
        Sid      = "KeepaliveDsnOnly"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = [aws_ssm_parameter.keepalive_dsn.arn]
      },
      {
        Sid      = "DecryptKeepaliveDsnOnly"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = [aws_kms_key.atom.arn]
        Condition = {
          StringEquals = {
            "kms:EncryptionContext:PARAMETER_ARN" = aws_ssm_parameter.keepalive_dsn.arn
          }
        }
      },
    ]
  })
}

resource "aws_lambda_function" "keepalive" {
  function_name = "atom-keepalive"
  role          = aws_iam_role.keepalive.arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 128

  filename         = data.archive_file.keepalive.output_path
  source_code_hash = data.archive_file.keepalive.output_base64sha256

  environment {
    variables = {
      ATOM_KEEPALIVE_DSN_PARAMETER = aws_ssm_parameter.keepalive_dsn.name
    }
  }

  # The log group must exist first: the role may write to it but not create it.
  depends_on = [aws_cloudwatch_log_group.keepalive]

  tags = { Name = "atom-keepalive" }
}

resource "aws_cloudwatch_log_group" "keepalive" {
  name              = "/aws/lambda/atom-keepalive"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.atom.arn
}

# Daily at 03:30 UTC (09:00 IST). A failed invocation is retried twice by the
# asynchronous invoke, and a whole missed day still leaves six before a pause.
resource "aws_cloudwatch_event_rule" "keepalive" {
  name                = "atom-keepalive-daily"
  description         = "One query a day so the Supabase free tier never pauses the ATOM database"
  schedule_expression = "cron(30 3 * * ? *)"
}

resource "aws_cloudwatch_event_target" "keepalive" {
  rule = aws_cloudwatch_event_rule.keepalive.name
  arn  = aws_lambda_function.keepalive.arn
}

resource "aws_lambda_permission" "keepalive_schedule" {
  statement_id  = "AllowDailySchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.keepalive.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.keepalive.arn
}
