# ATOM — Requirements As Captured (Round 1)

**Status:** Draft for review — *verbatim capture, not design*
**Date:** 2026-09-16
**Source:** Founder briefing (voice transcript), Session 1

> **Purpose of this document.** This is a faithful, structured restatement of the product
> brief exactly as it was given. It contains **no design decisions and no assumptions**.
> Where the brief was silent, contradictory, or open to more than one reading, the text
> below says so explicitly and points at a question ID in
> [`OPEN-QUESTIONS.md`](./OPEN-QUESTIONS.md) — e.g. `[→ Q-042]`.
>
> **This document is the contract.** Every later design document must trace back to a
> requirement here. If a design document asserts something that is not in here and not
> answered in the question bank, it is an unauthorised assumption and must be removed.

---

## 1. Product in one paragraph

ATOM is a multi-broker, multi-account automated equity/ETF trading system for the Indian
market, built on a **mean-reversion** thesis over Exchange Traded Funds. A human operator
starts the compute engine on demand via a Telegram bot, logs into a web console, supplies
the day's broker API tokens, and triggers an execution run. The engine ranks the tradable
ETF universe by deviation from its own mean, buys the most oversold candidate in each
enabled category, and immediately places a matching limit sell order at a configured
profit percentage. The system also supports manual position averaging, human-approved
tax-loss harvesting with correlation-matched proxy ETFs, exhaustive logging, and
month-on-month financial reporting net of Indian brokerage, depository and statutory
charges. Compute runs on an on-demand AWS EC2 instance carrying one dedicated Elastic IP
per trading account, as required for broker API access under current SEBI rules.

---

## 2. Actors and accounts

| Actor | Description |
|---|---|
| **Operator / Admin** | 2–3 people who log into the web console, authenticate tokens, and trigger runs. Runs trades on behalf of all onboarded accounts. |
| **Investor / Account holder** | A person whose broker account(s) are traded. Today: Person A and Person B. |
| **Broker** | An Indian stock broker whose API the engine calls to place orders and read data. |

### 2.1 Day-one account matrix

| Investor | Broker | Notes |
|---|---|---|
| Person A | Upstox | |
| Person A | Dhan | Same investor, second broker |
| Person B | Dhan | More brokers may be added later |

**Stated rule:** one investor may hold accounts at multiple brokers; the console must show
per-broker screens for that investor *and* a consolidated cross-broker view.

### 2.2 Broker support roadmap

Five brokers must be supported by design: **Groww, Zerodha, Dhan, Upstox, Shoonya**.
Anyone holding an account at any of these five must be able to connect to the utility and
have trades placed in their account by our logic. Onboarding a *new* broker must be
achievable by adding a broker adapter + documentation, **without touching application
logic**. `[→ Q-020]` `[→ Q-021]`

---

## 3. Infrastructure requirements (as stated)

1. Compute is hosted on **AWS EC2**, run on an **invocation basis**: the instance is
   started, performs the computation, places trades, and is then shut down to control cost.
2. A **AWS Lambda** function is the trigger that starts the EC2 instance.
3. A **Telegram bot** is the human entry point: the operator sends a command (e.g. `start`
   / a menu action), the bot invokes the Lambda, the Lambda starts EC2, and roughly
   **5 seconds later** the bot replies with a status message confirming whether EC2 is up
   and running. `[→ Q-030]`
4. A `stop` / bring-down command shuts the EC2 instance back down to save cost.
5. **Static IP requirement (SEBI):** per current SEBI rules, each account requires a
   **static IP** for calls to the broker to place trades or execute instructions.
   - **One static IP per investor**, not per broker. Person A's static IP is registered
     with *both* Upstox and Dhan; every call for Person A's accounts must egress from that
     one IP. Person B gets a second static IP used for all of their calls.
   - The static IPs are attached to the EC2 instance. `[→ Q-010]` `[→ Q-011]`
6. **Instance sizing analysis is required:** determine which EC2 instance types support
   how many secondary IPs / Elastic IPs, and at what cost on Indian (ap-south-1) pricing.
7. **Scale-out design decision required:** when the system grows to e.g. 5 clients, decide
   between one larger instance carrying 5 static IPs versus splitting across multiple EC2
   instances (e.g. 3 IPs + 2 IPs) on cost grounds. Document the analysis. `[→ Q-012]`
