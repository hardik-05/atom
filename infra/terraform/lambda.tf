data "archive_file" "control" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/control"
  output_path = "${path.module}/.build/atom-control.zip"
}

resource "aws_lambda_function" "control" {
  function_name = "atom-control"
  role          = aws_iam_role.control.arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 128

  # A flood cannot spin up cost, and it bounds any retry storm.
  reserved_concurrent_executions = 2

  filename         = data.archive_file.control.output_path
  source_code_hash = data.archive_file.control.output_base64sha256

  environment {
    variables = {
      ATOM_INSTANCE_ID = aws_instance.engine.id
      ATOM_SSM_PREFIX  = "/atom/telegram"
      # No secrets here. A Lambda environment variable is visible in the console
      # and to anyone with GetFunctionConfiguration; the bot token is read from
      # SSM at invocation instead.
      ATOM_CONSOLE_URL = var.env == "prod" && var.investor_count > 0 ? "https://${aws_eip.investor[0].public_ip}" : ""
    }
  }

  tags = { Name = "atom-control" }
}

resource "aws_lambda_function_url" "control" {
  function_name      = aws_lambda_function.control.function_name
  authorization_type = "NONE" # Telegram cannot sign; the secret token authenticates
}

resource "aws_cloudwatch_log_group" "control" {
  name              = "/aws/lambda/${aws_lambda_function.control.function_name}"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.atom.arn
}

# ---------------------------------------------------------------------------
# SSM parameter shells.
#
# Terraform creates the parameters but NOT their values: a secret in a .tf file or
# in state is a secret in git. `ignore_changes = [value]` means the operator sets
# the real value once with `aws ssm put-parameter --overwrite` and Terraform never
# touches it again.
# ---------------------------------------------------------------------------

locals {
  telegram_params = {
    "bot_token"        = "set-me"
    "webhook_secret"   = "set-me"
    "allowed_user_ids" = join(",", var.telegram_allowed_user_ids)
  }
}

resource "aws_ssm_parameter" "telegram" {
  for_each = local.telegram_params

  name   = "/atom/telegram/${each.key}"
  type   = "SecureString"
  key_id = aws_kms_key.atom.arn
  value  = each.value

  lifecycle {
    ignore_changes = [value]
  }
}
