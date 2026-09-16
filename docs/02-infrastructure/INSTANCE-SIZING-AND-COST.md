# EC2 Sizing and Cost Analysis — Static IPs vs Instance Topology

**Status:** 🟢 Analysis complete · pricing verified for us-east-1, **ap-south-1 figures are estimates pending console confirmation**
**Date:** 2026-09-16
**Answers:** D-008, D-009, D-010, D-011 · Q-012, Q-135

---

## 1. The question asked

> "If two small instances which support 2+2 IPs are cheaper than a large EC2 which supports
> 4 IPs, we go with 2 EC2s. Do the cost analysis on number of IPs and the best option — one
> big or multiple small — and come up with a table on what is best for N IPs."

**Workload modelled:** a 30-minute run, 5 days a week. That is **~11 hours per month**
(21.7 trading days × 0.5 h), plus ~1 hour for the weekly universe job ≈ **12 hours/month**.

---

## 2. The finding, up front

**Splitting across multiple instances never saves money, at any N.** And the choice of
instance size is almost irrelevant to cost. Both follow from one fact:

> **A public IPv4 address is billed 24×7 at $0.005/hour whether or not the instance it is
> attached to is running** — $3.65/month per IP, permanently.
> ([AWS VPC pricing](https://aws.amazon.com/vpc/pricing/))

Because the engine runs only 12 hours a month, compute is a rounding error while the IPs
bill continuously. Splitting N IPs across two instances does not reduce the IP count — it is
the same N addresses at the same $3.65 each — and it **adds** a second EBS root volume,
which is itself billed 24×7 and costs more than the compute does.

**So: one instance, always. Size it for comfort, not for cost.**

### Cost structure at N = 2 IPs (us-east-1, monthly)

| Component | Cost | Share |
|---|---|---|
| 2 × public IPv4 @ $3.65 | **$7.30** | 89% |
| EBS gp3 root, 8 GB, billed 24×7 | $0.64 | 8% |
| t3.small compute, 12 h @ $0.0209 | $0.25 | 3% |
| **Total** | **$8.19** | |

Compute is **3%** of the bill. Moving from the cheapest instance to one four sizes larger
changes the total by under 5%.

---

## 3. Verified inputs

### 3.1 Instance pricing — us-east-1, Linux, on-demand ✅ verified

| Type | vCPU | RAM | $/hour | 12 h/month |
|---|---|---|---|---|
| t3.nano | 2 | 0.5 GiB | $0.0052 | $0.06 |
| t3.micro | 2 | 1.0 GiB | $0.0104 | $0.12 |
| t3.small | 2 | 2.0 GiB | $0.0209 | $0.25 |
| t3.medium | 2 | 4.0 GiB | $0.0418 | $0.50 |
| t3.large | 2 | 8.0 GiB | $0.0835 | $1.00 |

Source: [AWS EC2 T3 instances](https://aws.amazon.com/ec2/instance-types/t3/).
**t3a** variants are ~10% cheaper for the same specs and are worth using.

> ⚠️ **ap-south-1 (Mumbai) pricing could not be verified** — `docs.aws.amazon.com` and
> `instances.vantage.sh` are blocked by this environment's egress proxy. Mumbai typically
> runs **~7–12% above us-east-1** for T3. Treat every figure here as a lower bound and
> confirm in the console before committing. The *conclusions* are unaffected: a uniform
> regional uplift changes nothing about which topology wins.

### 3.2 Public IPv4 ✅ verified

- **$0.005/hour per address = $3.65/month**, charged identically whether in-use or idle.
- **Free tier: 750 hours/month of in-use public IPv4** — effectively one address free, for
  new accounts in the first 12 months.
  ([AWS announcement](https://aws.amazon.com/about-aws/whats-new/2024/02/aws-free-tier-750-hours-free-public-ipv4-addresses/))
- Effective 1 Feb 2024, still current.

### 3.3 IPv4 capacity per instance type

Total IPv4 capacity = **max ENIs × max private IPv4 per ENI**. Each private IPv4 can carry
one Elastic IP.

| Type | Max ENIs | IPv4/ENI | **Total IPv4** | Verification |
|---|---|---|---|---|
| t3.nano | 2 | 2 | **4** | ✅ [verified](https://overmind.tech/types/ec2-network-interface) |
| t3.micro | 2 | 2 | **4** | ✅ verified |
| t3.small | 3 | 4 | **12** | ❓ confirm |
| t3.medium | 3 | 6 | **18** | ❓ confirm |
| t3.large | 3 | 12 | **36** | ❓ confirm |

Confirm the unverified rows with one command before provisioning:

```bash
aws ec2 describe-instance-types --region ap-south-1 \
  --instance-types t3.nano t3.micro t3.small t3.medium t3.large \
  --query 'InstanceTypes[].{Type:InstanceType,ENIs:NetworkInfo.MaximumNetworkInterfaces,IPv4perENI:NetworkInfo.Ipv4AddressesPerInterface}' \
  --output table
```

**Note:** even **t3.nano supports 4 IPv4 addresses**. The two-IP requirement does not force a
larger instance at all — so D-008's "smallest instance that supports two IPs" resolves to
t3.nano on capacity grounds. See §5 for why that is still the wrong pick.

---

## 4. The table: best topology for N static IPs

All figures monthly, us-east-1, 12 h/month runtime, 8 GB gp3 root per instance.

| N IPs | Single-instance option | Single cost | Split option | Split cost | **Winner** | Margin |
|---|---|---|---|---|---|---|
| 1 | t3.small × 1 | **$4.54** | — | — | Single | — |
| 2 | t3.small × 1 | **$8.19** | 2 × t3.nano (1 IP each) | $8.70 | **Single** | $0.51 |
| 3 | t3.small × 1 | **$11.84** | 2 × t3.nano (2+1) | $12.35 | **Single** | $0.51 |
| 4 | t3.small × 1 | **$15.49** | 2 × t3.nano (2+2) | $16.00 | **Single** | $0.51 |
| 5 | t3.small × 1 | **$19.14** | 2 × t3.micro (3+2) | $19.71 | **Single** | $0.57 |
| 8 | t3.small × 1 | **$30.09** | 2 × t3.micro (4+4) | $30.66 | **Single** | $0.57 |
| 12 | t3.small × 1 (at capacity) | **$44.69** | 2 × t3.micro (6+6) | $45.26 | **Single** | $0.57 |
| 18 | t3.medium × 1 | **$66.84** | 2 × t3.small (9+9) | $67.03 | **Single** | $0.19 |
| 25 | t3.large × 1 | **$92.89** | 2 × t3.medium (13+12) | $92.53 | **Split** | $0.36 |

**Reading the table.** The single instance wins everywhere up to ~18 IPs, and where the split
finally edges ahead at N = 25 the margin is **$0.36/month** — noise, and not worth operating
two boxes, two deployments and two failure domains for.

**Why the margin is always ~$0.5:** it is the cost of the second EBS root volume ($0.64)
minus the compute saved by running two smaller instances. IP cost is identical on both sides
of every row, because N is N.

**The real constraint is capacity, not cost.** A second instance becomes necessary when N
exceeds the largest type's IPv4 capacity, or when you want per-account blast-radius
isolation — both engineering decisions, not economic ones.

---

## 5. Recommendation

**Run a single `t3.small` (or `t3a.small`) in ap-south-1, carrying one Elastic IPv4 per
investor.**

Rationale:

1. **t3.small, not t3.nano/micro, despite nano being sufficient on IP capacity.** The upgrade
   from nano to small costs **$0.19/month** at this duty cycle. For that you get 2 GB RAM
   instead of 0.5 GB — which matters, because the engine runs Python with pandas/numpy over
   several hundred ETFs' price history, *plus* one forward proxy process per account (D-005),
   *plus* serving the web console (D-018). This directly addresses the D-009 concern that
   "containers on a micro or tiny EC2 will be slow or overloaded" — that concern is correct,
   and the fix costs pennies.
2. **t3.small's 12-IPv4 capacity covers growth to 12 investors** with no instance change.
3. **Keep the on-demand start/stop model** — see §6, it is the single biggest saving.
4. **Do not split into multiple instances** until you exceed IPv4 capacity or want isolation.

### Estimated monthly bill, 2 investors, ap-south-1

| Item | USD | INR @ ₹88 |
|---|---|---|
| 2 × Elastic IPv4 | $7.30 | ₹642 |
| t3.small, 12 h | $0.28 | ₹25 |
| EBS gp3 8 GB | $0.70 | ₹62 |
| S3 (logs, 30-day + Deep Archive) | ~$0.30 | ₹26 |
| Lambda + EventBridge | ~$0.00 | ₹0 |
| **Total** | **~$8.58** | **~₹755** |

Comfortably inside the ₹2,000/month target in Q-135, with headroom for the Supabase and
Render tiers.

---

## 6. Two findings worth acting on

**a) Shutting the instance down saves ~65% of the bill — your instinct is right.**
Always-on t3.small: $15.26 compute + $7.30 IPs + $0.70 EBS = **$23.26/month**.
On-demand at 12 h: $0.25 + $7.30 + $0.70 = **$8.25/month**. Saving ≈ **$15/month (65%)**.
The start/stop architecture earns its complexity.

**b) But shutting down saves nothing on the IPs — and IPs are 89% of what remains.**
Elastic IPs bill 24×7 whether attached, unattached, or attached to a stopped instance. So:

- Never release an Elastic IP once it is registered with a broker. Re-registration is manual
  (D-007), and a released IP is gone for good — you cannot get the same address back.
- Idle IPs are **not** free. Every IP provisioned for a future investor costs $3.65/month
  from the day it is allocated. Allocate them at onboarding, not in advance.
- The one lever on IP cost is **the number of investors**, which is a business input, not an
  infrastructure choice.

---

## 7. Open items

| ID | Item |
|---|---|
| Q-141 | Confirm ap-south-1 on-demand pricing in the AWS console (egress-blocked here) |
| Q-142 | Confirm ENI/IPv4 limits for t3.small and above via `describe-instance-types` |
| Q-143 | Confirm whether the account is inside the 12-month free-tier window (750 free IPv4 hours/month ≈ one free IP) |
| Q-144 | Decide EBS root volume size — 8 GB assumed; D-025 requires 30 days of rolling local logs, which may need more |

> ⚠️ **Q-144 interacts with D-025.** Thirty days of local log retention on the instance means
> the root volume must be sized for it, and EBS bills 24×7. At 10 MB/run × 22 runs × 3 accounts
> that is trivial, but if logs are verbose the volume grows and so does the only
> always-on cost you control.

---

## Sources

- [Amazon VPC Pricing — public IPv4 charges](https://aws.amazon.com/vpc/pricing/)
- [AWS — 750 free public IPv4 hours in free tier](https://aws.amazon.com/about-aws/whats-new/2024/02/aws-free-tier-750-hours-free-public-ipv4-addresses/)
- [Amazon EC2 T3 instance types and pricing](https://aws.amazon.com/ec2/instance-types/t3/)
- [EC2 On-Demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/)
- [ENI limits per instance type](https://overmind.tech/types/ec2-network-interface)
