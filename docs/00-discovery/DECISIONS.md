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

---

## Round 7 — 2026-09-17 (answers to PENDING-QUESTIONS 1–55)

### Engagement
- **D-054a** Build order confirmed: **paper gateway + strategy engine first**, then brokers,
  console, harvesting, reports. No go-live date. Monorepo. `docs/` keeps its name. Mermaid
  **and** rendered PNGs. Audience is the **development team only** — so documents stay as
  detailed as possible.
- **D-054b** "ATOM" is a **pet name**, not a product or brand. No brand assets needed.
- **D-054c — Process rule:** review in batches, and **whenever a new feature is requested,
  revisit every connected component and raise as many questions as possible** before designing.

### Infrastructure
- **D-055a** Instance up **15–20 min/day**. Auto-shutdown at **60 min idle**, Telegram warning
  at **45 min**.
- **D-055b** Region `ap-south-1`, but **region must be config-driven** so a future move to
  another region is seamless. Fresh AWS account on **free tier**.
- **D-055c** Instance fully disposable; Docker image on ECR; order intent written to DB before
  sending.
- **D-055d — Secrets live encrypted in Supabase, NOT AWS Secrets Manager.** Chosen on cost:
  Supabase is already paid for, Secrets Manager is not. *(Supersedes the Q-073 recommendation.)*
- **D-055e** EBS root volume **1–3 GB, not 20 GB**. Logs record actions and decisions, not
  prices, and carry a 30-day purge; growth beyond 2–3 GB is not expected.
- **D-055f** Budget **$10–15/month**, with an **AWS billing alert at $15**.
- **D-055g** Scope the infra for **3 accounts, 2 onboarded now**. Revisit the whole hosting and
  engine design if more users are added.
- **D-055h — Domain auto-switch: build and measure, do not assume.** Construct a raw test site
  for **each** of the three options — DNS switching, reverse proxy, Render-side redirect —
  measure switch latency, and adopt the fastest. Design end-to-end once measured.

### Brokers
- **D-056a — API access exists for all five brokers.** The system must be runnable from day one
  the moment tokens are entered; the intent is to dry-run for a week or a month first, then go
  live.
- **D-056b** Shared rate limiter per broker per account. **Raw HTTP**, not vendor SDKs.
  **Delivery (CNC) always. NSE preferred over BSE.**
- **D-056c — Buy orders are LIMIT at a freshly fetched LTP.** After the candidate list is
  finalised, make an **LTP call immediately before placing each order**, then price the limit
  from that — not from the ranking snapshot.

### Telegram and run lifecycle
- **D-057a** Two chats: one for instance up/down and status, one for engine logs only.
- **D-057b — No boot polling.** The user sends `/start`, waits, and sends `/status` when they
  choose. If not ready, they check again. No automatic poll loop.
- **D-057c — The engine never self-starts.** Even the weekly universe job is operator-triggered
  from its screen. The universe job needs **no static IP**.
- **D-057d** NSE holiday awareness is **out of scope** — the operator knows the calendar.
- **D-057e — Runs per day are config-driven:** `allow_multiple_runs_per_day`. When off, a second
  Execute is refused; when on, it proceeds.
- **D-057f — Concurrency is queued, not parallel.** The operator may hit Execute for several
  accounts; the backend runs them **linearly** to avoid DB contention. The UI shows one status
  per account from exactly four states: **QUEUED · EXECUTING · COMPLETED · FAILED**, updated
  per stage. Deliberately lightweight — no detailed progress telemetry.
- **D-057g** Hard failures alert to **Telegram, the run log, and a local log on the instance**
  readable from the EC2 terminal.

### Market data and universe
- **D-058a — Retain 8 quarters (~2 years) of prices on a rolling window**; as new prices arrive,
  the earliest are deleted.
- **D-058b — No corporate-action adjustment.** Use the rate as given; ETFs are not expected to
  carry corp actions. *(Supersedes the Q-046 recommendation — see risk note below.)*
- **D-058c — Price refresh is part of the weekly job and runs only on demand.** Never automatic.
  Brokers often cap a single history call at ~30 days, so multiple paginated calls are needed;
  **~200 days is the maximum back-refresh.**
- **D-058d — ETF eligibility = history available for (lookback + 10 days).** No other
  eligibility rule; the volume filter does the rest.
- **D-058e** The weekly universe is **frozen for the week**. No midweek refresh.
- **D-058f — Missing NAV handling:** missing for **one day** → interpolate as the average of the
  previous and following day. Missing for **multiple days** → **exclude the ETF**.
- **D-058g — The weekly job emits two CSVs to Telegram:** the frozen **universe** and the
  **rejected/excluded ETF** list, for verification. Both are also stored in Supabase and
  archived to **S3** — as are all logs and generated files.
- **D-058h** Use **i-NAV when present, NAV as fallback**.
- **D-058i — Upstox is the primary price source**; Yahoo Finance exists only as a fallback,
  since it does not cover the whole universe.

### Strategy
- **D-059a** Mean vs median stays config-driven.
- **D-059b — Quantity uses a configurable budget buffer.**
  `quantity = floor((trade_amount × budget_buffer_pct) / ltp)`.
  Default **99%**, because brokerage pushes a naive `amount/price` order over the budget — at
  ₹1,000 and ₹100/unit, 10 units costs ₹1,010–1,020 and is rejected. The buffer is
  **config per account × broker × category** and **may exceed 100%** — 105% deliberately dips
  into residual funds, 200% is permitted.
- **D-059c** One sell order per security; reconcile against the order book; cancel-and-replace
  wrong prices; never double.

### 🔴 D-060 — GTT REMOVED. Fresh DAY limit sells every morning. *(Reverses D-003.)*
A resting GTT **goes stale the moment a position is averaged**, and broker GTT support is
uneven. ATOM therefore places plain **DAY limit sell orders**, recomputed and re-placed each
morning from the current weighted-average buy price; the broker cancels them at ~16:15.
*Accepted trade-off: a position is unprotected on any day the engine is not run, making a daily
run an operational requirement.* Simplifies all five broker adapters — no GTT endpoints,
semantics or reconciliation. Full detail in
[`../04-strategy/SELL-LOGIC.md`](../04-strategy/SELL-LOGIC.md).

### D-061 — Profit is all-in, excluding capital cost and tax
`Profit = sell − buy − brokerage − STT − exchange − SEBI − stamp duty − GST − DP charges`.
**Cost of capital and tax are excluded from profit** and reported on their own screens. DP
charges are the hard part: some brokers report them in the P&L, others only in the ledger days
later, so profit is **provisional until reconciled** and the UI must say which it is.
Sell target always **rounds up**.

### 🔴 D-062 — NEW: Exclusion and Freeze subsystem
ATOM does not own the account, so the morning sell pass must not sell holdings that were never
the strategy's. `sellable = holding − excluded − frozen`.
- **Exclusion** = quantity ATOM did not buy (manual purchases, unrelated shares).
- **Freeze** = quantity ATOM did buy but the operator wants held.
- **Default is to sell:** a holding with no exclusion entry **is** sold at the configured
  percentage.
- Holdings are flagged **`ATOM`** or **`UNIDENTIFIED`** by reconciliation against our own order
  records.
- **The weighted-average buy price is recomputed over the sellable quantity** before every sell.
Full detail in [`../04-strategy/EXCLUSION-AND-FREEZE.md`](../04-strategy/EXCLUSION-AND-FREEZE.md).

---

> ⚠️ **Risk accepted under D-058b (no corporate-action adjustment).** ETFs do split — Nippon
> split GOLDBEES and several ETFs have split to improve retail accessibility. An unadjusted
> split shows as a large single-day price fall, which this strategy reads as an extreme negative
> deviation and would rank as its **top buy candidate**. Recommended cheap mitigation: a
> **sanity gate** rejecting any candidate whose one-day move exceeds a configurable threshold
> (say 20%) pending operator confirmation. Raised as **Q-183**.

| Q-183 | Sanity gate on implausible one-day moves, to catch unadjusted splits |
| Q-177 | Acceptable that positions are unprotected on non-run days, or add a sells-only quick run? |
| Q-178 | Per broker: where and when DP charges surface — round 2 research |
| Q-179 | Is ₹0.01 the universal NSE ETF tick, or does it vary by price band? |
| Q-180 | Should a freeze carry an optional auto-release expiry? |
| Q-181 | If holdings fall below the excluded quantity, auto-reduce or flag? |
| Q-182 | Auto-create exclusions for unidentified quantity, or always manual? |

---

## Round 8 — 2026-09-17

### 🔴 D-063 — GTT REINSTATED, with a mandatory cancel-all-first step. *(Withdraws D-060; restores D-003.)*

The reason GTT was dropped — a resting order going stale after averaging — is removed
procedurally rather than by abandoning GTT:

```
1. CANCEL    every ATOM-placed GTT sell for this account
2. VERIFY    re-read the order book; a survivor HALTS the run and alerts
3. HOLDINGS  read from broker
4. EXCLUDE   subtract excluded + frozen (D-062)
5. RECOMPUTE weighted-average buy price over sellable quantity
6. PLACE     fresh GTT sells at round_UP(avg × (1 + target))
7. BUY LOOP  only then
```

Averaging happens only during a run, so a cancel-then-re-place at the head of every run means
a stale GTT can never survive one. Between runs the resting GTT is consistent with the last
run's state by construction.

**What this buys back:** positions stay protected on days the engine is not run — miss two
days and a target can still be hit and filled. That was the operator's decisive objection to
D-060 and it was correct.

