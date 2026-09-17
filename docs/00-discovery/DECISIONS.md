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
| ~~Q-147~~ | ✅ Resolved by D-034b — implemented as a configurable veto gate |
| ~~Q-148~~ | ✅ Resolved by D-036 — five values, verified across all 350 rows |

---

## Round 4 — 2026-09-17

Driven by the operator-supplied NSE snapshot of all 350 ETFs
(`docs/99-vendor-docs/nse/MW-ETF-17-Sep-2026.csv`). Full specification in
[`../04-strategy/NAV-PREMIUM-CHECK.md`](../04-strategy/NAV-PREMIUM-CHECK.md).

**D-034a — The "Metals" bucket is renamed "COMMODITY".** Canonical buckets are
**EQUITY · COMMODITY · GLOBAL**, matching NSE's vocabulary. All documents, schema columns,
config keys and UI labels use these names.

**D-034b — NAV premium check.** A veto gate applied after ranking, before ordering:
- Master toggle `nav_check_enabled` per account (default ON).
- `nav_premium_tolerance_pct` per account × category (default 2.00% equity and commodity).
- Price **at or below NAV always passes** — no lower bound. The tolerance caps only how far
  above NAV a buy may go.
- Buy/sell ranking logic is unchanged; this is purely an additional gate.
- Tolerances are editable before any run.

**D-035 — Per-candidate decision logging.** Every evaluated candidate logs each gate's
**inputs and verdict** separately, in evaluation order, stopping at the first failure and
naming the gate and threshold breached — explicitly so that "deviation passed but NAV failed"
is visible. Applies to buys, sells, averaging and harvest. Format and structured columns in
the spec.

**D-036 — NSE category strings must be normalised, not matched literally.**
Verified across all 350 rows: `EQUITY` (260), `COMMODITY` (45), `DEBT` (38),
**`GLOBAL INDICES`** (6 — *not* `GLOBAL`), **`Hybrid`** (1, title-case, sub-category
Equity/Debt). DEBT and Hybrid are excluded.

### ⚠️ Finding that needs an operator decision (Q-149)

**The NAV check, as specified, switches the entire GLOBAL category off.** All five liquid
global ETFs trade at premiums of **+18.9% to +183.1%** to NAV — MONQ50 at +183% is ₹330 for
₹117 of assets. The only global ETF near a normal premium (HNGSNGBEES, +2.83%) fails the
volume filter.

This is structural, not a data error: SEBI's cap on overseas investment has frozen unit
creation in these schemes, so AP arbitrage cannot close the gap. It also means price-based
mean reversion offers no protection in this bucket — a premium collapse is a far larger move
than any price-history model would predict.

Five options are laid out in the spec; the recommendation is to **keep the 2% tolerance now**
(global dormant) and treat global as a separate design question, possibly ranking it on
premium-to-NAV rather than price deviation.

Impact on the other buckets is negligible and correctly calibrated: commodity never binds
(0 of 44 above NAV, median −0.64%), equity blocks 4 of 91 liquid candidates at 2%
(median +0.74%).
| ~~Q-149~~ | ✅ Resolved by D-052 — no special-casing; the tolerance is config, and 0% is legitimate |
| Q-150 | Behaviour when NAV is unavailable (18 of 350 lack i-NAV, 3 lack NAV/LTP) |
| Q-151 | Use NAV (EOD) or i-NAV (intraday) for the live check |
| Q-152 | Confirm `Hybrid` is excluded |

**D-037 — Configuration scope is (trading account × category), where a trading account is
one investor's account at one broker.** No operational number is hard-coded anywhere. The
operator's instruction — "for each account, each broker and each category we should be able
to change these numbers" — resolves to this key, because investor and broker always travel
together and that pair is already the unit holding tokens, funds, holdings and orders.
Person A with Upstox and Dhan therefore has two independently configurable trading accounts;
with three categories that is 9 config rows across the current three-account setup.

