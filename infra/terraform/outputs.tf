output "instance_id" {
  description = "Pass this to the control Lambda and the runbook."
  value       = aws_instance.engine.id
}

output "instance_private_ip" {
  value = aws_instance.engine.private_ip
}

output "investor_egress_ips" {
  description = <<-EOT
    The addresses to register with each broker.

    🔴 Register these, and the backup slot where a broker offers one, only AFTER
    `scripts/verify_egress_ip.py` passes. Registration is what engages Dhan's
    7-day lock.
  EOT
  value       = var.env == "prod" ? aws_eip.investor[*].public_ip : []
}

output "investor_eip_allocation_ids" {
  description = "Record these. The rebuild procedure begins by confirming they still exist."
  value       = var.env == "prod" ? aws_eip.investor[*].id : []
}

output "console_url" {
  description = "The console is served on the first investor's Elastic IP (D-078). Point the Route 53 A record here."
  value       = var.env == "prod" && var.investor_count > 0 ? "https://${aws_eip.investor[0].public_ip}" : null
}

output "control_lambda_function_url" {
  description = "Register this as the Telegram webhook, with the secret token."
  value       = aws_lambda_function_url.control.function_url
}

output "logs_bucket" {
  value = aws_s3_bucket.logs.id
}

output "archive_bucket" {
  value = aws_s3_bucket.archive.id
}

output "kms_key_arn" {
  value = aws_kms_key.atom.arn
}