> ⚠️ **Cancel only ATOM's own GTT IDs.** The account may hold GTTs the operator placed by hand,
> including against excluded holdings (D-062). Every GTT ATOM places is recorded with its
> broker order ID, and only those are cancelled. An unrecognised resting sell is **reported,
> never cancelled**. (Q-184)

Adapter surface: `place_gtt`, `cancel_gtt`, `get_gtt_orders`. **`modify_gtt` is not required** —
ATOM cancels and re-places, never modifies.

### D-064 — Corporate actions: detect and deactivate, do not adjust. *(Supersedes D-058b.)*

ATOM does not source or apply corporate-action adjustments. It detects the symptom:

```
if |close_today − close_yesterday| / close_yesterday > corp_action_threshold_pct:
        mark ETF INACTIVE — no ranking, no buying, no averaging
```

`corp_action_threshold_pct` is config per (trading account × category), starting at **20%**,
operator-adjustable. Deactivation blocks buying from that day, covering the Thursday/Friday
exposure described.

**Reactivation** happens at the Saturday universe rebuild: if the broker has adjusted its
history (likely), the ETF returns automatically; if not, it stays inactive and is reported
again. Both paths are safe, which is the design's point — no corporate-action feed is needed
and double-adjustment is impossible.

Deactivations are logged, shown on Daily Status, included in the weekly rejected-ETF CSV
(D-058g), and retained in the ETF master with date and reason.
Full detail in [`../04-strategy/CORPORATE-ACTIONS.md`](../04-strategy/CORPORATE-ACTIONS.md).

*Rationale for 20%: larger than almost any normal single-day ETF move, smaller than any split
ratio in common use (1:2 = −50%, 1:5 = −80%). Known blind spot: a 4:5 split is −20% and sits on
the threshold — accepted (Q-186).*

### D-065 — Freeze accrues cost of capital; exclusion does not. *(Confirms D-062.)*
Frozen quantity was bought by ATOM, is deployed ATOM capital, and **continues to accrue**.
Excluded quantity was bought outside the system, is not ATOM capital, and **never accrues**.
The operator notes freezing is expected to be rare; exclusion is the normal case.

### D-066 — `modify_order` is removed from the broker adapter contract. *(Answers Q-021.)*
Not required: orders are placed or cancelled, never amended. A buy either fills or does not;
an unfilled sell is cancelled and re-placed next run. The contract is therefore:
`authenticate`, `get_funds`, `get_holdings`, `get_positions`, `place_order`, `cancel_order`,
`get_order_status`, `get_order_book`, `get_trade_book`, `get_historical_candles`, `get_quote`,
`get_ledger`, `get_charges`, `get_funds_credits`, `place_gtt`, `cancel_gtt`, `get_gtt_orders`.

| Q-184 | Confirm: cancel only ATOM-recorded GTT IDs; report unrecognised resting sells |
| Q-185 | Per broker: is GTT cancellation synchronous, or must the book be re-polled? |
| Q-186 | Small-ratio splits (4:5 = −20%) sit on the threshold — accept, or add a feed later? |
| Q-187 | Should a holding in a deactivated ETF still get its sell order? *(Rec: yes — only buying is blocked)* |
| Q-188 | Threshold check on adjusted or raw close? *(Rec: whatever the broker returns)* |

---

## Round 9 — 2026-09-20 (answers to PENDING-QUESTIONS 56–117)

### Config
- **D-067 — Config blocking is scoped per trading account, not estate-wide.** A missing value on
  Investor A's Dhan account blocks **only that account**; A's Upstox and B's accounts run
  normally. A multi-account run proceeds for the complete accounts and reports the blocked ones
  individually. Adding a new config key blocks only the accounts missing it. *(Refines D-038.)*
- **D-068** Config changes are versioned with **who, when and timestamp**. NULL means "do not
  buy this category"; **sells continue**.

### Console
- **D-069a** Daily Status: 10 rows, greyed beyond depth. History via a date picker over all data.
- **D-069b — No dedicated Elastic IP for the console.** Use the instance's default public IP.
  *(Supersedes the Q-068 recommendation — see ⚠️ below, this has a consequence.)*
- **D-069c** UI: React + TypeScript + Tailwind, served by the Python engine. Must be **fast and
  professional, not clumsy**, with **dark and light modes**. Desktop-first, but **responsive**
  so it opens usably on mobile and iPad, with a desktop-mode option on other devices.
- **D-069d** Auth: Supabase Auth, Google sign-in restricted to named emails, password fallback.
  **2FA is a setting** — enabled if the operator wants it, not mandatory.

### Security
- **D-069e** Supabase RLS from day one. **No PAN or bank details, ever.** Log redaction of
  tokens and secrets, with a test. Every operator action audited. Global kill switch.
- **D-069f — Spend caps are per (investor × broker × account)**, matching the config grain.

### Harvesting
- **D-070a** STCG rate config, default 20%. Correlation = **Pearson on daily log returns**.
  Minimum correlation **0.85, as a config value**. Proxy must pass the volume filter. Proxy must
  be a **different ISIN** — hard constraint.
- **D-070b — Partial failure waits for the operator.** If the sell fills but the proxy buy
  fails, alert immediately, mark the chain INCOMPLETE, and **do nothing further until the
  operator decides**. They may retry (liquidity or funds having changed) or abandon it.
- **D-070c — Offset ATOM's gains only, but display all gains.** The screen shows **total
  realised gain**, split into **ATOM's gain** and **other gain**. Only ATOM's gain drives the
  harvesting process; other gains are shown for information so the operator can act on them
  manually.
- **D-070d** No frequency limit. Operator-triggered, individually approved. Expected cadence is
  monthly or quarterly, and more valuable in falling markets than rising ones.

### Orders
- **D-071a** Poll 5 minutes for a fill, then proceed and leave the order resting.
- **D-071b — Partial fills: quantity changes, average buy price does not.** Expected to be rare
  given the liquidity filter. If half fills at target and half remains, the next day's sell
  covers the remaining quantity **at the same average buy price**, re-placed per the normal
  cycle.
- **D-071c** Reconciliation at the next run plus a Telegram message covers fills that happened
  while the engine was down. Expectation is that ~99.99% of orders fill.

### Reporting
- **D-072a — Period selector offers Indian FY, calendar month, quarter, and a custom date
  range.** Not one basis — a dropdown.
- **D-072b** DP charges are a cost of the trade and are **attributed back to the sell** for
  profit (D-061), even when the broker reports them days later in the ledger.
- **D-072c — Broker ledgers are pulled automatically, once a day**, updating a local ledger.
- **D-072d** CSV export. No benchmark comparison. Log filename:
  `<investor>_<broker>_<run_id>_<date>.log`.

### Logging
- **D-072e** Google Drive via a service account writing to a shared folder. **Gzip above 10 MB**
  (raised from 5 MB — these files are expected to be kilobytes).

### Database
- **D-073a — The Supabase project does not exist and must be created from scratch.**
- **D-073b** One schema with table prefixes. Migrations as SQL files in the repo, applied via
  the Supabase CLI — **nothing is ever executed directly against the database.**
- **D-073c** `NUMERIC(_,4)`. Timestamps `timestamptz` in UTC, displayed IST, plus an IST
  `trade_date` column. FIFO lot matching. Weekly `pg_dump` to S3. Separate dev project.
- **D-073d — Purge diagnostic logs only. Trade and report data is retained for years.** Manual
  purge if ever wanted; no automated feature for it.

### Testing and ops
- **D-074a** Unit tests on strategy maths, contract tests per broker, full dry run, then
  ₹1,000-size live trades. The dry run is the end-to-end test of the whole application.
- **D-074b — No backtest harness in v1.** Moved to
  [`V2-BACKLOG.md`](./V2-BACKLOG.md).
- **D-074c — 🔴 Broker terms and conditions have NOT been checked.** Each broker's T&C must be
  **manually researched before development begins**, to confirm automated order placement is
  permitted. Added to the round 2 broker research scope as a blocking item.
- **D-074d** Free uptime monitor on the static site.

### Dry run
- **D-075a** Paper fill model: **complete fills only, no partial fills.**
- **D-075b — No dry-run vs live comparison.** Dry run is a phase (months 1–2), retired once live.
  Paper portfolios are kept indefinitely but will naturally go quiet, since paper funds are
  operator-topped-up and simply run out.
- **D-075c** A dry run may run **without EC2**, using Yahoo Finance data, since no static IP is
  needed.

### Cost of capital
- **D-076a** Simple interest, **Actual/365**, accrual base = **original cost, all-in** including
  charges.
- **D-076b — Rate changes apply forward only.** A dated rate series per trading account;
  **history is never restated**.
- **D-076c — The sell day counts as a held day.** Buy day 1, sell day 5 → **5 deployed days**;
  settlement runs from day 6 to the credit date. `deployed_days = sell − buy + 1`,
  `settlement_days = credit − sell`.
- **D-076d** Opening balance is **fetched from the broker funds API**, not entered by hand.

---

## ⚠️ Two consequences that need a decision

**1. D-069b (no dedicated Elastic IP) breaks the console URL.**
An EC2 instance's auto-assigned public IPv4 **changes every time it is stopped and started**.
Since ATOM's instance is stopped daily (D-055a), the console would be at a different address
every day, and no DNS record or bookmark would survive. Three ways out:

| Option | Cost | Assessment |
|---|---|---|
| **(a)** Lambda updates a Route 53 A record on each boot | **Free** (Route 53 hosted zone ~$0.50/mo) | Keeps the domain stable, no extra IP. **Recommended** |
| **(b)** Serve the console on one of the two broker-whitelisted Elastic IPs | Free — already paid for | Works: whitelisting governs *outbound* source IP, inbound web traffic is unaffected. Slightly muddles the IP's purpose |
| **(c)** Accept a changing IP | Free | The operator reads the new address from the Telegram `/status` reply each day. Ugly but functional, and no TLS certificate can be issued for a bare IP |

*Raised as **Q-190**. Option (a) also solves TLS, which (c) cannot.*

**2. Free secrets storage (Q-073 reopened).**
Secrets Manager was rejected on cost. Options that are genuinely free:

| Option | Cost | Assessment |
|---|---|---|
| **AWS SSM Parameter Store, Standard tier, SecureString** | **Free** — standard parameters have no charge, and the AWS-managed `aws/ssm` KMS key is free (only customer-managed keys cost $1/mo) | Purpose-built for this, IAM-controlled, audited. **Recommended** |
| Encrypted in Supabase (D-055d) | Free | Already the recorded decision. Needs app-level encryption, and the encryption key still has to live somewhere — which is the same problem one level down |
| Docker image / environment variables | Free | Secrets end up in the image or the ECS task definition. Not recommended |

*Raised as **Q-191**. SSM Parameter Store solves the key-of-the-key problem that encrypted-in-Supabase does not: the instance role grants access, so there is no bootstrap secret to store.*

| Q-189 | Confirm settlement counts the credit date itself, with idle starting the day after |
| Q-190 | Console addressing — Route 53 updated on boot, reuse a trading EIP, or accept a changing IP |
| Q-191 | Confirm SSM Parameter Store (free) over encrypted-in-Supabase for secrets |

---

## Round 10 — 2026-09-20

- **D-077** `Hybrid` ETFs are **excluded**, alongside DEBT. (Q-152 closed.)
- **D-078 — The console is served on one of the existing broker-whitelisted Elastic IPs.**
  No third IP is provisioned. Whitelisting governs *outbound* source IP, so serving inbound web
  traffic on that address does not affect broker access, and the address is stable across
  stop/start so DNS and TLS both work. (Q-190 closed, option (b).)
- **D-079 — Secrets live in AWS SSM Parameter Store (Standard tier, SecureString).** Free:
  standard parameters carry no charge and the AWS-managed `aws/ssm` key is free. Access is
  granted by the instance role, so there is no bootstrap key to store anywhere.
  *(Supersedes D-055d, encrypted-in-Supabase.)* (Q-191 closed.)
- **D-080 — Settlement spans non-trading days, and idle begins only when cash is actually
  available.** (Q-189 closed.)

  > "Security bought on Monday, sold on Friday — five days deployed. But Friday T+1 is actually
  > Monday, so Saturday, Sunday and Monday come as settlement, and only when it becomes
  > available cash does idle start."

  | Phase | Days (worked example) | Count |
  |---|---|---|
  | DEPLOYED | Mon (buy) … Fri (sell), inclusive | **5** |
  | SETTLEMENT | Sat, Sun, **Mon (credit date, inclusive)** | **3** |
  | IDLE | Tue onward | — |

  `deployed_days = sell − buy + 1` · `settlement_days = credit − sell` · idle starts
  `credit + 1`.

  **Weekends and holidays accrue in full**, consistent with all-seven-day accrual (D-045), and a
  settlement spanning a long weekend simply costs more — which is exactly what the bucket exists
  to reveal. Because `credit_date` is observed, never assumed (D-050), an extended settlement
  over a holiday cluster is captured automatically.

---

## Round 11 — 2026-09-20

- **D-081 — Cancel only ATOM-placed GTT orders.** (Q-184 closed.) Every GTT ATOM places is
  recorded with its broker order ID, and the cancel pass targets only those. Orders placed
  manually are never touched; an unrecognised resting sell is **reported, never cancelled**.
- **D-082 — A deactivated ETF still gets its sell order.** (Q-187 closed.) Selling needs only
  the average buy price, the quantity and the target — none of which come from the suspect
  price series. Corporate-action deactivation therefore blocks **buying only**.
- **D-083 — The corp-action threshold checks whatever close the broker returns.** (Q-188
  closed.) That is the series the strategy consumes, so it is the series that must be sane.
- **D-084 — 🔴 Nothing is ever auto-released. Ever.** (Q-180 closed.)
  A freeze, an exclusion or a corporate-action deactivation **never expires, never auto-releases
  and never reverts to sellable on its own**. Only an explicit operator action releases any of
  them. No expiry dates, no timers, no "stale entry" cleanup.

  > "If manually a security is placed on freeze or is deactivated, do not ever un-release it or
  > make it sell. That should be totally in the user's hands."

  *Design consequence: no background job may mutate freeze, exclusion or deactivation state.
  The only writer is the operator, through the UI. This is stricter than the earlier D-064
  wording, which had the weekly universe job reactivating a deactivated ETF automatically —
  **that auto-reactivation is withdrawn**; the weekly job may only re-evaluate and **report**,
  leaving the release to the operator.*

- **D-085 — Exclusion drift is flagged, never auto-corrected.** (Q-181 closed.) If holdings fall
  below the excluded quantity, raise a flag for the operator. Silently reducing the exclusion
  would hide a reconciliation gap.
- **D-086 — ATOM never auto-creates exclusions.** (Q-182 closed.) Unidentified quantity is
  reported; the operator decides. Auto-excluding would silently stop ATOM selling something it
  should sell.

### Process gate
- **D-087 — All discussion closes before any code is written.** Broker research and end-to-end
  broker detail complete first; the first line of application code waits until the design
  conversation is finished.

---

## Round 12 — 2026-09-20 · Broker research begins (R2: SEBI compliance)

**D-088 — The per-broker rate limiter is a compliance control.** SEBI's retail algo framework
(in force since 1 April 2026) exempts self-developed retail algos from exchange registration
**provided they stay under the Threshold Orders Per Second — 10 OPS** on NSE and BSE. ATOM
places ~20 orders **per day**, so it sits about four orders of magnitude below the line. To
keep it there structurally, the rate limiter is **hard-capped at 2 OPS**, not configurable
upward without an explicit logged override.

**D-089 — Keep an unused `algo_id` field in the order schema.** Registered algos must tag every
order with an exchange-assigned Algo ID. ATOM does not need one below TOPS, but carrying the
field now makes future compliance a value to populate rather than a schema migration.

### 🔴 Finding that may affect the operating model

**SEBI defines "family" narrowly: self, spouse, dependent children and dependent parents.**
A self-developed algo may be used for those accounts and **no others**.

D-004 recorded ATOM's posture as "self and family", which keeps it outside the algo-provider
regime — **but only if every onboarded investor falls inside that definition**. A sibling,
friend, in-law or independent parent does not.

> **Q-192 — What is Person B's relationship to the operator?** This is now the highest-priority
> open question in the project: it is the only one that can invalidate the operating model
> rather than adjust a design detail.

It also means the founding brief's ambition — "anyone having an account with any of these five
brokers should be able to connect with our utility" — describes **being an algo provider**,
a registered role acting as an agent of the broker. The architecture is unaffected and worth
building either way; the *onboarding policy* is a regulatory decision, not a config change.

Full analysis in [`../09-security/SEBI-ALGO-COMPLIANCE.md`](../09-security/SEBI-ALGO-COMPLIANCE.md).

| Q-192 | 🔴 Person B's relationship to the operator — determines whether the family exemption covers them |
| Q-193 | Q-186: add the peer-comparison discriminator for corporate actions, or accept the blind spot? |

---

## Round 13 — 2026-09-20

**D-093 — Averaging rules.**
- Loss buckets (5%, 10%) are **configurable**, per trading account × category.
- **No limit on how many times** a position may be averaged.
- **Maximum one lot per instrument per day.** If `trade_amount_inr` is ₹10,000, a security can
  be averaged by at most ₹10,000 in a day.
- Averaging **respects the NAV gate** (D-034b) and **respects `category_enabled`**.
- Funds follow D-042 — place the order and let the broker reject it.

**D-094 — Averaging is blocked in a category where the algo already bought today.**
Averaging exists to deploy capital when the depth/skip rules produced no buy. If the daily run
*did* buy in that category, averaging is redundant.
- The Average option is **still shown** on screen.
- Tapping it raises a popup: *"already bought by the daily run, hence no buy"*.
- The popup carries an **override**. On override, the average order is placed.

*So the rule is advisory-with-override, not a hard block — the operator keeps final say, but
cannot trip over it by accident.*

**D-095 — Correlation is computed on demand only**, when a harvest proposal is requested. Never
scheduled, never cached on a timer.

**D-096 — Correlation pools are sector-restricted.** An auto ETF is correlated against auto
ETFs only, never against a Nifty 50 ETF. Equity splits **BROAD / SECTOR / FACTOR**, and SECTOR
splits further into ~15 sector groups. Proxies must share a pool, pass the volume filter, and
carry a different ISIN. Analysis in
[`../04-strategy/SECTOR-BUCKETS.md`](../04-strategy/SECTOR-BUCKETS.md).

*Finding: **five sector groups cannot be harvested at all** — FMCG/Consumption, Chemicals,
Internet, Manufacturing and Other Thematic have one liquid ETF or none, so no different-ISIN
proxy exists. The harvest screen must show "no proxy available" with the reason rather than
silently omitting those holdings. Gold (17 liquid), Silver (14), Banking (9), Pharma (5) and
Auto (5) harvest reliably.*

