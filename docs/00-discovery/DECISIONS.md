# ATOM — Decision Log

**Status:** Live — appended as decisions are confirmed
**Companion to:** [`OPEN-QUESTIONS.md`](./OPEN-QUESTIONS.md) · [`REQUIREMENTS-AS-CAPTURED.md`](./REQUIREMENTS-AS-CAPTURED.md)

Every entry is a confirmed instruction. Design documents may rely on these; anything not
here and not in the requirements capture remains an open question.

---

## Round 1 — 2026-09-16

| ID | Decision |
|---|---|
| D-001 | All five brokers (Upstox, Dhan, Zerodha, Groww, Shoonya) fully built and tested in v1 |
| D-002 | Deviation uses live LTP against a mean of daily closes; LTP snapshotted per run |
| D-003 | GTT/GTC resting sell orders where supported, DAY re-placement as fallback |
| D-004 | Self and family accounts only; no external-client compliance surface |

---

## Round 2 — 2026-09-16

### Infrastructure and networking

**D-005 — Per-account egress via local forward proxy (Q-010).**
One local forward proxy per static IP on the EC2 instance; the broker adapter receives a
proxy URL from config and stays IP-agnostic. Treated as the **starting approach, to be
validated empirically** — "try and see what will work". Policy routing remains the
documented fallback if the proxy approach underperforms.

**D-006 — All static IPs must be IPv4.** No IPv6. Brokers whitelist IPv4 addresses.

**D-007 — One IP per investor, shared across all that investor's brokers (Q-011).**
Person A's single IPv4 is registered with every broker Person A holds an account with;
Person B gets a second IPv4 used for all of their brokers. **The operator configures these
IPs into each broker's portal manually** after the infrastructure is provisioned — IP
registration is not automated by ATOM.

**D-008 — Minimise instance size (Q-012).** Choose the **smallest EC2 instance type that
supports two IPv4 addresses**, provision two Elastic IPs, attach both, and reference them
explicitly in application config. Cost control is the governing constraint.

**D-009 — Containers only if they are cheaper.** Per-account network namespaces are
acceptable in principle, but there is an explicit concern that containers on a micro/small
instance will be slow or overloaded. In-instance networking is preferred unless the cost
analysis shows otherwise.

**D-010 — Rejected: one EC2 per account.** Too costly.

**D-011 — Cost analysis is a required deliverable.** Model a **30-minute run, 5 days a
week**, and produce a table recommending the best topology **for N static IPs**. The
question to answer explicitly: is 2 × small instances carrying 2 IPs each cheaper than
1 × large instance carrying 4 IPs? Output a per-N recommendation, not a single answer.
→ `docs/02-infrastructure/INSTANCE-SIZING-AND-COST.md`

### Authentication and secrets

**D-012 — Per-broker authentication strategies (Q-022).** Each broker is implemented
according to what that broker actually offers: OAuth redirect link where there is one,
paste-in token where the broker issues one from a settings page, credential-submission flow
where that is the mechanism. No forced uniformity.

**D-013 — Token storage (Q-023).** Encrypted at rest, auto-expired, never logged.
**AWS Secrets Manager preferred subject to cost**; whichever of Secrets Manager or
encrypted-in-Supabase is cheaper wins. An additional idea to evaluate: after a run
completes, generate a fresh token and discard it — the act of generating a new token
invalidates the previous one, so no usable token is left at rest at all.

**D-014 — Telegram authorisation (Q-031).** Only specific allow-listed Telegram user IDs
may bring the EC2 instance **up or down**. All other senders are ignored.

### Universe and market data