8. Calls to **Supabase do not require** the static IP and may use the generic egress path.
9. The system must remain scalable: the code must not hard-code two accounts.

### 3.1 Web hosting

- The public website is a **static company web page** that is up **all the time**,
  independent of EC2.
- Hosting on **Render** (Vercel named as an alternative) on a free tier. A **domain is
  already owned** and must be attached. `[→ Q-060]`
- **Auto-switching behaviour:** when the engine (EC2) is down, visitors see only the static
  site. When the operator starts the engine via Telegram, a **Login option appears** on the
  same website. When the engine is brought down, the login button disappears again.
  `[→ Q-061]` `[→ Q-062]`

---

## 4. Tech stack (as stated)

| Layer | Choice |
|---|---|
| Web hosting | Render (Vercel as alternative) |
| Backend / computation | **Python** |
| UI | Node.js "or anyone at whatever you want" — i.e. **unconstrained**, operator preference `[→ Q-063]` |
| Data storage | **Supabase** (dedicated schema + tables) |
| Authentication | Free service — Firebase, Supabase Auth, email-based, Google, GitHub — to be chosen `[→ Q-070]` |
| Compute host | AWS EC2 (on-demand) + AWS Lambda (trigger) |
| Chat interface | Telegram bot |
| Log archive | Google Drive (append-only archive) + S3 (rolling 4-week retention) |

### 4.1 Non-functional requirements stated

- The website must be **very smooth, with no lag**.
- The code must be **completely modular** — many small scripts, wrappers, modules and
  functions rather than large scripts, so that a broker changing its API or Python SDK
  requires changes only in that broker's adapter, never in the application.
- The theme must be **navy blue**, professional, in the style of a financial website.

---

## 5. ETF universe

### 5.1 Categories

Exactly three buckets, each traded independently:

1. **Equity ETFs** — pure equity.
2. **Metals ETFs** — gold, silver and others.
3. **Global ETFs** — foreign/international ETFs listed on NSE.

`[→ Q-040]` (classification rules and edge cases: debt/liquid ETFs, smart-beta, silver+gold
combos, sectoral vs broad equity)

### 5.2 Universe construction (weekly batch job)

- Fetch **all actively traded ETFs on Indian exchanges** and bucket them into the three
  categories above. `[→ Q-041]`
- A **weekly job** computes, for every ETF, the volume over the **past 25 working days**
  and the **past 60 working days**, then sorts the list in **descending** order.
  `[→ Q-042]` (what exactly is compared/sorted — average daily volume, total, or both
  windows; and how the two windows combine)
- ETFs with volume **greater than 1 lakh (100,000)** qualify for the **trading universe**;
  those below do not. `[→ Q-043]` (traded quantity vs traded value; which window the
  threshold applies to)
- The threshold **must be config-driven**: lowering it (e.g. to 60,000) in a bear market
  widens the universe across all three categories; raising it (e.g. 1.5 lakh or 2 lakh)
  shrinks it for liquidity reasons.
- The job runs **every Saturday** and produces the tradable universe for the coming week.
  During that week, **only** securities in that computed list are considered, per category.
- The job must run **automatically**, but the web console must expose a **Jobs** page with
  a manual **Run** button for ad-hoc execution, and the result must be stored.

### 5.3 ETF master data

- A **master table of all available ETFs** must exist.
- The console must offer a **search screen** where an operator types an ETF name and sees
  whether it exists in the database.
- If a newly launched ETF is missing, the operator can click **Add** and supply the
  **ETF name, ticker, ISIN** (and other identifiers). From then on the system connects to
  **Upstox for data**, begins pulling history for it, and it enters the normal pipeline.
  `[→ Q-044]` (Upstox named as the market-data source — is it the sole data source for all
  accounts, including those with no Upstox account?)
- A brand-new ETF will not qualify for the universe until it has history/volume.

---

## 6. Buy logic

### 6.1 Ranking

1. For each ETF in the category's tradable universe, compute the **average price over a
   configured lookback period** (examples given: 25, 50 or 60 days). The period **must be
   fully config-driven**, and configurable **per account and per category** — e.g. Person A
   equity = 20 days, Person A metals = 35 days, Person B global = 90 days, Person B
   equity = 5 days. This config lives on the Execute Engine screen.