**D-097 — `peer_min_count` is a config value, default 3, and may be set as low as 1.**
(Q-194 closed.) The operator may widen or narrow the peer requirement at will.

**D-098 — The three-stage lifecycle applies to corporate-action blocks only.** (Q-195 closed.)
Freezes and exclusions are deliberate operator choices and need no review queue.

**D-099 — Dividends are out of scope entirely.** (Gap closed.) ETF distributions are credited
to the investor's **bank account, not the broker funds account**, so they never touch the
trading ledger, principal, cost of capital, profit, or reconciliation. No modelling required.

| Q-196 | Confirm the BROAD/SECTOR/FACTOR split and the 15 sector groups |
| Q-197 | Should BROAD ETFs harvest against each other (one Nifty 50 tracker for another)? |
| Q-198 | FACTOR harvesting within-factor only, or across factors? |
| Q-199 | Who maintains sector groups as NSE lists new themes? |

**D-100 — INDEX ETFs bucket by market-cap segment; there is no single "broad" pool.**
(Q-197 closed, and it corrects D-096.) The first pass demanded sector precision for SECTOR while
leaving 100 index trackers in one pool, which would have permitted swapping a Nifty 50 ETF for a
Smallcap 250 ETF — booking the loss while completely changing market-cap exposure.

Nine index buckets: **LARGECAP_50** (32 ETFs, 7 liquid) · **MIDCAP** (16/9) · **SMALLCAP** (8/5) ·
**BROAD_MARKET_500** (7/4) · **NEXT_50** (15/3) · **NIFTY_100** (6/2) · **NIFTY_200** (1/0) ·
**MSCI_INDIA** (4/0) · **IPO_THEME** (2/0).

LARGECAP_50 merges Nifty 50 and BSE Sensex, which track the same segment at ~0.99 correlation;
the 0.85 floor validates every pair independently, so a wrong merge is caught rather than
executed. Its seven liquid trackers make it one of the three cleanest harvest pools alongside
GOLD (17) and SILVER (14).

The bucket name **BROAD is renamed INDEX** throughout.

| Q-200 | Merge NEXT_50 into LARGECAP_50? Correlation ~0.85–0.90, right on the floor *(Rec: keep separate)* |

**D-101 — Classification is evaluated sector-first, then factor, then index. Zero ETFs are
unbucketed.** All 350 land in a defined bucket. The ordering is itself the fix for the
keyword bugs in earlier passes: `BSE Top 10 Banks` and `BSE MidSmall Private Banks` now resolve
correctly to SECTOR/BANKING. Two proposed buckets, `INDEX/CONCENTRATED_TOP_N` and
`INDEX/MIDSMALLCAP`, are **empty and removed** — they existed only to catch what the ordering
now places correctly.

*Two buckets are not genuine correlation pools and need fixing (Q-201): `SECTOR/OTHER_THEMATIC`
is a catch-all mixing Tourism, MNC and Services Sector, and `SECTOR/MANUFACTURING` mixes
Manufacturing with Nifty Commodities. Neither currently matters — no member is liquid — but a
fake pool is a latent correctness bug.*

**D-102 — FACTOR splits by factor type, the same correction as D-100.** 57 ETFs sat in one
pool; momentum, value, quality and low-volatility are different and often inversely-behaving
exposures, so harvesting between them would swap the factor while appearing to preserve it.
Eleven sub-buckets: MOMENTUM (10 ETFs, **7 liquid** — the only reliably harvestable factor) ·
VALUE (9/2) · QUALITY (8/2) · LOW_VOLATILITY (6/2) · MOMENTUM_QUALITY_COMBO (5/2) · ALPHA (3/2) ·
EQUAL_WEIGHT (9/1) · DIVIDEND (4/0) · SHARIAH, ESG, GROWTH (1/0 each).

**Full harvest viability: 12 buckets are reliable, 13 are thin, and 14 cannot be harvested at
all.** Every holding in the last group can never have its loss booked while keeping exposure,
and the harvest screen must say so against the holding rather than omitting it.

| Q-201 | Dissolve `OTHER_THEMATIC` into single-member buckets and split `Nifty Commodities` out of `MANUFACTURING`? |
| Q-202 | Split factor buckets by market-cap segment too? *(Rec: no — it would cut the only healthy factor pool from 7 to ~4 and ~3; let the 0.85 correlation floor filter instead)* |

---

## Round 14 — 2026-09-20 · Two-tier harvest matching

**D-103 — Proxy matching is two-tier: exact index first, segment second.**
Splitting the large buckets further (as instructed) leads to bucketing by the **exact underlying
index**, which gives a near-perfect proxy — same index, different ISIN, correlation ~0.99. But
exact-index alone leaves 38% of liquid equity ETFs with no peer. Two tiers keep both properties:

| Tier | Pool | Use |
|---|---|---|
| **TIER 1** | **Exact underlying index** (`Nifty 50`, `Midcap 150`, `GOLD`) | **Preferred.** A same-index swap is as close to exposure-neutral as harvesting gets |
| **TIER 2** | Segment / sector group (`LARGECAP_50`, `BANKING`) | **Fallback**, only when tier 1 has no liquid peer. The 0.85 correlation floor still applies |

**Measured across the 127 liquid tradable ETFs: 92 have a tier-1 proxy, 22 fall back to tier 2,
and 13 have none.** The harvest screen shows which tier a proposal used, so a tier-2 swap is
visibly a compromise rather than silently equivalent.

**D-104 — Q-201 applied.** `OTHER_THEMATIC` is dissolved into `TOURISM`, `MNC` and `SERVICES`;
`COMMODITIES_EQUITY` is split out of `MANUFACTURING`.

**D-105 — Q-202 applied: factor buckets split by market-cap segment.** `MOMENTUM` becomes
`MOMENTUM_LARGECAP200`, `MOMENTUM_MIDCAP`, `MOMENTUM_BROAD500` and so on.

> ⚠️ **The cost is now measured, and it is heavy.** Of 18 liquid FACTOR ETFs, splitting by cap
> leaves **only 4 with a tier-1 proxy and 4 with tier 2 — 10 have none at all**, including
> liquid names like ALPHA (786k), ALPHAETF (738k), LOWVOLIETF (472k), TOP10ADD (453k) and
> MOMENTUM50 (240k). Before the split, MOMENTUM alone had 7 mutually harvestable ETFs.
>
> This is the correct-but-costly outcome that was flagged when the question was asked. It stands
> as instructed, and is reversible by a config change if factor harvesting turns out to matter
> more than factor purity. Raised for revisit as **Q-203**.

**D-106 — The taxonomy is generated by a committed, re-runnable script**, not by hand:
`scripts/build_etf_buckets.py` reads an NSE export and emits the bucket CSV. Re-running it on a
fresh export reproduces the classification exactly, and a new listing is one re-run away.

| Q-203 | Revisit D-105 — factor-by-cap splitting removes proxies for 10 of 18 liquid factor ETFs. Keep, or fall back to factor-type only for tier 2? |

---

## Round 15 — 2026-09-20

**D-107 — Final tradable bucket list excludes DEBT and HYBRID.**
`docs/99-vendor-docs/nse/etf-tradable-buckets-2026-09-17.csv` — **311 ETFs** (39 removed: 38
DEBT + 1 HYBRID), of which **127 are liquid**: INDEX 90/29 · SECTOR 113/44 · FACTOR 57/18 ·
COMMODITY 45/31 · GLOBAL 6/5. This is the final list.

**D-108 — Bucket management is operator-governed with an unassigned pool.** Three statuses —
`AUTO`, `MANUAL`, `UNASSIGNED`. The classifier runs **on demand only** (expected every 6–12
months), never on a schedule, and produces a **change set** that is reviewed item by item;
accept applies it, reject sends the ETF to the **unassigned pool** rather than reverting it.
Manual add/remove/move is available at any time.

> 🔴 **Manual assignments are never overwritten by a classifier run.** An operator correction
> must not be silently undone six months later — the run would look successful while quietly
> reintroducing a harvesting bug. Where the classifier disagrees with a manual assignment it
> shows an informational note, never a change to accept.

Removing an ETF to UNASSIGNED never strands a position: sells continue from our own lot
records, and only buying and proxy matching stop. Full spec in
[`../04-strategy/BUCKET-MANAGEMENT.md`](../04-strategy/BUCKET-MANAGEMENT.md).

