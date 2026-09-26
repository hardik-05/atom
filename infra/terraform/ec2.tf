data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

locals {
  # Secondary private IPs for investors 2..N. Investor 1 uses the primary.
  secondary_private_ips = var.env == "prod" && var.investor_count > 1 ? [
    for i in range(1, var.investor_count) : cidrhost("10.0.1.0/24", 10 + i)
  ] : []
}

resource "aws_instance" "engine" {
  ami                     = data.aws_ssm_parameter.al2023.value
  instance_type           = var.instance_type
  subnet_id               = aws_subnet.public.id
  vpc_security_group_ids  = [aws_security_group.engine.id]
  iam_instance_profile    = aws_iam_instance_profile.engine.name
  key_name                = var.ssh_key_name
  private_ip              = cidrhost("10.0.1.0/24", 10)
  secondary_private_ips   = local.secondary_private_ips
  monitoring              = false
  disable_api_termination = var.env == "prod"

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 only
  }

  root_block_device {
    volume_size           = 8
    volume_type           = "gp3"
    encrypted             = true
    kms_key_id            = aws_kms_key.atom.arn
    delete_on_termination = false # keep the volume; the data is cheap to retain
  }

  user_data_replace_on_change = false
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    region                = var.region
    env                   = var.env
    idle_shutdown_minutes = var.idle_shutdown_minutes
    investor_count        = var.env == "prod" ? var.investor_count : 0
  })

  tags = {
    Name           = "atom-engine"
    "atom:managed" = "true" # the Lambda's IAM condition keys off this
  }

  lifecycle {
    # The AMI id moves whenever Amazon publishes a new Linux release. Replacing the
    # instance is a deliberate, runbooked act (DEPLOYMENT.md section 6) because it
    # touches Elastic IP associations — never something a terraform apply should do
    # on its own.
    ignore_changes = [ami, user_data]
  }
}
