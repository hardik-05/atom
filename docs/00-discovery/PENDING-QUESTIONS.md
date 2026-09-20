# ATOM — Pending Items

**Status:** as of 2026-09-20 · **80 decisions recorded** (D-001 … D-080)
**Superseded:** the earlier 1–117 list is fully answered. This is what actually remains.

Pending work now falls into three kinds. Only **§1 needs answers from you**; §2 and §3 are
work I do, though §3 needs your AWS/broker accounts.

---

## 1. Open design questions — awaiting your answer (7)

| # | ID | Question | Recommendation |
|---|---|---|---|
| 1 | Q-184 | GTT cancel pass: cancel **only ATOM-recorded order IDs**, and report rather than cancel a resting sell ATOM has no record of? | Yes — a blanket cancel would destroy manually placed GTTs |
| 2 | Q-186 | Small-ratio splits (4:5 = −20%) sit exactly on the corp-action threshold and are indistinguishable from a sharp fall. Accept as a known blind spot? | Accept for v1; a corp-action feed is V2-4 |
| 3 | Q-187 | If an ETF is deactivated for a suspected corporate action but you **hold** it, should its sell order still be placed? | **Yes** — the holding is real and its average buy price comes from our own lot records, not the suspect price series. Only buying is blocked |
| 4 | Q-188 | Does the corp-action threshold check use adjusted or raw close? | Whatever the broker returns — that is the series the strategy consumes |
| 5 | Q-180 | Should a freeze carry an optional auto-release expiry date? | Yes, optional — a forgotten permanent freeze silently accrues cost of capital |
| 6 | Q-181 | If holdings fall below the excluded quantity (you sold manually), auto-reduce the exclusion or flag it? | Flag it — a silent auto-reduce hides a reconciliation gap |
| 7 | Q-182 | Should ATOM ever auto-create an exclusion for unidentified quantity, or always require explicit action? | Always explicit — auto-excluding would silently stop selling something |

---

## 2. Research and design tasks — mine to do, no answer needed

| # | Item | Notes |
|---|---|---|
| R1 | **Round 2 broker research, all five** | The largest remaining block. Per broker: auth flow, order API, **GTT place/cancel semantics and whether cancellation is synchronous (Q-185)**, holdings/positions shape, funds, ledger, **where and when DP charges surface (Q-178)**, **funds credit date exposure and whether credits are trade-attributable (Q-175)**, rate limits, error taxonomy, **static-IP whitelisting procedure**, and raw doc snapshots into `99-vendor-docs/` |
| R2 | **🔴 Broker T&C review (D-074c)** | Confirm each broker permits automated order placement. **Blocking — must complete before development** |
| R3 | **Domain auto-switch (D-055h)** | Build a raw test site for each of DNS switching, reverse proxy, and Render-side redirect; measure switch latency; adopt the fastest |
| R4 | **Database schema** | Now carries real requirements: lot-level tracking, typed cash ledger, settlement dates, config versioning, exclusions/freezes, universe snapshots, decision logs |
| R5 | **NSE ETF tick size (Q-179)** | Is ₹0.01 universal, or does it vary by price band? Affects sell-limit rounding |
| R6 | Remaining architecture docs | System overview, run lifecycle, module map |
| R7 | Screen specs and design system | 10 screens now, navy-blue theme, dark + light modes |
| R8 | Charges model and unified P&L | Per-broker fee schedules; computed-vs-reported contrast view |
| R9 | Logging spec, runbook, threat model, testing strategy | |
| R10 | Diagrams | System context, run sequence, buy/sell decision trees, harvest flow, ER, network topology |

---

## 3. Actions needing your accounts

| # | Item |
|---|---|
| A1 | Confirm ap-south-1 pricing in the AWS console (blocked by egress proxy here) |
| A2 | Run `aws ec2 describe-instance-types` to confirm ENI/IPv4 limits above t3.micro |
| A3 | Create the Supabase project (D-073a) — production and a separate dev project |
| A4 | Procure the two Elastic IPv4 addresses and register them with each broker (D-007) |
| A5 | Set the AWS billing alert at $15 (D-055f) |
| A6 | Confirm API subscriptions are active for all five brokers (D-056a) |

---

## Closed this round

Q-152 (Hybrid excluded) · Q-189 (settlement day counting) · Q-190 (console on an existing
Elastic IP) · Q-191 (SSM Parameter Store for secrets) · Q-183 (superseded by the D-064
corp-action threshold) · Q-177 (withdrawn — GTT reinstated)