Values resolve most-specific-first through six levels, and each run records which level
supplied each value. Config is versioned, snapshotted per run, frozen at run start, printed
into the run log, and validated at write time. Full registry of every configurable value in
[`../01-architecture/CONFIGURATION-MODEL.md`](../01-architecture/CONFIGURATION-MODEL.md).

*Supersedes the narrower account × category scope proposed in Q-060.*
| Q-153 | Confirm config resolution order |
| Q-154 | Is one `category_priority` per trading account enough? |
| Q-155 | May a VIEWER edit config, or ADMIN only? |

---

## Round 5 — 2026-09-17

**D-038 — No defaults anywhere; config completeness is a pre-flight gate.** Supersedes the
six-level resolution order in D-037. There is no inheritance and no fallback. Every required
key must be explicitly set for every (trading_account, category). Before any run — live or
dry — the engine enumerates the required set, and **blocks the run** if anything is absent,
naming exactly what is missing and where. The same check drives a live validity indicator on
the Execute Engine screen. Suggested values survive only as **UI pre-fills the operator must
actively accept**; the engine never applies them.

**D-039 — NULL is an explicit operator choice, distinct from absent.** NULL means "do not
trade this" and skips the category, logged as a deliberate choice. Absent means "unknown" and
blocks the run. Storage must distinguish the two: the config row's **existence** means
configured, and its **value** may be NULL.

**D-040 — Single admin login. No other roles.** The application is admin-only. The people
whose accounts are traded have **no access**. One login to the website, one role, which can
change configs, run the process, update tokens and everything else.
*Supersedes* the earlier "two to three users" statement in the requirements capture (§11) and
closes Q-072 and Q-155 — there is no VIEWER role to design.

**D-041 — End-to-end dry-run infrastructure is a first-class subsystem.** Per trading account,
`execution_mode ∈ {LIVE, DRY}`. Real market data, real configs, identical strategy code;
the only difference is that orders go to a paper fill engine instead of a broker. Paper money
is added explicitly and behaves as real cash, including blocking buys when short. Portfolio
snapshots at start and end of day — no intraday polling. A dedicated Dry Run screen carries
the paper portfolio, equity curve and performance. Every dry-run artefact is marked `DRY`.
Full specification in
[`../01-architecture/EXECUTION-MODES-AND-DRY-RUN.md`](../01-architecture/EXECUTION-MODES-AND-DRY-RUN.md).

*This is the architectural justification for the modularity mandate, and it reorders the
build plan: the paper gateway can be implemented first, letting the whole strategy engine be
validated against live market data before any broker order adapter, static IP or SEBI IP
registration exists.*

| Q-156 | NULL semantics per key |
| Q-157 | Adding a new config key — block all accounts or allow a grace mode? |
| Q-158 | Confirm the paper fill model |
| Q-159 | Compare dry-run and live P&L side by side? |
| Q-160 | Paper portfolio retention |
| Q-161 | Can a dry run start without the EC2 engine? |

---

## Round 6 — 2026-09-17

**D-042 — Do not pre-check funds locally; let the broker reject the order.**
*Supersedes the local funds check in the requirements capture §6.3.*
The engine places every order the rules call for, in the fixed category priority order. If
funds are short, **the broker rejects it and the broker's own reason is logged verbatim** —
authoritative, and better than inferring it from a funds API that may be stale or
differently defined.
- **Category priority is fixed** per trading account (Q-154 closed).
- Orders are never downsized. A failure is a failure.
- **The UI offers a manual retry** per failed order, so the operator can add money to the
  broker account after a run and retry without re-running the whole engine.
- Rejection reasons are surfaced on Daily Status and in the run log (D-035).

**D-043 — Dry-run price source is selectable: `BROKER` or `FREE`.**
Broker data requires a validated token and carries the broker's IP policy; a free source
(e.g. Yahoo Finance) needs neither but has **incomplete ETF coverage**. Both are offered.
Because missing prices silently change the ranking, a `FREE` run must report coverage
explicitly and is classed as a plumbing test rather than a strategy validation.
*This corrects an earlier claim that dry runs never need a static IP.*