2. Compute **both the mean and the median** and compare the price differences. `[→ Q-050]`
   (which of the two drives the actual ranking and order decision?)
3. Subtract today's price from the average to get the **deviation**, and rank all ETFs in
   the category by that deviation.
4. **All price inputs are the one-day closing price** of the security.
   `[→ Q-051]` (if closing prices drive the calculation, which close is "today's price"
   during a live 09:30+ run — previous close, or live LTP?)

### 6.2 Selection

- Buy the ETF that is **most negatively deviated** (e.g. average 100, today 75 — the
  largest historical deviation below its mean).
- **One security per category per day**, maximum.
- **Holdings skip rule with a depth config:** if the most deviated ETF is already held in
  the portfolio, skip it and consider the second most deviated; if that is also held,
  consider the third; and so on, up to a **configured depth level**.
  - Depth is a per-account (and per-category) config. Examples given: 3 for equity, 5 for
    metals, and `1/1/1` meaning "only ever buy the single most deviated, and if it is
    already held, buy nothing".
  - If every candidate within the configured depth is already held, **place no buy order**
    for that category that day.

### 6.3 Category ordering and funds

- The operator must be able to define the **order in which categories are bought** —
  e.g. equity, then global, then metals.
- **Rationale given:** with a ₹10,000 per-order size and only ₹20,000 of funds, the first
  two categories in the order get filled and the third is skipped. Changing the order to
  metals → equity → global with ₹10,000 available means only metals is bought.
- **Available funds must be checked before placing each buy order.** `[→ Q-052]`
  (behaviour when funds are partially sufficient — e.g. ₹7,000 free against a ₹10,000
  order size: skip, or buy fewer units?)

### 6.4 Order sizing

- A **per-category rupee amount per trade**, configurable per account. Example given:
  equity ₹10,000, global ₹20,000, metals ₹5,000.
- `[→ Q-053]` (how quantity is derived from a rupee amount — floor of amount/price;
  handling when one unit costs more than the configured amount)

### 6.5 Category enable/disable

- Each category can be **disabled** for a run — e.g. "today I only want equity", so global
  and metals are switched off.
- **Sell orders are always placed regardless of the enable/disable flag.** The flag only
  suppresses **buying** in that category.

---

## 7. Sell logic

- As soon as a **buy order is completed (fulfilled)**, the system automatically places a
  **limit sell order** at a **configured profit percentage** above the buy price.
- The percentage is configurable **per category and per investor**. Example given:
  equity 3.5%, metals 5%, global 2%.
- Example: buy fills, push a limit sell at buy price + 3.5%; if it executes, 3.5% is booked.
- `[→ Q-054]` (is the target computed on raw traded price or on cost including charges?
  tick-size rounding rule? order validity — DAY vs GTT/GTC, given the engine is off most
  of the time?)

### 7.1 Sell orders at the start of a run

On each execution run, **before** the buy loop:

1. Take the current **holdings**.
2. Determine the required profit percentage per holding.
3. **Push all limit sell orders to the exchange.**
4. Only then enter the buy loop (compute averages → rank → check holdings → place trades).

`[→ Q-055]` (how to avoid duplicating a sell order that is already resting at the broker
from a previous day — matching, cancel-and-replace, or skip?)

### 7.2 Pre-conditions for a run

The stated trigger conditions are: the **token has been provided**, and the **market is
up / time is past 09:30**. `[→ Q-056]` (is 09:30 a hard gate, a config, and what is the
latest permissible run time?)

---

## 8. Averaging (the "Average" screen)

- Compute the **P&L of every holding in the portfolio** and report which positions are at
  a loss, bucketed by severity — examples given: **≤5% loss** (bought 100, now 95) and
  **10% loss**.
- Provide a **one-click "Average" button** per position that buys a further **configured
  rupee amount** (example: ₹10,000) of that security.
- **Use case given:** the depth config is 3 and all three equity candidates are already
  held, so the normal route places no buy; but the operator still wants equity exposure,
  so they open the Average screen, see a holding down 12%, and click buy.
- **Mandatory consequence — sell order refresh:** after an averaging buy, the **previous
  resting sell order must be cancelled** and a **new sell order placed** computed from the
  **new weighted-average buy price** plus that category's configured percentage.
  - Worked example: ₹10,000 held at a 12% loss + ₹10,000 averaged = ₹20,000 position with a
    lower average price; the old sell order is void and must be replaced.