**D-015 — ETF classification is automated, with rules plus an LLM classifier (Q-040).**
Combine rule/keyword matching with an LLM classifier. **Debt and liquid ETFs must be
excluded.** The classifier uses **free NVIDIA-hosted model APIs**
(https://build.nvidia.com/models), implemented as a **try/except cascade across five
different models** so that one model being unavailable never blocks classification.

**D-016 — Volume metric is the mean (Q-042).** Compute the **average volume** over the
window and build the buying universe from it. **The window length in days is configurable**,
not fixed at 25/60.

**D-017 — Market data is source-agnostic and shared (Q-044, Q-024).** Data is pulled from
**whichever account has a working data API**, and the computed result is consumed by **all**
accounts. Worked example given: Person A holds Dhan with data access → pull from Dhan;
Person B holds Upstox → pull from Upstox. Critically: **an account may be able to place
orders without having data access** — the stated case is a Zerodha account with **no data
API subscription**, where data comes from Upstox and orders are placed on Zerodha.
Data is pulled **once a day** and reused. Where different sources disagree, **take the mean
across sources**.
*Design consequence: the data layer and the trading layer are fully decoupled, and each
broker account carries independent `can_trade` and `can_supply_data` capability flags.*

### Website and hosting

**D-018 — Domain auto-switching between Render and EC2 (Q-066, Q-067).**
One domain. When the engine is down it resolves to the **Render-hosted static site**. When
the operator brings the instance up via Telegram, the same domain **points to the site served
by the EC2 instance**, which carries the login page and all functionality. On shutdown it
falls back to Render. **The two sites must look identical** — the only visible difference is
the login button. The switching mechanism itself needs design and is called out as an open
engineering problem.

### Tax-loss harvesting

**D-019 — Synthetic cost basis confirmed (Q-081).** The proxy inherits the original
₹10,000 basis and must climb ~15% from ₹9,000 to ₹10,350. Long holding periods are accepted.
ATOM's P&L differing from the broker's until close is accepted.

**D-020 — NEW SCREEN: ATOM vs Broker P&L contrast page.** Because of D-019, a dedicated
screen shows, per affected trade, what ATOM did, what ATOM's books say, and what the broker's
side shows. Trades are listed as **expandable dropdowns by date** — clicking e.g. the
13 September trade reveals that trade's full contrast.

**D-021 — Harvest proxy buys are funded from buffer cash, not sale proceeds (Q-085).**
T+1 settlement is acknowledged; the working assumption is that spare funds are available, so
the proxy purchase uses buffer funds rather than waiting for the sale to settle.

**D-022 — NEW: pending execution queue.** A harvest that cannot execute immediately is
**not** shown as "executable tomorrow". It is written to an **execution list**, and the next
run **picks it up and executes it**. This is a general mechanism: deferred work is queued and
drained by subsequent runs.

### Orders

**D-023 — Unfilled orders are left resting (Q-090).** No cancel-before-shutdown step; the
broker expires day orders at end of day.
> ⚠️ **Flagged for confirmation:** this is true for DAY orders, but **GTT orders deliberately
> survive** — up to one year on Groww, until expiry elsewhere (D-003). So unfilled *buy* DAY
> orders expiring is fine, while *sell* GTTs persisting is the intended behaviour. A separate
> case still needs handling: a buy that **fills late in the day while the engine is down**
> has no sell order until someone places one, so start-of-run reconciliation is still
> required. See Q-137.

### Charges and reporting

**D-024 — Charges are shown as a contrast view (Q-100).** Both figures are presented side by
side: **what ATOM computed locally** from the fee schedule, and **what the broker reports**.
The explicit purpose is to expose hidden or unexpected charges levied by the broker.

### Logging and archival

**D-025 — Four log destinations (Q-110).**

| Destination | Retention |
|---|---|
| EC2 local storage | Rolling 30 days, cleared on a rolling basis |
| S3 (standard) | Rolling 30 days |
| S3 Glacier Deep Archive | Permanent deep archive |
| Google Drive | Permanent archive |

So **two S3 buckets/paths**: a 30-day rolling one and a deep archive.
> ⚠️ **Flagged for confirmation:** the instruction included "we need not push the logs data
> to [Supabase]". Read as: **raw log files** do not go into Supabase. Structured trade,
> decision and order records still must, since the brief requires full DB traceability of
> why every trade happened. See Q-138.

---

## Open items carried forward from this round

| ID | Item |
|---|---|
| ~~Q-051~~ | ✅ Resolved by D-026 — percentage, 4dp internal / 2dp display |
| ~~Q-043~~ | ✅ Resolved by D-027 — NSE ETF table Volume column, i.e. traded quantity |
| ~~Q-137~~ | ✅ Resolved by D-029 — sell placed next working day; start-of-run reconciliation confirmed |
| ~~Q-138~~ | ✅ Resolved by D-030/D-031 — structured rows in Supabase with 90-day purge; detailed files to Telegram |
| Q-139 | Cost of Secrets Manager vs encrypted Supabase storage, to settle D-013 |
| Q-140 | Feasibility and reliability of the domain auto-switch mechanism (D-018) |

---

## Round 3 — 2026-09-17

### Strategy precision

**D-026 — Deviation is ALWAYS expressed in percentage terms, never absolute rupees (Q-051).**
Resolves the contradiction flagged as C-1/C-2 in the requirements capture.

| Context | Precision |
|---|---|
| All internal calculation, storage and ranking | **4 decimal places** |
| All UI display | **2 decimal places** |

*Design consequences:* deviation columns are `NUMERIC(_,4)`; rounding to 2dp happens in the
presentation layer only, never in the database or the ranking comparison. Two ETFs whose
deviations differ only in the 3rd or 4th decimal place still rank deterministically. Rounding
for display must never feed back into a decision.

**D-027 — Volume threshold is traded quantity, per NSE's own ETF table (Q-043).**
The authority is the **Volume column** of
<https://www.nseindia.com/market-data/exchange-traded-funds-etf> — i.e. **units/shares
traded**, not rupee turnover. The 1,00,000 default therefore means **100,000 units**.

> ⚠️ **Verification pending.** `nseindia.com` is blocked by this environment's egress proxy,
> so the column semantics could not be confirmed first-hand. The NSE ETF table is understood
> to carry both a `Volume` column (shares) and a separate `Value` column (₹ lakhs); this
> decision selects the former. Confirm before implementing. See Q-145.

> **Practical note for the weekly job.** That NSE page shows a *single day's* snapshot. It
> defines the metric but cannot supply the 25/60-day history the universe job needs, so
> historical daily volume comes from the broker data API (D-017) using the same definition —
> traded quantity, averaged over the configurable window (D-016).

### Infrastructure

**D-028 — IPv4-per-instance limits are real and already modelled (Q-012).**
Confirmed: EC2 caps IPv4 addresses per instance at `max ENIs × max private IPv4 per ENI`.
The cost analysis was built on those caps, not on an assumption of unlimited IPs —
t3.nano/micro cap at 4, t3.small at 12, t3.medium at 18, t3.large at 36. The recommendation
of a single t3.small already respects them and leaves room for 12 investors.
Rows above t3.micro remain `❓ UNVERIFIED` pending `describe-instance-types` against a real
AWS account (Q-142); if they come back lower than modelled, the topology table must be
recomputed, since capacity — not cost — is what would force a second instance.

### Orders

**D-029 — Deferred sell placement is acceptable (Q-137, resolved).**
- When a **GTT sell completes**, the next buy order for that security is placed on the
  **next working day** — not intraday.
- Where a broker does **not** support GTT and a buy **fills late in the day** after the
  engine is down, its sell order is placed on the **next working day**.

*Design consequence:* start-of-run reconciliation is confirmed as a required step. Every run
begins by finding fills that occurred while the engine was down and placing the sell orders
they are missing. No intraday re-wake is needed.

### Logging

**D-030 — Structured logs in Supabase with a 90-day purge (Q-138, resolved).**
Log data **is** written to a structured table in Supabase, subject to a **90-day purge
policy**. This supersedes the earlier reading that Supabase was excluded.

**D-031 — Detailed logs are files, delivered to Telegram.**
The verbose run log is a **`.log` or `.txt` file** pushed to the Telegram group, one per
account per broker (§13 of the requirements capture), alongside the archival destinations
in D-025.

*Resulting split:*

| Layer | Content | Store | Retention |
|---|---|---|---|
| Structured | Queryable run/decision/order rows | Supabase | **90 days, purged** |
| Detailed | Full human-readable run narrative | `.log`/`.txt` → Telegram, S3, S3 Deep Archive, Google Drive, EC2 local | Telegram + Drive + Deep Archive permanent; S3 standard and EC2 local 30 days rolling |

> ⚠️ **Tension to resolve (Q-146).** The original brief requires that an operator can query
> the database to reconstruct *why* any trade was made. A 90-day purge means that
> capability expires after 90 days, while the reports module needs month-on-month
> financials over years. Proposal: **exempt the trade, order, position and harvest tables
> from the purge** — purge only the high-volume diagnostic log rows. Confirm.

### Round 3 addendum — NSE ETF table, confirmed from source (screenshot, 17-Sep-2026 16:00 IST)

**D-027 is now VERIFIED, and the same source resolves more than the volume question.**

Observed column set:

`SYMBOL · CATEGORY · SUB-CATEGORY · OPEN · HIGH · LOW · PREV. CLOSE · LTP ·
INDICATIVE CLOSE · CHANGE · % CHANGE · VOLUME · VALUE (₹ Crores) · i-NAV · NAV ·
52 WEEK HIGH · 52 WEEK LOW`

**D-027 confirmed — VOLUME is units traded.** `VOLUME` and `VALUE (₹ Crores)` are separate
columns, and the arithmetic ties out exactly:

| Symbol | Volume | LTP | Volume × LTP | VALUE shown |
|---|---|---|---|---|
| LIQUIDCASE | 2,57,71,011 | 115.96 | ₹298.8 cr | **298.81** ✅ |
| NIFTYBEES | 47,32,947 | 266.36 | ₹126.0 cr | **125.85** ✅ |

So the 1,00,000 threshold means **100,000 units**, as decided. Q-145 closed.

---

**D-032 — NSE already publishes the category. The LLM classifier is demoted to a fallback.**

The table carries native `CATEGORY` and `SUB-CATEGORY` columns, and the observed values map
directly onto the three required buckets plus the required exclusion:

| NSE CATEGORY | Observed SUB-CATEGORY | ATOM bucket |
|---|---|---|
| `EQUITY` | Nifty 50, … | **Equity** |
| `COMMODITY` | GOLD, SILVER | **Metals** |
| `GLOBAL` | GLOBAL INDICES | **Global** |
| `DEBT` | Overnight ETFs and Liquid ETF | **EXCLUDED** |

This satisfies D-015's hard requirement — "debt and liquid ETFs must be excluded" — directly
from exchange data, with no inference. Observed examples: LIQUIDCASE, LIQUIDBEES and LIQUID1
are all `DEBT`, and would be excluded automatically.

**Revised classification pipeline (supersedes D-015's ordering):**

1. **NSE `CATEGORY`/`SUB-CATEGORY` is the authority** where present.
2. **Keyword rules** as a cross-check; a disagreement with NSE raises a review flag rather
   than silently overriding.
3. **LLM classifier** (free NVIDIA-hosted models, five-model try/except cascade per D-015)
   only for instruments NSE has not classified — typically a newly listed ETF — and for
   sub-categorising sectoral ETFs for harvest proxy matching, which NSE does not provide at
   the granularity correlation work needs.
4. **Operator confirmation** remains the final authority for anything auto-assigned.

*This materially reduces both cost and risk:* classification of the standing universe stops
depending on an external LLM being available, and the LLM is confined to the genuinely
ambiguous margin.

**D-033 — Universe snapshot is downloadable.** The page exposes a **download control** and a
**Category filter**, so the full table can be pulled as a file rather than scraped row by
row. The weekly job (D-016) should prefer this, with the broker data API supplying the
25/60-day history the single-day snapshot cannot.

> **Scale check:** the page reported Advances 232 / Declines 105 / Unchanged 13 — about
> **350 listed ETFs**. That is the size of the raw universe before the volume filter, and it
> sets the sizing for the data pipeline and the daily quote budget.

---

**OPPORTUNITY — NAV and i-NAV are published (not yet a decision, needs your call).**

The table carries `NAV` and `i-NAV` (indicative NAV) alongside `LTP`. The gap between LTP and
i-NAV is an ETF's **premium/discount to fair value**, and it is a different signal from
deviation-from-own-mean:

- An ETF trading *below* its own mean may simply be tracking a falling underlying — the
  strategy's intent.
- An ETF trading *below its i-NAV* is cheap **relative to the assets it holds right now** —
  a genuine mispricing, and often a liquidity artefact.

Observed on 17-Sep: SILVERBEES LTP 216.69 vs i-NAV 297.13, and GOLDBEES 124.41 vs 283.07 —
gaps far too large to be real premiums, which suggests the i-NAV column is on a different
basis (per-unit vs per-gram, or a stale feed) and **must be validated before any use**.

Two candidate uses, both deferred pending your decision (Q-147):
1. A **guard rail**: refuse to buy an ETF trading at a large premium to i-NAV, however
   oversold it looks against its own mean.
2. A **second ranking input** alongside mean deviation.

---

## Open items after round 3

| ID | Item |
|---|---|
| Q-139 | Cost of Secrets Manager vs encrypted Supabase storage, to settle D-013 |
| Q-140 | Feasibility and reliability of the domain auto-switch mechanism (D-018) |
| Q-141 | Confirm ap-south-1 on-demand pricing (egress-blocked here) |
| Q-142 | Confirm ENI/IPv4 limits for t3.small and above via `describe-instance-types` |
| Q-143 | Confirm free-tier status (750 free IPv4 hours/month) |
| Q-144 | EBS root volume size, given 30 days of local log retention |
| ~~Q-145~~ | ✅ Resolved — VOLUME is units; Volume × LTP reconciles to the VALUE (₹ cr) column |
| Q-146 | Exempt trade/order/position/harvest tables from the 90-day purge? |
| Q-147 | Use NAV / i-NAV premium-discount as a buy guard rail or ranking input? Validate the feed first |
| Q-148 | Full list of NSE ETF CATEGORY values — only EQUITY, COMMODITY, GLOBAL and DEBT observed so far |