**D-109 — NEXT_50 stays separate from LARGECAP_50.** (Q-200 closed, with the operator's
reasoning recorded: *"Next 50 has stocks from 51 to 100, but largecap may have few holdings
which are in 1–50."*) The constituent sets differ, so they are not interchangeable exposures.

### 🔴 D-110 — Harvest proxies get their own, lower volume threshold

Investigating the 13 liquid ETFs with no proxy showed that **10 of them are not orphans at
all** — peers tracking the *same exact index* exist and are simply below the 1-lakh volume
filter. Examples: FMCGIETF's peer FMCGADD (37k), NV20IETF's peer NV20 (46k), MOMENTUM50's peer
GROWWMOM50 (71k), GROWWNET's peer INTERNET (96k — **short of the threshold by 4%**).

**The liquidity requirement for a proxy should not equal the requirement for a daily-traded
holding.** A harvest proxy is bought once and held; it does not need the turnover that a
repeatedly-traded position does. So `harvest_proxy_volume_threshold` becomes its own config
value, per (trading account × category), with **no default** (D-038).

Measured effect, holding threshold fixed at 100,000:

| Proxy threshold | Tier-1 | Tier-2 | No proxy |
|---|---|---|---|
| 100,000 *(as before)* | 92 | 22 | **13** |
| 50,000 | 97 | 21 | 9 |
| **20,000** | **101** | **20** | **6** |
| 5,000 | 105 | 16 | 6 |
| none | 108 | 16 | 3 |

**Suggested starting value: 20,000 units** — it recovers 7 of the 13 orphans and pushes tier-1
coverage from 92 to 101, while still excluding genuinely untradeable instruments.

**Only three ETFs are true orphans at any threshold** — ALPHAETF (Nifty 200 Alpha 30),
ALPL30IETF (Nifty Alpha Low-Volatility 30) and FLEXIADD (Nifty 500 Flexicap Quality 30) — each
the sole tracker of its index. Nothing can be done for those; the harvest screen states it.

**D-111 — Reference-data fetching is scripted but cannot run in this environment.**
`scripts/fetch_etf_reference_data.py` resolves scheme name, AMC, benchmark, ISIN, expense ratio
and launch date from the NSE ETF listing, NSE quotes, the AMFI scheme master and MFAPI, with
per-field source and timestamp. **All four hosts are refused (HTTP 403) by this session's egress
policy**, so it must be run on the EC2 box or any machine with open outbound HTTPS. It degrades
gracefully — it was executed here and produced a complete, empty-valued file rather than
failing.

> **Note on benchmarks:** NSE's `SUB-CATEGORY` column already *is* the benchmark index for most
> ETFs — it is NSE's own statement of what each ETF tracks, and it is what the current tier-1
> bucketing uses. External sources will mostly corroborate it; their value is in resolving the
> handful of coarse or ambiguous entries, and in supplying expense ratio and launch date, which
> NSE does not publish here.

| Q-204 | Block a classifier run while a previous change set has undecided items? |
| Q-205 | Show unassigned ETFs on Daily Status greyed, or hide them? |
| Q-206 | Confirm `harvest_proxy_volume_threshold` starting value of 20,000 units |

### 🔴 D-112 — Bucketing is purely tracking-based. Liquidity plays no part.
*(Corrects D-107 and supersedes D-110.)*

> "While creating buckets do not consider liquidity. Liquidity is a config and might change, and
> several which are not active might get active. Bucketing should be purely based on tracking."

Correct, and it was a real leak in the taxonomy: a dormant ETF that gains volume next quarter is
**the same instrument tracking the same index** — its bucket should never have depended on
yesterday's turnover. Peer counts are now computed over **all** ETFs in a pool, and volume is
carried as `VOLUME_INFO_ONLY` / `LIQUID_INFO_ONLY`, informational columns that no logic reads.

**The effect is large.** Proxy availability across the 311 tradable ETFs:

| | Liquidity-filtered (wrong) | Tracking-only (correct) |
|---|---|---|
| TIER 1 — same index | 92 | **262 (84%)** |
| TIER 2 — same group | 22 | 29 |
| No proxy | 13 of 127 liquid | **20 of 311** |

The earlier "14 buckets cannot be harvested at all" finding was an artefact of the liquidity
filter and is **withdrawn**. Only **20 ETFs** are genuine sole trackers of a sole-member group —
led by ALPL30IETF, ALPHAETF, FLEXIADD — and for those nothing can be done.

`harvest_proxy_volume_threshold` (D-110) is therefore **withdrawn as a bucketing concept**. It
survives only as the advisory limit in D-113.

### D-113 — Liquidity is an execution-time advisory with an operator override

Liquidity is checked when an order is about to be placed, not when a taxonomy is built, and it
**warns rather than blocks**:

| Flow | Behaviour |
|---|---|
| **Averaging** | If the security is below the account's current volume limit, the popup shows it as **illiquid**, with the observed volume and the limit. The operator can **cancel** or **override and proceed** |
| **Harvest proxy** | If the best-correlated proxy is below the limit, it is shown **marked illiquid**. The operator can cancel the harvest or **override and buy it anyway** to book the tax loss |

> "User has the option to cancel the averaging process, or override and buy a security for tax
> loss even if it does not match the liquidity constraint at account level."

This is the same advisory-with-override pattern as D-094 (averaging where the algo already
bought), and it is the right shape: **an illiquid proxy that books a real tax loss may well be
worth buying**, and only the operator can weigh that. The system surfaces the fact and records
the override in the audit trail (D-069e) and the run log (D-035).

*Note: the daily buy path is unchanged — the volume filter still governs **universe
construction** (D-016/D-027), because that is about which instruments the strategy trades
routinely. The override applies to the two discretionary flows only.*

| Q-206 | ~~Confirm proxy threshold~~ — ✅ withdrawn by D-112 |
| Q-207 | Should an override be permitted on the daily buy path too, or stay limited to averaging and harvesting? *(Rec: stay limited — the daily path is automated and an override there has no operator watching it)* |

**D-114 — Reference-data fetching no longer depends on NSE.** *(Replaces D-111.)*
The first script keyed everything off NSE — ISIN came from the NSE API and the AMFI lookup was
keyed on that ISIN — so an NSE 403 emptied the whole chain. That was a design fault, not an
environment problem.

The rewrite uses **four independent sources**, tried in order, each contributing whatever it can:

| # | Source | Auth | Gives |
|---|---|---|---|
| 1 | `images.dhan.co/api-data/api-scrip-master-detailed.csv` | none | **ISIN**, trading symbol, name |
| 2 | `assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz` | none | **ISIN**, trading symbol, name |
| 3 | `portal.amfiindia.com/spages/NAVAll.txt` | none | Official scheme name, **AMC**, by ISIN |
| 4 | `nsearchives.nseindia.com/content/equities/EQUITY_L.csv` | none | Symbol → ISIN (static archive) |

**Sources 1 and 2 are broker CDN asset files** — plain static downloads with no cookies, no
browser emulation and no bot protection, unlike `nseindia.com`. Either alone resolves
symbol → ISIN → name.

**Local-file fallback:** every source accepts `--dhan-file`, `--upstox-file`, `--amfi-file`,
`--nse-file`. A browser download is never blocked the way a script is, so a fully blocked
machine can still complete the job by hand.

**Benchmark derivation:** no public API exposes it. It is parsed from the scheme name
("Nippon India ETF Nifty 50 BeES" → "Nifty 50") and **cross-checked against the NSE
SUB-CATEGORY** already held in the bucket CSV, with the result recorded as `YES` or `REVIEW`
per ETF. Disagreements are flagged for the operator, never silently resolved.

*Verified end-to-end with a local file in this session: symbol → ISIN → scheme name → derived
benchmark → NSE cross-check all produced correct output.*

---

## Round 16 — 2026-09-23

**D-115 — GLOBAL splits by tracked index, using scheme-name evidence.** NSE labels all six
global ETFs `GLOBAL INDICES`, but their scheme names show five different indices across two
markets: Nasdaq 100, Nasdaq Q50, S&P 500 Top 50 and NYSE FANG+ (US); Hang Seng and Hang Seng
TECH (Hong Kong). One pool would have permitted harvesting US tech exposure into Hong Kong
exposure. Tier 2 becomes `US_EQUITY` / `HK_EQUITY`; tier 1 is the exact index.

**D-116 — Taxation is per bucket, and two of the three are not flat rates.** *(Supersedes the
single 20% STCG in D-070a.)*

| | EQUITY | COMMODITY | GLOBAL |
|---|---|---|---|
| STCG ≤12m | **20% flat** | **investor's slab rate** | **investor's slab rate** |
| LTCG >12m | 12.5% | 12.5% | 12.5% |
| Annual exemption | **₹1.25 lakh** (LTCG) | none | none |
| STT | yes | no | no |

Plus 4% cess. Commodity and global STCG follow the **investor's marginal slab** — up to 30%
before cess — so they cannot be system constants and must be captured per investor.

Three consequences, all new:
1. **Harvesting must rank by tax saved, not loss size.** A ₹10,000 commodity loss at a 30% slab
   saves ₹3,120; a ₹12,000 equity loss at 20% saves ₹2,496. Ranking by loss picks the worse one.
2. **Set-off rules differ:** short-term losses offset STCG *and* LTCG; long-term losses offset
   LTCG only. Losses carry forward 8 years. Track by type and vintage, not as one pool.
3. **The 12-month boundary conflicts with the daily sell rule (D-063).** Crossing 12 months
   drops equity from 20% to 12.5%, and commodity/global from ~30% to 12.5% — worth ₹1,750 on a
   ₹10,000 commodity gain. ATOM currently sells regardless of holding period. Raised as Q-208.

Full detail in [`../08-reporting/TAXATION-MODEL.md`](../08-reporting/TAXATION-MODEL.md).

| Q-208 | 🔴 12-month boundary — ignore, warn, or defer the sell? *(Rec: warn)* |
| Q-209 | The investor's marginal slab rate, per investor |
| Q-210 | Model surcharge, or slab + cess only? |
| Q-211 | Track carried-forward losses across FYs? |
| Q-212 | Is the ₹1.25 lakh equity LTCG exemption applied per investor across accounts? |

---

## Round 17 — 2026-09-23 · Design questions closed

**D-117 — Factor tier-2 drops the cap segment.** (Q-203 closed.) Tier 1 keeps the exact index,
so cap precision is preserved where a same-index peer exists; tier 2 falls back to the factor
type alone, so a midcap momentum ETF can proxy a largecap momentum ETF. The 0.85 correlation
floor guards the swap.

*Effect: orphans across the 311 tradable ETFs fall from **20 to 8**; within FACTOR, from 10
liquid orphans to **3 in total** (ESG, GROWTH, SHARIAH — each the sole ETF of its kind).*

**D-118 — 12-month boundary: warn, never defer.** (Q-208 closed.) Daily Status flags positions
approaching LTCG; the engine never suppresses a sell. Noted that long-term holdings are
expected to be rare — a position either hits its target or is harvested — so this is a
safety net, not a common path.

**D-119 — Tax rates are declared by the operator, not inferred.** (Q-209, Q-210 closed.)
The operator declares **income** and **tax slab**; ATOM derives the STCG rate for commodity and
global from the declared slab, and applies **surcharge only when the declared income crosses
the threshold** (₹50 lakh). Nothing is guessed from trading data.

**D-120 — Harvesting is ranked by tax saved.** (Confirms §2.2 of the taxation model.) The
harvest screen sorts opportunities by **estimated tax saved**, not loss size, and shows the
computation, so it is visible why a smaller commodity loss outranks a larger equity one.

**D-121 — Carry-forward losses are tracked across financial years.** (Q-211 closed.) By type
(short-term vs long-term) and vintage, for the 8-year carry-forward window.

**D-122 — The LTCG exemption is a config value.** (Q-212 partly closed.) `ltcg_exemption_inr`
defaults to nothing and is set to ₹1,25,000 today, so a statutory change is a config edit.

> 🔴 **Flagged for correction: the exemption is per PAN, not per account.**
> The instruction was "per account ₹1.25 lakh should be done". Under the Income-tax Act the
> ₹1.25 lakh equity LTCG exemption is an **annual allowance of the assessee (the PAN)**, not of
> a demat or trading account. Since ATOM is mostly one person's accounts across several brokers
> (D-092), applying it per account would claim the exemption two or three times over and
> **understate tax by up to ₹15,625 per extra account** (12.5% of ₹1.25 lakh).
>
> **Recommendation: apply it once per investor**, across all their trading accounts, and show
> the consumed/remaining balance at investor level. Per-account reporting can still show each
> account's contribution. See Q-213.

**D-123 — Broker tax data includes non-ATOM trades, and must.** (Operator-raised.) When the tax
report is pulled from a broker it may contain gains from trades ATOM never made. Those gains
**consume the same annual exemption and the same set-off pools**, so the tax position is only
correct if they are included. ATOM therefore ingests the broker's full capital-gains statement
and **tags each trade as ATOM or EXTERNAL** (consistent with the provenance flags in D-062),
reporting both separately and combined.

*This also means ATOM's tax view is only as complete as the accounts connected to it — a gain
in an account ATOM does not see cannot be counted. The tax screen should state that limit
rather than imply completeness.*

**D-124 — Taxonomy confirmed.** (Q-196 closed.) Three buckets, 9 index groups, ~18 sector
groups, 11 factor types, GLOBAL split US/HK.

**D-125 — The operator creates new sector groups.** (Q-199 closed.) When NSE lists a new theme,
the operator defines the group; the classifier does not invent one.

**D-126 — Unassigned ETFs are shown greyed on Daily Status.** (Q-205 closed.) Visible but
inert, so nothing is silently forgotten.

| Q-213 | 🔴 Confirm the LTCG exemption is applied per investor (per PAN), not per trading account |
| Q-204 | Block a classifier run while a previous change set has undecided items? — explanation requested |

**D-127 — The tax engine computes FIFO per demat account, but everything else per PAN.**
(Q-213 closed, Q-204 closed — a classifier run is **blocked** while a previous change set has
undecided items.)

CBDT Circular 768 (1998) applies FIFO **vis-à-vis each demat account** — stock in another
account cannot be treated as sold. But the assessee is the **person**, so gain pooling,
loss set-off, the ₹1.25 lakh exemption, surcharge, cess and the final liability are all
computed **once per PAN**. One investor with three broker accounts has **one** liability, and
it cannot be obtained by summing three independently-computed numbers.

Nuances captured, several of which change the arithmetic:
- **The 15% surcharge cap does not apply to commodity and global STCG.** It covers gains under
  s.111A/112A/112; slab-rate STCG falls outside, so at high income it attracts the full 25–37%
  surcharge on top of a 30% slab — the most expensive combination in the system.
- **STT is not deductible** from capital gains, though brokerage, exchange fees, stamp duty, DP
  charges and GST all are. So "profit" (D-061) and "taxable gain" are deliberately different
  numbers and must not be conflated.
- **Set-off has a legal order**: current-year before brought-forward, oldest vintage first;
  short-term losses offset either kind of gain, long-term losses only long-term.
- **Advance tax** instalments (15/45/75/100% by 15 Jun/Sep/Dec/Mar) with s.234B/234C interest —
  an active short-term strategy accrues liability all year.
- **s.94(7) dividend stripping** can disallow a harvested loss outright if the sale lands within
  three months of a distribution record date — silently defeating the harvest.
- **Dividends remain taxable** at slab even though D-099 excludes them from the trading engine.

Full specification in [`../08-reporting/TAX-ENGINE.md`](../08-reporting/TAX-ENGINE.md).

> ⚠️ **D-075 conflict:** PAN-level aggregation needs a grouping key, but not the PAN digits.
> Recommendation is `investor_id` plus a **masked** PAN for statement verification, never the
> full number. See Q-214.

| Q-214 | 🔴 Store investor_id + masked PAN only? (conflicts with D-075) |
| Q-215 | Report "profit" and "taxable gain" as two distinct figures |
| Q-216 | Show advance-tax instalment dates and estimates? |
| Q-217 | Check harvest sales against the s.94(7) dividend-stripping window? |
| Q-218 | Note dividend income as out of scope but taxable? |
| Q-219 | Should ATOM propose tax actions beyond harvesting, or stay descriptive? |

---

## Round 18 — 2026-09-23 · Design conversation closed

**D-128 — The full PAN is never stored. A unique internal key groups a user's accounts.**
(Q-214 closed, D-075 upheld.) Each investor gets an internal `investor_id`, and every broker
account carries that key. Tax aggregation happens on the key, never on PAN digits. Nothing
changes in the computation — the key does exactly the grouping work the PAN would have done.

**D-129 — Dividends stay fully out of scope.** (Q-218 closed.) Operator's reasoning, and it is
correct: dividend income is **income from other sources** taxed at slab. It does **not** consume
the ₹1.25 lakh capital-gains exemption and does **not** enter the capital-gains set-off pools.
Excluding it therefore leaves the capital-gains computation exactly right, rather than
approximately right. ATOM reports capital-gains tax, not total tax, and the screen says so.

**D-130 — Advance tax is deferred to v2.** (Q-216 closed.) Volumes are too small for the
instalment obligation to matter. Recorded in the v2 backlog with the mechanics, so it is
recoverable rather than forgotten.

**D-131 — s.94(7) dividend stripping is deferred to v2.** (Q-217 closed.) Parked with its full
mechanics: a harvest sale within three months either side of a distribution record date has its
loss **disallowed to the extent of the dividend**. It also needs ETF record-date data that no
current source provides. Revisit when harvest volume makes a disallowed loss material.

*All three deferrals are in [`V2-BACKLOG.md`](./V2-BACKLOG.md) as V2-9 … V2-12, with enough
detail to act on without re-deriving the reasoning.*

**D-132 — No liquidity override on the daily buy path.** (Q-207 closed.) The override exists
because a human weighs the trade-off; the daily run is automated with nobody watching, so there
is no one to weigh it. Overrides stay limited to **averaging** and **harvest proxy selection**
(D-113). The volume filter governs universe construction absolutely.

**D-133 — "Profit" and "taxable gain" are reported as two distinct figures.** (Q-215 closed.)
Profit (D-061) subtracts all charges including STT; taxable gain adds STT back, since STT is not
deductible from capital gains. Both are labelled, shown side by side, with the difference
visible. One blended number would be wrong for one purpose or the other.

**D-134 — Proactive tax proposals are deferred to v2.** (Q-219 closed.) v1 stays descriptive
outside harvesting and the position-specific LTCG warning (D-118). Recorded as V2-13.

---

# 🏁 DESIGN CONVERSATION CLOSED — 2026-09-23

**134 decisions across 18 rounds.** Every question raised has been answered, deferred to v2 with
its reasoning, or converted into a research task. Two cold-start gaps are raised below; they
concern onboarding rather than design, and do not reopen anything decided.

## Two onboarding gaps found while closing out

**Q-220 🔴 — What happens to holdings that already exist on day one?**
D-062 makes the default behaviour *sell anything not explicitly excluded*, using the broker's
reported average cost for holdings ATOM did not buy (D-059/`EXTERNAL`). Taken literally, the
**first run would place sell orders across every ETF already in the account**, at the configured
profit percentage, whether or not the operator intended those positions to be managed.

That is almost certainly not wanted on day one. Options:
- **(a)** Onboarding presents every existing holding and the operator marks each **ADOPT** or
  **EXCLUDE** before the first run — nothing is sold until that is done.
- **(b)** Everything existing is auto-excluded; only positions ATOM buys are ever managed.
- **(c)** Everything existing is adopted, as the current rules imply.

*Recommendation: **(a)**. It is one screen, it is a decision only the operator can make, and it
matches the no-defaults principle (D-038). **(b)** is the safe fallback if that screen slips.*

**Q-221 🟠 — Adopted holdings have no buy date, so cost of capital cannot start.**
D-045 accrues per lot from the **buy date**. A holding adopted at onboarding has a broker-reported
average cost but often **no acquisition date** — broker holdings APIs commonly omit it. Without a
date there is no accrual start.

Options: take the date from the broker's **trade book** where history reaches back far enough;
have the operator **enter** an acquisition date per adopted lot; or **start accrual from the
onboarding date**, accepting that pre-existing holding period is not charged.

*Recommendation: trade book where available, operator entry where not, onboarding date as the
last resort — and flag which basis was used, since it changes the cost-of-capital figure.*

| Q-220 | 🔴 Day-one treatment of existing holdings — adopt, exclude, or choose per holding |
| Q-221 | Acquisition date for adopted holdings, for cost-of-capital accrual |

---

## Round 19 — 2026-09-23 · Broker research begins

**D-135 — D-056b (raw HTTP, not vendor SDKs) is confirmed on evidence.** The SDKs were
downloaded from PyPI and read directly:

| Broker | Per-instance proxy | Finding |
|---|---|---|
| **Upstox** | ✅ | `configuration.proxy` → `urllib3.ProxyManager`; two Configurations coexist cleanly |
| **Dhan** | ⚠️ | Trading calls use a per-instance `requests.Session` (proxy settable post-construction), but **six calls in `auth.py` and `_security.py` use module-level `requests` and bypass it entirely** |
| **Shoonya** | ❌ | GTT absent from the SDK, present in REST — cannot express ATOM's sell logic |

> 🔴 The Dhan gap is the failure mode the design exists to prevent: **orders would egress from
> the correct whitelisted IP while the authentication flow left from the instance's default
> route**, silently. Nothing would look broken. Fixing it requires patching `requests`
> process-globally — reintroducing the very problem — or forking the SDK.

**D-136 — A proxy is a mandatory constructor argument on every broker adapter**, and a missing
proxy **raises** rather than falling back to the default route. A test must prove no code path
can reach a broker without one. Full analysis in
[`../03-brokers/SDK-EVALUATION.md`](../03-brokers/SDK-EVALUATION.md).

*The SDKs remain valuable as the most accurate available specification of each broker's API —
endpoint paths, payload shapes, enums and error formats read from working code rather than
prose. PyPI is also reachable from restricted environments where broker sites are not.*

| Q-222 | Confirm a missing proxy raises rather than defaulting to the instance IP |
| ~~Q-223~~ | ✅ Verified — see D-139 |

**D-139 — All five SDKs inspected. Three of five cannot meet the static-IP requirement at all.**
(Q-223 closed.)

| Broker | Sessions | Bare `requests` calls | Per-instance proxy |
|---|---|---|---|
| **Zerodha** | 1 | 0 | ✅ `proxies=` passed on every request — cleanest of the five |
| **Upstox** | urllib3 | 0 | ✅ `configuration.proxy` → `ProxyManager` |
| **Dhan** | 1 | **6, all in `auth.py`/`_security.py`** | ⚠️ trading yes, **authentication leaks** |
| **Groww** | **0** | **5** | ❌ no session object exists to attach a proxy to |
| **Shoonya** | **0** | **26** | ❌ same, at greater scale — **and no GTT methods at all** |

Groww and Shoonya offer no per-instance HTTP object whatsoever, so their only lever is the
process-wide `HTTPS_PROXY` environment variable — which by definition cannot differ per account.
**Raw HTTP is not a preference; for three of the five it is the only option that works.**

**D-137 — At onboarding, every pre-existing holding is auto-excluded.** (Q-220 closed, option b.)
ATOM manages **only what ATOM bought**. On connecting an account, everything already held **at
that moment** is written to the exclusion list in one pass, so the first run cannot place a sell
order across positions the operator never intended to hand over.

> **Clarified by the operator:** anything ATOM subsequently **buys is sold by ATOM** — ATOM-bought
> positions are never excluded, and there is nothing to exclude on that side. The exclusion list
> holds only what pre-dated the connection (plus anything the operator adds by hand later).

> ⚠️ **Boundary with D-086, which must not be blurred.** D-086 says ATOM *never* auto-creates
> exclusions — unidentified quantity is reported and the operator decides. That still holds for
> **ongoing operation**. The auto-exclusion here is a **one-time onboarding snapshot**, scoped to
> the moment an account is connected.
>
> Implemented carelessly, "auto-exclude what ATOM did not buy" would run on every reconciliation
> and silently exclude every manual purchase forever — quietly stopping ATOM from selling
> holdings it should sell. **The rule is: auto-exclude once, at account connection. Never
> again.** Any unidentified quantity appearing afterwards is reported, per D-086.

**D-138 — Cost-of-capital accrual starts at the onboarding date.** (Q-221 closed.) No attempt is
made to reconstruct historical acquisition dates for pre-existing holdings. The operator's
reasoning: the accounts this runs on are expected to start empty, so there is no history worth
digging for. Combined with D-137 — pre-existing holdings are excluded and are not ATOM capital
anyway — nothing is left to accrue on.

**D-140 — Broker onboarding plan.** Eight verifiable stages per broker — commercials/T&C,
developer app, IP whitelisting, auth, read-only surface, order surface, GTT surface, money
surface — sequenced **Upstox → Dhan → Zerodha → Groww → Shoonya**.

Upstox is first because its read-only stage alone unblocks the universe job, ranking engine, NAV
gate and the whole paper-trading path — **before any other broker exists, before the static IPs
are registered and before any money is at risk**. Zerodha is third specifically because its
account has no data subscription, making it the first real exercise of the D-017 decoupling
(data from one broker, orders to another). Shoonya is last: REST-only GTT, unusable SDK,
thinnest documentation.

Architecture is **one `HttpCore` plus five thin adapters** — proxy, retries, rate limiting,
redaction and logging live in the core, so each adapter is only endpoints, payload mapping and
an error table, and broker #6 touches no application code.

*Commercial finding: a broker may be free for orders but charged for data. Since ATOM needs data
from only one broker (D-017), the rest can stay order-only — potentially one subscription
instead of five. Reported figures disagree across sources and must be confirmed per broker
(Q-224).*

Full plan in [`../03-brokers/BROKER-ONBOARDING-PLAN.md`](../03-brokers/BROKER-ONBOARDING-PLAN.md).

| Q-224 | Confirm API subscription cost per broker |
| Q-225 | Ship read-only stage for all five early as data fallback, or Upstox only? |

---

## Round 20 — 2026-09-23 · All five broker specifications written

**D-141 — Per-broker adapter specifications complete**, with endpoints extracted from SDK source
rather than inferred from prose, since the broker sites are egress-blocked. Documents:
[`UPSTOX.md`](../03-brokers/UPSTOX.md) · [`DHAN.md`](../03-brokers/DHAN.md) ·
[`ZERODHA.md`](../03-brokers/ZERODHA.md) · [`GROWW.md`](../03-brokers/GROWW.md) ·
[`SHOONYA.md`](../03-brokers/SHOONYA.md), consolidated in the capability matrix.

### Findings that change the build

**Two brokers can verify their own egress IP.** Upstox `/v2/user/ip` and Dhan `/ip/getIP` return
the address a request arrived from. This converts the hardest infrastructure assumption (D-005,
per-investor static IP) from something we hope works into a **startup health check and a test**.
Build it with the first adapter.

**Dhan exposes IP whitelisting as an API** — `/ip/getIP`, `/ip/setIP`, `/ip/modifyIP`. D-007
assumed manual registration everywhere. Recommendation stands that **writing** stays manual and
operator-initiated; reading is a health check.

**Charge visibility is uneven, and it shapes reporting.** Upstox (`/v2/charges/brokerage`,
`/trade/profit-loss/charges`) and Zerodha (`/charges/orders`) expose charges directly; Dhan
exposes a dated `/ledger`; **Groww and Shoonya appear to expose neither.** So D-024's
computed-vs-reported contrast is genuinely two-sided for three brokers and **computed-only for
two**, with manual statement upload as the fallback.

**Dhan's quote API at 1 request/second** is the sharpest limit across all five — a 60-ETF
universe would take a minute per account. Dhan must never be the data source, reinforcing D-017
and D-058i.

**Groww's GTT exists as SDK constants with no methods; Shoonya's is absent entirely.** Both have
it in REST. Since ATOM is raw-HTTP this is not blocking, but Shoonya's exact GTT endpoint,
payload and alert-type enum (`LTP_A_O` style) is now **the largest single unknown in the broker
layer** and must be resolved before Phase E (Q-237).

| Q-229 | Dhan `/ip/getIP` as health check, `setIP` manual? |
| Q-233 | 🔴 Groww GTT endpoint and payload from REST docs |
| Q-237 | 🔴 Shoonya GTT endpoint, payload and alert-type enum |
| Q-234, Q-238 | Do Groww and Shoonya expose any ledger or charges API? |
| Q-231, Q-232 | Zerodha per-key rate limits across accounts; order-only tier? |
| Q-226, Q-227 | Upstox analytics token for data; `/v2/user/ip` as health check |

**D-142 — GTT is a declared per-broker capability, with a DAY-limit fallback.**
Each adapter exposes `supports_gtt`. Where true, the cancel-all-then-replace GTT cycle of D-063
runs. Where false — Shoonya today, possibly Groww — ATOM places **plain DAY limit sells**, which
the broker cancels around 16:15; the next run finds an empty book and places fresh ones.

> ⚠️ **The non-run-day exposure that D-063 was created to eliminate returns, for these brokers
> only.** A DAY order dies at 16:15, so a position at a non-GTT broker is unprotected on any day
> the engine is not run. **Those accounts require a daily run**, and the console must say so
> against them rather than leaving it implicit.

*The strategy code branches on the capability flag, never on a broker name — which is what keeps
onboarding broker #6 a configuration change rather than a code change.*

**D-143 — Egress IP verification is an internal script, not a broker dependency.**
`scripts/verify_egress_ip.py` calls an independent IP-echo service **through each account's
proxy** and asserts the observed address equals that investor's expected Elastic IP.

Chosen over the broker endpoints (Upstox `/v2/user/ip`, Dhan `/ip/getIP`) because those cover
only two of five brokers and would tie the check to broker availability and a valid token. The
internal script needs neither and covers every account identically.

It also catches a failure the per-account assertion alone would miss: **if two accounts report
the same address, egress isolation is not working**, even when each address matches what was
configured. The script flags shared addresses explicitly.

Runs at engine startup before any order is placed, after any change to proxies, ENIs or Elastic
IPs, and in CI against staging. **Fails closed** — a non-zero exit means no trading.

*The two broker endpoints remain useful as a secondary confirmation, since they prove the path
end to end as the broker sees it. Belt and braces, not a substitute.*

---

## Round 21 — 2026-09-24 · Prior-art review

Four existing MetaAlgo repositories reviewed. **This is a working production system for the same
strategy**, and it answers open questions, validates decisions, and contradicts one.
Full analysis in
[`../11-prior-art/EXISTING-SYSTEM-ANALYSIS.md`](../11-prior-art/EXISTING-SYSTEM-ANALYSIS.md).

### 🔴 Q-242 — rotate the exposed Upstox credentials

`Token_gen/token_gen.py` has **hardcoded Upstox `client_id`, `api_key` and `api_secret`
committed to git**, with the access token written to a plain `.txt` file. The repository is
private, which limits but does not remove the exposure — history rewriting cannot recall clones
already taken. **Rotate the key and secret**; that is the fix, not deletion. Exactly the failure
mode D-079 exists to prevent.

### 🟢 D-055h WITHDRAWN — the domain switch is solved and running

`metaalgo-cloudflare` is a deployed Worker doing EC2-first with a **3-second timeout** and
automatic **Vercel failover** on timeout, error or 5xx. It beats all three options D-055h
proposed to build and measure: the switch is **per-request rather than DNS-TTL**, **automatic
rather than triggered**, and it protects the origin with an `X-Custom-Auth-Key` header matched
by an **Nginx map on EC2**. A grey-cloud subdomain avoids Cloudflare Error 1003.

*Consequences: the static site is on **Vercel**, not Render (D-018 corrected), and **Nginx is
already on the EC2 box**.*

**D-144 — Evaluate the existing Nginx for the per-account forward proxy** (D-005) before
introducing squid. It is already deployed, already configured, and already trusted by the
Worker.

**D-145 — Use the existing Selenium/Chrome NSE downloader** for the weekly universe job. NSE
fingerprints scripted clients and returns 403, but cannot distinguish a real browser — which is
precisely what blocked `fetch_etf_reference_data.py`. Chromium and Playwright are available in
the target environment. Broker CDN instrument masters remain preferred where they suffice
(D-114); this is for the NSE ETF table specifically.

### ⚠️ ATOM will not reproduce the existing bot's picks

The live system ranks on **absolute rupee difference** (`current − mean`, sorted ascending,
top 5). ATOM ranks on **percentage** (D-026, decided via Q-051) because rupee ranking
systematically favours expensive ETFs.

**This is intended, but it should be expected rather than discovered.** The first parallel run
will surface different candidates — that is the change working. Worth validating against history
before going live, and a good first use of the deferred backtest harness (V2-1).

*Confirmed parameters in the live system: ₹10,000 per trade, top-5 shortlist per category, three
categories driven by manual CSV ticker lists.*

### Directly reusable
Cloudflare Worker · Nginx auth-key map · Selenium NSE downloader · Upstox OAuth flow and
endpoints (including **trade charges**) · Telegram messaging · the cancel-resting-LIMIT-SELL
logic, which already has D-063's shape · the Vercel site's brand (dark navy `#0a0f1c`, cyan
`#06b6d4`, Inter, Tailwind) for the design system.

| Q-242 | 🔴 Rotate the exposed Upstox API key and secret |
| Q-243 | Is local-only `metaalgo_capital` materially different from `metaalgo_backup`? |
| Q-244 | Reuse the Cloudflare Worker as-is, or redeploy under ATOM? |
| Q-245 | Keep `metaalgocapital.com` and its brand for ATOM? |

---

## Round 22 — 2026-09-24

**D-146 — The prior system is archived reference material only.** Correcting the round-21
characterisation: it is **not live and has not run for about six months**. It was shut down for
falling short on reporting, trading and more, and parts of its infrastructure are likely already
cleaned up. **ATOM is built from scratch.** Nothing is copied or mimicked; the value taken
forward is the problems it surfaced, not its code.

**D-147 — Everything is provisioned fresh.** New AWS account, new EC2, new Elastic IPs, new
Telegram bot, new chats, new tokens, new Supabase. No resource is inherited from the archive.
*(This also retires Q-244 — the Cloudflare Worker is a design reference, not an artefact to
reuse.)*

**D-148 — The domain is `metaalgocapital.com`.** (Q-245 closed.)

**D-149 — Deviation is measured in percentage, confirmed after analysis.** (D-026 upheld.)

Measured across 127 liquid ETFs at real prices: **price dispersion within a single category
reaches 83×** (INDEX: ₹9.35 to ₹773.40), and 89× across the universe. That is what makes the
metric consequential.

Worked scenario, real symbols and prices: rupee ranking buys **JUNIORBEES, down 1.0%**, while
percentage ranking buys **NIFTYCASE, down 18.0%**. The two orderings are almost exactly
inverted. On the same ₹10,000, a recovery to the mean returns **₹94 versus ₹2,171 — 23×**.

Rupee ranking fails because **it ranks price level, not cheapness**: the rupee gap scales with
price, so at 83× dispersion it approximates "always buy the most expensive ETF in the category".
Two further inconsistencies: the **exit target is already a percentage** (3.5%, not ₹3.50), so
ranking in rupees while exiting in percent measures different things at each end; and **order
size is fixed in rupees so quantity adjusts** — ₹10,000 buys 12 units of a ₹773 ETF or 1,058 of
a ₹9.35 one — meaning per-unit rupee gap is not a quantity the portfolio ever experiences.

Full analysis in
[`../04-strategy/DEVIATION-METRIC-ANALYSIS.md`](../04-strategy/DEVIATION-METRIC-ANALYSIS.md).

| Q-246 | Percentage ranking is noisier on sub-rupee ETFs (one tick on a ₹9.35 ETF is 0.107%). The volume filter and corporate-action peer check already mitigate; watch in early live running |

---

## Round 23 — 2026-09-24 · Database schema

**D-150 — Database schema v1 designed.** PostgreSQL on Supabase, schema `atom`, third normal
form with two documented exceptions, surrogate keys throughout, nothing derivable stored.
Full DDL in [`../05-data/DATABASE-SCHEMA.md`](../05-data/DATABASE-SCHEMA.md).

**Eight invariants are enforced by database constraints rather than convention**, which is the
design's main defence against the 150 decisions drifting during the build:

| Invariant | Mechanism | From |
|---|---|---|
| A LIVE account cannot exist without an egress IP **and** a proxy | CHECK constraint | D-136 |
| Capital buckets sum to principal, every day | CHECK constraint | D-080 |
| One execute run per account/universe/day | partial unique index | D-057e |
| An order can never be sent twice | UNIQUE idempotency key | D-094 |
| Relationship must be inside SEBI's family definition | CHECK constraint | D-092 |
| A full PAN cannot be stored | CHECK regex on the masked form | D-128 |
| Paper and live books never mix | `execution_mode` on the account, inherited via FK | D-041 |

*`execution_mode` sitting on `trading_account` rather than on every table is what gives D-041's
isolation for free: a paper account and a live account are different rows, and every child
inherits the mode through its foreign key.*

**D-151 — 🆕 Trading universe is a first-class entity.**

> "There should be a trading-universe concept which has these securities, and at individual level
> you can run the model on one of the universes — or multiple, so you can compare which universe
> is working best."

This generalises what was a fixed ETF list. **The weekly volume-filtered ETF list becomes one
universe among several**, produced by a generator (`source = VOLUME_FILTER`) rather than being
the only thing the engine can trade. Manual universes (`source = MANUAL`) are built by searching
the instrument master by ISIN or name and ticking members.

- `universe` · `universe_member` · `universe_snapshot` · `universe_snapshot_member`
- **Universe-level freeze is distinct from holdings-level freeze (D-062):** freezing a *member*
  means "don't consider it for new buys"; freezing a *holding* means "don't sell what I own".
  A frozen member keeps its row, history and add-date, so unfreezing next quarter restores it
  exactly — which is why freeze exists rather than delete-and-re-add.
- `instrument` carries `country` and `currency`, so a future US or other-market universe is a
  data change, not a migration.
- Every run records `universe_id` **and** `snapshot_id`, so a past decision replays against the
  universe as it stood then.

**D-152 — Broker instrument identifiers are resolved once, in `broker_instrument`.** Each broker
names the same security differently (`NSE_EQ|INE002A01018`, a numeric security id, an instrument
token). Resolution happens in one table and the strategy engine only ever sees `instrument_id`.
This is a large part of why five adapters stay tractable.

### Open questions from the schema — Q-247 … Q-256

The universe concept raises real design questions that the schema has deliberately left open
rather than guessing at. Listed in the reply; all need answers before the schema is frozen.
