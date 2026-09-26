# AWS Topology

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Costs and sizing:** [`INSTANCE-SIZING-AND-COST.md`](INSTANCE-SIZING-AND-COST.md) — not repeated here

> One region, one VPC, one small EC2 instance that runs **15–20 minutes a day**, two Elastic IPv4
> addresses that bill 24×7 whether or not anything is running, and a Lambda that starts the
> instance when the operator asks.

---

## 1. The shape

```
                            ┌──────────────────────────────┐
                            │        Telegram (bot)        │
                            └───────────────┬──────────────┘
                                            │ webhook
                                            ▼
                            ┌──────────────────────────────┐
              ┌─────────────│  Lambda  atom-control        │
              │             │  start · stop · status       │
              │             └───────────────┬──────────────┘
              │                             │ ec2:StartInstances
              │                             ▼
  ┌───────────┴──────────────────────────────────────────────────────┐
  │  VPC 10.0.0.0/16                                                 │
  │  ┌────────────────────────────────────────────────────────────┐  │
  │  │  Public subnet 10.0.1.0/24  (single AZ)                    │  │
  │  │                                                            │  │
  │  │   ┌──────────────────────────────────────────────────┐     │  │
  │  │   │  EC2  t3a.small   "atom-engine"                  │     │  │
  │  │   │                                                  │     │  │
  │  │   │   eth0  ┌── 10.0.1.10  ← EIP-A  (investor A)     │     │  │
  │  │   │         └── 10.0.1.11  ← EIP-B  (investor B)     │     │  │
  │  │   │                                                  │     │  │
  │  │   │   nginx :3128 → binds 10.0.1.10  (proxy A)       │     │  │
  │  │   │   nginx :3129 → binds 10.0.1.11  (proxy B)       │     │  │
  │  │   │   engine (python)      console (:443 on EIP-A)   │     │  │
  │  │   └──────────────────────────────────────────────────┘     │  │
  │  └────────────────────────────────────────────────────────────┘  │
  │        Internet Gateway · no NAT gateway · no private subnet      │
  └──────────────────────────────────────────────────────────────────┘
              │                    │                    │
              ▼                    ▼                    ▼
      ┌──────────────┐    ┌────────────────┐   ┌─────────────────┐
      │ SSM Param    │    │ S3 · 2 paths   │   │ five brokers    │
      │ Store (tokens│    │ rolling + deep │   │ Supabase        │
      │  by path)    │    │ archive        │   │ Google Drive    │
      └──────────────┘    └────────────────┘   └─────────────────┘
```

**One AZ, no NAT gateway, no private subnet, no load balancer.** A NAT gateway alone would cost
~$32/month — four times the entire current bill — and buys nothing: the instance *must* egress from
a known static address, which is exactly what an Elastic IP on a public subnet gives.

---

## 2. Components

| Component | Choice | Why this and not the obvious alternative |
|---|---|---|
| Region | **one**, `ap-south-1` (Mumbai) preferred | Latency to Indian brokers; keeps data in India |
| Compute | **t3a.small**, on demand | `t3a` is ~10% cheaper than `t3` for identical specs. `small` for the 2 GiB, not the CPU |
| Subnet | **one public**, single AZ | The instance runs 20 min/day; multi-AZ protects against nothing |
| Egress | **Elastic IP per investor**, on secondary private IPs of one ENI | Splitting across instances never saves money — IPs bill 24×7 regardless |
| Inbound | **console on EIP-A:443** | D-078. Whitelisting governs *outbound* source IP; inbound web traffic is unaffected |
| Control plane | **Lambda** + Telegram webhook | No always-on server needed to start an on-demand one |
| Secrets | **SSM Parameter Store**, `SecureString` | Free at this volume; Secrets Manager is $0.40/secret/month for no gain here |
| Object storage | **S3**, two paths | 30-day rolling + Glacier Deep Archive |
| Database | **Supabase** (managed Postgres), outside AWS | Already chosen; RLS from day one |
| DNS | Route 53 hosted zone (~$0.50/mo) | For `metalcocapital.com` and the D-018 switch |

---

## 3. Networking

### 3.1 One ENI, two Elastic IPs

Both Elastic IPs attach to **secondary private IPs on `eth0` of a single instance**:

```
eth0
 ├─ 10.0.1.10 (primary)    ← EIP-A   investor A's broker egress + console inbound
 └─ 10.0.1.11 (secondary)  ← EIP-B   investor B's broker egress
```

A `t3a.small` supports 3 ENIs × 4 IPv4 = 12 addresses, so two is comfortable and there is room for
a third investor without changing instance type. `t3.nano` and `t3.micro` cap at **4** total, which
is still enough for two investors but leaves less headroom — the sizing document has the table.

### 3.2 🔴 Elastic IPs are allocated once and never released

This is the single most consequential operational rule in the infrastructure.

**Dhan locks a registered IP for 7 days** (D-173). An address that changes is not a restartable
error — it is up to a week during which that account cannot place orders, and there is no override.

| Rule | |
|---|---|
| Allocate EIPs **before** registering them with any broker | Registration is the irreversible step |
| Never release an EIP, even while the instance is stopped | Release returns it to the pool; you will not get it back |
| Record the allocation ID and the per-broker registration date in `trading_account` | Dhan's `GET /v2/ip/getIP` returns the earliest permitted change date |
| Tag both EIPs `atom:do-not-release = true` | And keep the account's EIP quota headroom |

