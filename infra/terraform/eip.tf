# ---------------------------------------------------------------------------
# Elastic IPs — one per investor.
#
# 🔴 These are the most operationally dangerous resources in the stack.
#
# Dhan locks a registered IP for 7 days (D-173). An address that changes is not a
# restartable error: it is up to a week during which that account cannot place
# orders, with no override.
#
# Therefore:
#   * `prevent_destroy` is set. `terraform destroy` will refuse until someone
#     removes it deliberately, which is the intent.
#   * `dev` gets none, so a dev account has no proxy_url and the database CHECK
#     constraint makes a LIVE dev account impossible.
# ---------------------------------------------------------------------------

resource "aws_eip" "investor" {
  count  = var.env == "prod" ? var.investor_count : 0
  domain = "vpc"

  tags = {
    Name                  = "atom-investor-${count.index + 1}"
    "atom:purpose"        = "broker-egress"
    "atom:investor"       = tostring(count.index + 1)
    "atom:do-not-release" = "true"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Associate each EIP with its own secondary private IP on the instance's ENI, so
# one nginx listener per investor can bind to a distinct source address.
resource "aws_eip_association" "investor" {
  count                = var.env == "prod" ? var.investor_count : 0
  allocation_id        = aws_eip.investor[count.index].id
  network_interface_id = aws_instance.engine.primary_network_interface_id
  private_ip_address   = count.index == 0 ? aws_instance.engine.private_ip : cidrhost("10.0.1.0/24", 10 + count.index)
}
