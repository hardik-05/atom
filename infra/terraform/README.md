# ATOM infrastructure

Terraform for the whole stack: VPC, one EC2 instance, Elastic IPs, the control
Lambda, KMS, and two S3 buckets.

> ⚠️ **Not yet validated.** These files were written without a Terraform binary
> available, so `terraform validate` and `terraform plan` have not been run
> against them. Treat the first `plan` as a review step and expect to fix small
> things. Nothing here has been applied to an AWS account.

---

## 🔴 Read this before the first apply

**Elastic IPs are the most dangerous resource in this stack.** Dhan locks a
registered IP for **7 days** (D-173). An address that changes is not a
restartable error — it is up to a week during which that account cannot place
orders, with no override.

Consequences baked into the code:

| Guard | Where |
|---|---|
| `prevent_destroy` on every EIP | `eip.tf` — `terraform destroy` refuses until someone removes it deliberately |
| `atom:do-not-release = true` tag | `eip.tf` |
| Instance role **denies `ec2:*`** | `iam.tf` — the engine cannot detach its own address |
| `disable_api_termination` in prod | `ec2.tf` |
| `delete_on_termination = false` on the root volume | `ec2.tf` |
| `dev` gets **no** EIP | `eip.tf` — so a dev account has no `proxy_url`, and the database CHECK makes a LIVE dev account impossible |

**Use remote state** (the commented `backend "s3"` block in `versions.tf`) before
the first apply that allocates an address. Losing local state means losing track
of an EIP that may already be registered with a broker.

---

## Order of operations

The sequence is not interchangeable — registration is what engages the lock.

```
1  terraform init && terraform plan          # review, especially the EIP count
2  terraform apply                           # allocates the address
3  note the outputs: investor_egress_ips and investor_eip_allocation_ids
4  set the SSM secrets (below)
5  deploy the application per docs/02-infrastructure/DEPLOYMENT.md
6  python scripts/verify_egress_ip.py        # 🔴 MUST pass
7  ONLY NOW register the address with each broker, plus the backup slot
8  one DRY run per account
9  promote to LIVE
```

Step 6 before step 7. Registering an address ATOM has not proved it egresses from
means discovering the error after the lock has engaged.

## Secrets

Terraform creates the SSM parameters but never their values — a secret in a `.tf`
file or in state is a secret in git. Set them once by hand:

```bash
aws ssm put-parameter --name /atom/telegram/bot_token \
  --type SecureString --key-id alias/atom --overwrite --value '<from BotFather>'

aws ssm put-parameter --name /atom/telegram/webhook_secret \
  --type SecureString --key-id alias/atom --overwrite --value "$(openssl rand -hex 32)"

aws ssm put-parameter --name /atom/telegram/allowed_user_ids \
  --type SecureString --key-id alias/atom --overwrite --value '123456789'
```

Then register the webhook, using the `control_lambda_function_url` output:

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=<function_url>" \
  -d "secret_token=<webhook_secret>"
```

Broker credentials go under `/atom/brokers/{broker}/{account}/…`, and daily
tokens under `/atom/sessions/…` — created and **destroyed** each run by the
engine (D-170). See `docs/09-security/SECRETS-MANAGEMENT.md`.

## Cost

| | Monthly |
|---|---|
| 1 × Elastic IPv4, billed 24×7 | $3.65 |
| EBS gp3 8 GB | $0.64 |
| t3a.small, ~12 h | ~$0.23 |
| KMS customer-managed key | $1.00 |
| S3 + Glacier Deep Archive | < $0.50 |
| Lambda, SSM, CloudWatch | ~$0 |
| **≈** | **$6.00** |

At two investors it is ~$9.70. **The IP addresses dominate**, and they bill
whether or not anything runs — which is why splitting investors across instances
can never save money, and why one small instance with several addresses is the
cheapest correct design.

Figures are `us-east-1`-derived; confirm `ap-south-1` before relying on them.

## What is deliberately absent

NAT gateway (~$32/mo, and the design needs a *public* static source address) ·
load balancer · Auto Scaling · RDS · ECS/EKS · Secrets Manager ($0.40/secret/mo
for rotation ATOM does not use) · VPC endpoints · CloudWatch Logs as the primary
log sink. Each is a default an experienced reviewer would reach for, and each
would cost more than the entire current bill while solving a problem this system
does not have.

## Layout

| File | Contains |
|---|---|
| `versions.tf` | Providers, and the remote-state block to enable |
| `variables.tf` | Inputs, with the reasoning for each default |
| `network.tf` | VPC, subnet, route table, security group (**no port 22**) |
| `eip.tf` | 🔴 Elastic IPs and their guards |
| `iam.tf` | Instance and Lambda roles, with explicit denies |
| `kms_s3.tf` | CMK, rolling log bucket, Object-Locked archive bucket |
| `ec2.tf` | The instance, IMDSv2-only, encrypted root |
| `user_data.sh.tftpl` | Host bootstrap: runtime, nginx proxies, idle timer |
| `lambda.tf` | Control plane, Function URL, SSM parameter shells |
| `outputs.tf` | Addresses, allocation IDs, webhook URL |
