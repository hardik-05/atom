# One VPC, one public subnet, one AZ.
#
# No NAT gateway: it would cost ~$32/month — four times the entire bill — and buy
# nothing, because the design requires a *public* static source address, which is
# exactly what an Elastic IP on a public subnet provides.

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "atom-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "atom-igw" }
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = false # every address here is an explicitly managed EIP
  tags                    = { Name = "atom-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "atom-public-rt" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "engine" {
  name        = "atom-engine"
  description = "ATOM engine: console inbound on 443 only; port 22 closed by design"
  vpc_id      = aws_vpc.main.id

  # Port 22 is deliberately absent. SSM Session Manager gives a shell through the
  # AWS API with IAM auth and CloudTrail logging, needs no inbound rule and no key
  # pair, and removes the largest attack surface a small deployment has.
  ingress {
    description = "Console (TLS; admin login and TOTP behind it)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.allow_console_from
  }

  # Broker endpoints are documented by hostname and change without notice, so
  # allow-all egress is deliberate. The meaningful control is the *source*
  # address, enforced by the forward proxy binding (STATIC-IP-AND-PROXY.md).
  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "atom-engine-sg" }
}