- The Average screen must **first show the trades made in the current run at the top**,
  per category: e.g. "Equity — enabled — <trade>", "Global — enabled — no trade". If no
  trade happened, it must say so, and the operator can cross-check on the Daily Status
  screen that all candidates were already held.
- The screen must also show **available funds**.
- `[→ Q-057]` (are the loss buckets — 5%, 10% — fixed or configurable? is averaging depth
  limited, i.e. can the same position be averaged repeatedly?)

---

## 9. Tax-loss harvesting

The system runs purely on **short-term** gains and short-term trades, so an end-to-end
tax-loss harvesting capability is required.

### 9.1 Tax computation

- On opening the Tax Harvesting screen, **compute or pull tax data** — from the broker if
  the broker provides it, otherwise from our own trades data.
- Apply **20% as the current short-term capital gains rate** and show the resulting
  **tax liability**. `[→ Q-080]` (is 20% a hard-coded constant or config? are surcharge and
  cess included? is the STCG rate applied per financial year with set-off carry rules?)
- Example given: ₹5,000 of realised gain in recent days ⇒ potential tax payable ₹1,000.

### 9.2 The harvesting mechanic

1. The screen shows **realised profits to date** alongside **current loss-making positions**.
2. The goal: realised gains are sitting in the account and need a **set-off**.
3. **Sell the position with the largest loss**, and **simultaneously buy a proxy ETF** —
   a *different* ETF with the same sector/asset exposure — **on the very same day**, so
   sector exposure is unchanged but the loss is booked.
4. Worked example given: an auto-sector ETF bought for ₹10,000 is now ₹9,000. Sell it,
   take the ₹9,000, buy a **different auto-sector ETF** with it. Sector exposure is intact,
   a ₹1,000 loss is booked against the gains, reducing tax liability.
5. **Carry-over of the sell target:** the newly bought ₹9,000 proxy position carries the
   **original ₹10,000 cost basis** for exit purposes — the sell order is placed at
   **₹10,000 + the configured percentage** (3.5% / 5% / whatever the user set), i.e. the
   proxy must reach ₹10,350 before it is sold. The net effect: no real loss on the auto
   position, but a ₹1,000 booked loss offsetting taxable gains. `[→ Q-081]` (confirm this
   cost-basis carry-over rule and how it is stored/tracked in the database)

### 9.3 Proxy selection by correlation

- The proxy ETF must be **as close as possible** to the ETF being sold — the two must move
  very closely together.
- A **database of correlations between sectoral ETFs** is required.
- When the operator clicks **"Propose tax harvest"**, the system must **compute the
  correlation of each sectoral ETF against every other**, build the list, and then find
  harvesting opportunities.
- **Correlation window: at least 180 days, or 250 days**, to get a reliable picture.
  `[→ Q-082]` (daily log returns vs price levels? Pearson? minimum correlation threshold to
  allow a swap?)
- **Ranking example given:** if auto's best proxy has correlation 0.90 but healthcare —
  also at a loss — has a proxy at 0.95, harvesting healthcare is preferred, because the
  tracking error is lower.
- **End goal stated:** "if I'm selling a security I should get a perfectly equivalent proxy
  entry, and the selling price of that would be the actual price which I bought."

### 9.4 Human approval

- Tax-loss trades **execute only on human approval**.
- The screen shows: current gain (e.g. ₹3,000 for the last month), the loss-making
  positions that could be sold, and the proxy positions that would be entered.
- The operator clicks **Harvest / Execute** and the full sell + proxy-buy transaction runs.
- `[→ Q-083]` (what happens if the sell fills but the proxy buy fails — is this an atomic
  operation with rollback, or best-effort with alerting?)

---

## 10. Order lifecycle and reconciliation

- A buy order may be placed and **not get executed**.
- The system must keep an **active track of whether each order has executed**, **polling
  every one minute**.
- The same applies to **sell orders**.
- `[→ Q-090]` (polling runs only while EC2 is up — what happens to pending orders after
  shutdown? is there an end-of-run cancel policy for unfilled buys?)
- Downstream dependency: the automatic sell order is created **only when the buy is
  fulfilled**, so the sell placement depends on this polling loop.

