variable "region" {
  description = "AWS region. ap-south-1 keeps latency to Indian brokers low and data in India."
  type        = string
  default     = "ap-south-1"
}

variable "env" {
  description = "Environment name. `dev` gets no Elastic IP and therefore cannot trade."
  type        = string
  default     = "prod"
  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be dev or prod."
  }
}

variable "instance_type" {
  description = "t3a is ~10% cheaper than t3 for identical specs; `small` for the 2 GiB, not the CPU."
  type        = string
  default     = "t3a.small"
}

variable "investor_count" {
  description = <<-EOT
    Number of investors, and therefore Elastic IPv4 addresses.

    Each address bills 24x7 at $0.005/hour whether or not the instance runs, so
    this is the dominant cost line. Starting at 1 per the current requirement.
  EOT
  type        = number
  default     = 1
  validation {
    condition     = var.investor_count >= 1 && var.investor_count <= 3
    error_message = "1-3 investors; a t3a.small has room for more but re-check the ENI IPv4 limit first."
  }
}

variable "allow_console_from" {
  description = "CIDRs permitted to reach the console on 443. Narrow this to the operator's addresses if they are static."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "idle_shutdown_minutes" {
  description = "Auto-shutdown after this many idle minutes (D-055a)."
  type        = number
  default     = 60
}

variable "telegram_allowed_user_ids" {
  description = "Numeric Telegram user IDs permitted to drive the control plane (D-014). Numeric, never usernames — usernames can be changed and reused."
  type        = list(string)
  default     = []
  sensitive   = true
}

variable "ssh_key_name" {
  description = "Optional EC2 key pair. Leave null: access is via SSM Session Manager and port 22 stays closed."
  type        = string
  default     = null
}