**D-044 — Dry run includes full Indian charges.** Brokerage, DP charges, STT, GST, exchange
and SEBI fees and stamp duty are computed and deducted from paper cash, so dry-run output is
comparable to live rather than a naive price difference.

**D-045 — NEW SUBSYSTEM: Cost of capital.** Funds deployed are **borrowed**, at a per-annum
rate, so true profit is `Realised P&L − Charges − Cost of capital for days held`. Interest
accrues **per lot, daily, on all seven calendar days**, from buy date to sell date for closed
lots and to today for open ones. Averaging raises the accrual base from the averaging date,
which falls out of per-lot accrual automatically. Partial sells close lots FIFO, freezing
each closed lot's interest. A dedicated screen shows, for a chosen period: closed trades with
P&L and true profit, open holdings with accrued interest **but no P&L**, and a period summary.
**Taxation is explicitly excluded from this calculation**, per instruction.
Full specification in [`../08-reporting/COST-OF-CAPITAL.md`](../08-reporting/COST-OF-CAPITAL.md).

*This makes lot-level position tracking mandatory — position-level tracking cannot represent
the averaging case correctly.*

| ~~Q-054~~ | ✅ Resolved by D-042 — never downsize; place the order and let it fail |
| ~~Q-154~~ | ✅ Resolved by D-042 — one fixed ordering per trading account |
| Q-162 | 🔴 Does idle borrowed cash accrue interest, or only deployed lots? |
| Q-163 | Simple or compound interest |
| Q-164 | Day-count convention (Actual/365 proposed) |
| Q-165 | Is the borrowing rate per investor, per trading account, or global? |
| Q-166 | Can the rate change over time (dated rate series)? |
| Q-167 | Accrual base: original cost or current value? |
| Q-168 | Does the sell day count toward days held? |
| Q-169 | Are charges included in the accrual base? |
| Q-170 | Which free price provider, and should unmapped symbols block a FREE run? |

**D-046 — Cost of capital accrues in two buckets: deployed and idle.** (Q-162 resolved.)
Every rupee in an account is borrowed and accrues from arrival until repayment, sitting in
exactly one bucket per day:
- **Deployed** — open lots at cost, accrued **per lot** and attributed to trades.
- **Idle** — the account cash balance, accrued and reported as **unattributed idle capital
  drag**.

A **withdrawal is a repayment** and stops interest on that amount from that day; a deposit is
additional borrowing. A buy moves capital idle→deployed and a sell moves it back, with total
interest continuous across the move. The resulting invariant —
`per-lot accrual + idle accrual == total borrowed × r / 365` — is the primary test for the
subsystem.

The period summary gains an **idle capital drag** line and a **capital efficiency** measure
(share of days capital was deployed rather than idle), which quantifies the cost of the
depth/skip rules deliberately producing no-buy days.

*Consequence: a complete per-account cash ledger becomes a hard requirement. Daily balances
are **reconstructed** from deposits, withdrawals, buys, sells and charges rather than
snapshotted daily — the engine is off most days — and reconciled against broker-reported
balances whenever it does run, with any drift surfaced as an unknown cash movement rather
than silently absorbed.*

| Q-171 | 🔴 Does retained profit accrue interest (actual balance) or only principal? |
| Q-172 | Do sale proceeds accrue as idle from trade date or settlement date? |
| Q-173 | How is each account's opening balance anchored for reconstruction? |

**D-047 — The accrual base is borrowed principal, not the account balance.** (Q-171 resolved.)
`principal = Σ CAPITAL_IN − Σ CAPITAL_OUT`. Retained profit does **not** accrue interest —
₹50,000 grown to ₹55,000 still costs interest on ₹50,000.

Cash movements are **typed by the operator** via a dedicated entry screen:
`PROFIT_WITHDRAWAL` leaves principal unchanged, while `CAPITAL_IN`/`CAPITAL_OUT` move it.
The distinction cannot be inferred — money leaving the account is either a repayment or a
profit take and only the operator knows which — so an unclassified withdrawal **blocks**
rather than defaulting (consistent with D-038).