---

## 11. Web console — screen by screen

The console is described as "a quant shop website" operated by one or few people.

### Screen 1 — Accounts / Home
- Complete details of **each individual account** (two today, growing).
- Each account needs a **daily token** to authenticate broker APIs before trading. The
  screen provides a place for the operator to **generate/obtain and paste the token**,
  activating that account's API calls for the day.
- Once authenticated, show per account:
  - **Funds available**
  - **Total gains**
  - **Active (unrealised) gains**
  - **Realised gains**
  - **Tax values** — e.g. "gain ₹5,000 to date with no harvesting done ⇒ potential tax
    payable = 20% of ₹5,000 = ₹1,000"

### Screen 2 — Execute Engine
- Holds the **configs** for both/all accounts:
  - profit percentage per category per account
  - number of **levels / depth** per category (2, 3, 5 …)
  - **rupee amount per trade** per category
  - **lookback period in days** per account per category
  - **category buy order/priority**
  - **category enable/disable toggles**
- An **Execute / Trade** button which: fetches prices → computes the ETF list → computes
  deviations → **places sell orders first** → then places buy orders.

### Screen 3 — Tax-Loss Harvesting
- Per account: show the tax position; **Propose tax harvesting** computes proxies and
  correlations and presents options; the operator taps **Harvest/Execute** to run the
  sell + proxy buy.

### Screen 4 — Daily Status
- Per account, **three lists** — equity, global, metals.
- Each list shows the **top ~7 securities in descending deviation order**
  (with a stated requirement elsewhere to "show 10 securities status for each account"
  `[→ Q-064]` — reconcile 7 vs 10).