A stopped instance keeps its EIP associations, so the daily start/stop cycle is safe. Terminating
the instance is not — see §5.

### 3.3 Security groups

**Outbound** — default allow-all is acceptable and deliberate: the broker endpoints are numerous,
documented by hostname rather than address, and change without notice. The meaningful egress control
is the *source* address, which the proxy binding enforces (see
[`STATIC-IP-AND-PROXY.md`](STATIC-IP-AND-PROXY.md)).

**Inbound** — minimal:

| Port | Source | Purpose |
|---|---|---|
| 443 | `0.0.0.0/0` | Console (TLS, admin login behind it) |
| 22 | **none** | SSH closed; access via **SSM Session Manager** only |

> Closing port 22 entirely removes the largest attack surface a small deployment has, and costs
> nothing — Session Manager gives a shell through the AWS API with IAM auth and CloudTrail logging,
> and needs no inbound rule and no key pair. There is no reason to keep 22 open.

Ports 3128/3129 (the proxies) bind to the instance's own interfaces and are **never** exposed. An
open forward proxy on the public internet would be an immediate abuse magnet.

---

## 4. IAM

Three roles, each minimal. The instance profile is the one that matters, because a compromise of
the engine inherits it.

### 4.1 EC2 instance profile — `atom-engine-role`

| Allow | Resource |
|---|---|
| `ssm:GetParameter`, `GetParameters` | `arn:aws:ssm:*:*:parameter/atom/*` only |
| `ssm:PutParameter`, `DeleteParameter` | `/atom/sessions/*` only — daily tokens |
| `s3:PutObject` | `arn:aws:s3:::atom-logs/*` |
| `s3:GetObject`, `ListBucket` | `atom-logs` (for the 30-day rolling reads) |
| `kms:Decrypt` | the SSM/S3 CMK |
| SSM Session Manager | the managed `AmazonSSMManagedInstanceCore` policy |

**Explicitly denied, not merely omitted:**

| Deny | Because |
|---|---|
| `ec2:*` | The engine must not be able to modify its own networking — including detaching or reassociating an Elastic IP, which §3.2 makes a week-long outage |
| `s3:DeleteObject` on `atom-logs` | Logs are append-only; deletion is lifecycle policy's job, not the engine's |
| `iam:*` | No privilege escalation path |

An explicit `Deny` on `ec2:*` is worth writing even though nothing grants it, because a future
convenience grant cannot silently override a deny.

### 4.2 Lambda role — `atom-control-role`

`ec2:StartInstances` · `StopInstances` · `DescribeInstances` — **scoped by resource tag**
`atom:managed = true`, so it cannot touch any other instance in the account. Plus
`route53:ChangeResourceRecordSets` on the one hosted zone if the D-018 DNS switch is used.

### 4.3 Human operator

Console access via IAM Identity Center with MFA. **No long-lived access keys** anywhere.

---

## 5. Lifecycle and state

The instance is **ephemeral compute over durable state**. What survives a stop, and what survives a
terminate, are different questions and the distinction matters.

| | Survives stop | Survives terminate |
|---|---|---|
| Elastic IP association | ✅ | ❌ — **the 7-day lock problem** |
| EBS root volume | ✅ | ❌ unless `DeleteOnTermination = false` |
| Local 30-day log cache | ✅ | ❌ (already in S3) |
| SSM parameters | ✅ | ✅ |
| Supabase data | ✅ | ✅ |
| S3 logs | ✅ | ✅ |

**Therefore: stop, never terminate.** The instance is stopped daily after the run and started on
demand. Terminating and rebuilding would mean re-associating Elastic IPs — safe if the EIPs were
never released, and a week-long outage on Dhan if they were.

Rebuild procedure, if ever needed, is in [`DEPLOYMENT.md`](DEPLOYMENT.md) §6 and begins with
"confirm both Elastic IP allocation IDs still exist".

### 5.1 Auto-shutdown

Idle timeout **60 minutes**, with a Telegram warning before it fires (D-055a). The engine itself
requests shutdown after a completed run; the timer is the backstop for a crashed or abandoned
session, because a forgotten instance costs compute but a forgotten *IP* costs nothing extra —
the IPs bill anyway.

---

## 6. What is deliberately absent

| Not used | Why |
|---|---|
| NAT gateway | ~$32/mo, and the design needs a *public* static source address |
| Load balancer / ALB | One instance, one operator; an ALB is ~$16/mo for nothing |
| Auto Scaling group | Scaling to zero is what the Lambda does, more cheaply |
| Multi-AZ, RDS, ElastiCache | Supabase is the database; there is no other state |
| ECS / EKS / Fargate | Container orchestration for one process on one host |
| Secrets Manager | $0.40/secret/month; SSM `SecureString` is free and sufficient |
| CloudWatch Logs as primary | Logs go to files → S3 → Drive (D-030/D-031). CloudWatch is used only for the Lambda |
| VPC endpoints | ~$7/mo each; the instance has a public route already |

Each of these is a default an experienced AWS reviewer would reach for, and each would cost more
than the entire current bill while solving a problem this system does not have.

---

## 7. Open items

| ID | Item |
|---|---|
| Q-140 | Feasibility and reliability of the D-018 domain auto-switch — see [`DEPLOYMENT.md`](DEPLOYMENT.md) §4 |
| — | Confirm IPv4-per-ENI limits for `t3a.small` with `describe-instance-types` before the second investor is added |
| — | Confirm `ap-south-1` pricing; the cost document was built on `us-east-1` figures |