**D-048 — Settlement interest is a third bucket.** A sale closes its lot's accrual and fixes
its True Profit, but the funds are not yet credited and the lender is still charging. That
gap accrues separately as **settlement interest**, attributed to neither the trade nor idle
cash:
- Base is the **lot's cost**, not the sale proceeds — the profit portion was never borrowed.
- `funds_credited_date` is **observed from the broker ledger**, never assumed from a
  settlement-cycle constant; the instruction is explicit that it varies by security, and
  assuming T+1 would understate the cost.
- Amounts stay in SETTLEMENT and keep accruing until the credit is observed, so an unusually
  long settlement appears as a rising cost rather than vanishing.

Principal therefore splits three ways — `DEPLOYED + SETTLEMENT + IDLE` — with the invariant
`Σ per-lot + settlement + idle == principal × r / 365`. Buys, sells and credits move capital
between buckets without changing the total; only `CAPITAL_IN`/`CAPITAL_OUT` change it.

*Consequences: `funds_credited_date` becomes a tracked field per sale, and the cash ledger
must be typed.*

| Q-174 | Pro-rata attribution when deployed lots exceed principal |
| Q-175 | How `funds_credited_date` is obtained per broker; FIFO matching if credits are not trade-attributed |
| Q-176 | Reject a PROFIT_WITHDRAWAL exceeding realised profit to date? |

**D-049 — Profit is never reinvested; the capital lifecycle is closed.** (Q-174 resolved.)
Capital is borrowed, deployed, sold, the profit is withdrawn, and the principal is repaid.
Consequently `deployed + settlement ≤ principal` always holds, and pro-rata attribution is
unnecessary.

> This is a **policy, not a mechanism** — the broker fills orders from whatever cash is
> present and cannot distinguish principal from profit. Realised profit left in the account
> will be deployed by the next run, silently breaking the assumption. **Required guard:** alert
> whenever `deployed + settlement > principal`, prompting the operator to record a
> `PROFIT_WITHDRAWAL` or reclassify the excess as `CAPITAL_IN`. Never absorbed silently.

**D-050 — `funds_credited_date` is always observed, never assumed.** (Q-175 confirmed.)
No T+1 constant anywhere. A Friday sale may credit on Monday — already beyond T+1 — and
holidays extend it further. Each broker adapter exposes the actual credit event and date, with
FIFO matching of credits to sales where the broker does not attribute credits to specific
trades. Added to the round 2 broker research scope.

**D-051 — Profit withdrawals are validated against realised profit.** (Q-176 resolved.)
An entry exceeding realised profit to date is **rejected** with a validation message; the
operator reduces it or reclassifies the excess as `CAPITAL_OUT`.

**D-052 — The NAV check is a pre-placement gate, and GLOBAL is not special-cased.**
(Q-149 closed.)

*Gate position:* ranking and selection happen first and are **never influenced by NAV**. The
check then applies to the already-chosen order: pass → send to the exchange, fail → **do not
push it**, log the reason, move to the next candidate in the existing rank order. A failing
candidate is skipped, not substituted by a better-priced one.

*No special handling for GLOBAL:* it uses the same `nav_premium_tolerance_pct` config at the
same (trading account × category) grain, with no default. The operator sets the number and the
engine enforces it exactly — 15% admits some global ETFs, 0% admits none, and **0% is a
legitimate configuration meaning "only buy at or below NAV"**, not a disabled category. An
empty candidate list is a valid outcome, logged as such rather than treated as an error.

The structural-premium analysis (all five liquid global ETFs at +18.9% to +183.1%) is retained
in the spec as context for choosing the number, not as behaviour baked into code.

**D-053 — The borrowing rate is per trading account.** (Q-165 resolved.)
Person A's cost of capital at Broker A may differ from Person A's at Broker B, and Person B's
at Broker C differs again. The rate therefore attaches to the **(investor, broker)** pair —
the same trading-account grain as every other config (D-037) — with no default (D-038).

*Consequence: the cost-of-capital calculation runs per trading account and rolls up to the
investor level for consolidated reporting, rather than applying one investor-wide rate.*