- Each row carries a **status**: `HELD` (already in portfolio), `BOUGHT` (purchased in
  today's run), or **blank** (evaluated, not acted on).
- Rows **below the configured depth** are shown **greyed out / not highlighted**.
- Worked example given: equity depth 3 — #1 shows `HELD`, #2 shows `BOUGHT`, #3 blank,
  rest greyed. Metals depth 5 — #1/#2/#3 show `HELD`, #4 shows `BOUGHT`, #5 blank, the
  remaining greyed.
- Must be viewable **for a number of days** (history), not just today. `[→ Q-065]`

### Screen 5 — Average
- Top section: the trades made in the current run, per category, with enabled/disabled
  state and "no trade" where applicable.
- Funds available.
- Loss-making holdings with their loss percentages, each with an **Average** action that
  buys the configured amount and **replaces the resting sell order** at the new average
  price + configured percentage.

### Screen 6 — Reports
An **extensive** month-on-month financial reporting module. See §12.

### Screen 7 — Jobs
- Page for the **weekly volume/universe job**: runs automatically, with a manual **Run**
  button for ad-hoc execution, and stores its output.

### Screen 8 — ETF Master / Search
- Search for an ETF by name; see whether it is in the database; **Add** a new ETF by name,
  ticker and ISIN, after which data pulling begins.

### Cross-cutting UI requirements
- **Login page** — unique ID + password, and/or Google, email or GitHub authentication, via
  a free service (Firebase / Supabase Auth / email-based). 2–3 users total.
- **Download logs** button after buying/selling completes — produces a `.txt` file.
- Navigation bar covering the above screens.
- Navy blue, professional financial theme.
- Detailed operational documentation is required **per screen**: what it does, what it does
  not do, how it interacts, which APIs it calls and how the broker wrapper is invoked.

---

## 12. Reporting

- **Month-on-month, end-to-end financials**, per **account** and per **broker**, plus a
  **consolidated view** per investor summing across their brokers.
- Must account for **Indian market cost structure**: depository charges, brokerage, and
  other government/statutory charges.
- **Core difficulty stated:** every broker returns this information differently — different
  APIs, different P&L shapes. Some brokers put DP/other charges **inside the P&L**; others
  expose them only in the **ledger** (funds added/withdrawn). The system must consume all
  of these and produce a **unified** model.
- Per broker, the user must see: **P&L, tax optimisation, and cost/charges**.
- Consolidated across brokers for the investor level.
- **A thorough research exercise is explicitly requested** to determine a unified approach.
  `[→ Q-100]` … `[→ Q-104]`
- Reports must be **downloadable as CSV**, and support further analysis.

---

## 13. Logging and archival

- **Everything** in a buy/sell run must be logged.
- Logs are written to **Google Drive** *and* to **S3**.
  - **S3:** cleared on a **rolling basis every month** — i.e. roughly four weeks of active
    runs retained.
  - **Google Drive:** **append-only archive**, never cleared.
  - `[→ Q-110]` (the brief says "your local S3" — clarify whether this means S3 proper,
    local disk on EC2, or both)
- **Telegram delivery:** log files are pushed to a Telegram chat/channel.
  - **One log file per account per broker.** Stated example: triggering two brokers for one
    account and one broker for another account ⇒ **three files** sent to the log channel.
- The operator can download logs from the web page **or** from Telegram.
- **Log content requirement — a reader must be able to reconstruct the entire run from the
  log alone**, including:
  - process start time and date
  - the configs in force for the run
  - the viable/tradable universe used
  - computed averages
  - the ranked ETFs (top 3 / top 5 per the depth config)
  - what was computed, in what order, and why
  - which securities were held vs bought vs skipped, and if nothing was bought, why
  - lack-of-funds situations that prevented a trade
  - every order sent and every response received

---

## 14. Database (Supabase)

- Supabase is the system of record, with **specific schemas and tables**.
- **No data may be lost.** Full **traceability** is required: an operator must be able to
  query the tables and determine **what trade was made, why it was made, and what sell was
  made** — end-to-end, reconstructible from the database.
- Tables are also required for **onboarding new users and brokers**.
- "Do very detailed work on the database" — schema, APIs and data flow must be designed in
  depth. `[→ Q-120]` … `[→ Q-129]`

---

## 15. Explicit process instructions for this engagement

1. **Design first.** Complete end-to-end system design, extensive documentation and
   flowcharts, then **review**. Only after review does implementation begin.
2. **Break the problem into small chunks** — roughly **20–25 documents** covering infra,
   website, trade mechanics, averaging, configs and how configs change.
3. Documentation lives in a `documentation` folder in the GitHub repo, split into
   sub-folders (modules, infra, etc.).
4. **Research each broker thoroughly**, using **current/latest documentation**; **save the
   raw vendor documentation** in the repo for reference.
5. **Ask as many questions as needed — even 100.** **Do not assume anything.** Stick to the
   guidance given.
6. Code must be **completely modular**: small scripts, per-broker utilities, wrappers and
   functions, so a broker API change is contained to that broker's module.
7. Push the documentation to GitHub.

---

## 16. Known contradictions and gaps in the brief

These are not criticisms — they are the points where the brief admits more than one reading
and a decision is required before design can proceed.

| # | Issue | Question |
|---|---|---|
| C-1 | Prices are stated as "one-day closing price", but the run is triggered intraday after 09:30 and buys at market/limit. Which price is "today's price"? | Q-051 |
| C-2 | Both **mean and median** are to be computed, but only one can rank the list. | Q-050 |
| C-3 | Daily Status says "top 6 or 7" in one place and "10 securities" in another. | Q-064 |
| C-4 | Sell orders are placed for all holdings at run start, but the engine is down most of the day — resting order validity (DAY vs GTT) is undefined. | Q-054, Q-055 |
| C-5 | Order fill polling is every 1 minute, but EC2 shuts down after the run. Fate of unfilled orders is undefined. | Q-090 |
| C-6 | Static IP is per **investor**, yet EC2 has one default route — per-account source-IP binding is an explicit engineering requirement, not a given. | Q-010, Q-011 |
| C-7 | Upstox is named as the market-data source, but Person B has no Upstox account. Data-source strategy for non-Upstox investors is undefined. | Q-044 |
| C-8 | Tax harvesting carries the **original** cost basis onto the proxy for exit pricing. This is a bookkeeping construct, not the broker's view of cost. Needs explicit modelling. | Q-081 |
| C-9 | "Local S3" — ambiguous between AWS S3 and on-instance storage. | Q-110 |
| C-10 | Login appears only when EC2 is up, but the site is statically hosted on Render — the liveness signal and its security model are undefined. | Q-061, Q-062 |

---

*Next document: [`OPEN-QUESTIONS.md`](./OPEN-QUESTIONS.md) — the full question bank that must
be answered before design documents are written.*
