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
| Q-051 | Percentage vs rupee deviation — deferred, needs to be re-asked with a clearer worked example |
| Q-043 | "1 lakh" volume threshold — operator points to NSE's own published data using 100000; verify what NSE actually publishes and re-confirm units |
| Q-137 | Reconciliation of buys that fill while the engine is down |
| Q-138 | Confirm raw logs are excluded from Supabase while structured records are retained |
| Q-139 | Cost of Secrets Manager vs encrypted Supabase storage, to settle D-013 |
| Q-140 | Feasibility and reliability of the domain auto-switch mechanism (D-018) |
