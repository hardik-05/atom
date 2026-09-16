# ATOM — Open Questions (Question Bank v1)

**Status:** Awaiting answers — *design is blocked on the 🔴 items*
**Date:** 2026-09-16
**Companion to:** [`REQUIREMENTS-AS-CAPTURED.md`](./REQUIREMENTS-AS-CAPTURED.md)

---

## How to use this document

You asked me not to assume anything. So every point where the brief was silent or
ambiguous is listed below as a numbered question. There are **127**.

To keep this fast for you, **each question carries a proposed default** — the answer I
would pick if forced to choose, with the reasoning compressed to one line. You do not have
to answer 127 questions. You can:

- **Reply "defaults, except …"** and list only the ones you want changed, or
- answer only the 🔴 blockers and let the rest ride on defaults, or
- go through them in full if you want tight control.

Nothing marked *proposed default* has been written into any design document. It becomes a
requirement only when you confirm it.

**Priority legend**

| Mark | Meaning |
|---|---|
| 🔴 | **Blocker** — the architecture cannot be drawn without this answer |
| 🟠 | **Important** — changes a module's design, but design can start |
| 🟡 | **Detail** — can be settled during detailed design or first implementation |

**Answer tracking:** fill the `Answer:` line under each question, or reply in chat and I
will populate them and commit.

---

## A. Engagement, scope and sequencing

**Q-001** 🟠 **Delivery order.** After documentation is approved, which module should be
built first?
*Proposed default:* broker adapter layer + Supabase schema → universe job → execution
engine → web console → tax harvesting → reports. Tax harvesting and reports are the most
research-heavy and least urgent to trade.
`Answer:`

**Q-002** 🟠 **Go-live target.** Is there a date by which real money must trade through
this system? This decides how much is v1 vs deferred.
`Answer:`

**Q-003** 🟡 **Paper-trading mode.** Do you want a dry-run mode that does everything except
send the order to the broker, for validating the first few weeks?
*Proposed default:* Yes — a `DRY_RUN` flag per account, logged identically. Cheap to build,
and the only safe way to validate ranking logic against live data.
`Answer:`

**Q-004** 🟠 **Capital at risk on day one.** Rough per-account capital, so I can size order
counts, API rate-limit budgets and DB volumes realistically.
`Answer:`

**Q-005** 🟡 **Repository layout.** Single monorepo (`engine/`, `web/`, `infra/`, `docs/`)
or separate repos for engine and website?
*Proposed default:* Monorepo. Two operators, shared config contracts, simpler deploys.
`Answer:`

**Q-006** 🟡 **Docs folder name.** You said "documentation folder"; I have used `docs/`.
Rename to `documentation/`?
*Proposed default:* keep `docs/` — conventional and shorter. Trivial to rename.
`Answer:`

**Q-007** 🟡 **Diagram format.** Mermaid (renders natively in GitHub, diffable in git) or
exported images from draw.io?
*Proposed default:* Mermaid as the source of truth, with rendered PNGs committed alongside
for the ones that matter.
`Answer:`

**Q-008** 🟠 **Who else reads these docs?** Just you, or a co-founder / auditor / future
hire? Affects how much Indian-market context I spell out.
`Answer:`

**Q-009** 🟡 **Naming.** Is "ATOM" the product name (from the repo name), and is there a
brand/logo to match the navy-blue theme?
`Answer:`

---

## B. Infrastructure, networking and static IPs

**Q-010** 🔴 **Per-account source-IP binding — the core networking question.** One EC2
instance will hold two (later N) Elastic IPs, but Person A's calls *must* egress from
Person A's IP and Person B's from Person B's. A Linux box has one default route, so this
does not happen by itself. Which mechanism do you want?
- **(a)** Multiple ENIs, one Elastic IP each, with **source-based policy routing**
  (`ip rule` + per-IP routing tables) and Python sockets bound to a specific source IP.
- **(b)** One squid/HAProxy **forward proxy per IP** on the same box; the Python adapter
  picks the proxy by account. Simplest to verify and to prove to a broker.
- **(c)** One **container per account** with its own network namespace pinned to an IP.
- **(d)** One **EC2 instance per account** — trivially correct, most expensive.

*Proposed default:* **(b)**, with (a) underneath it. A local proxy per IP is the only
option where "which IP did this call leave from" is directly observable and unit-testable,
and it keeps the broker adapter code IP-agnostic — it just gets a proxy URL from config.
`Answer:`

**Q-011** 🔴 **Have the static IPs been procured and registered yet?** Each broker
(Upstox, Dhan) has its own process for whitelisting a static IP against an API app. Are
Person A's and Person B's IPs already allocated and registered, or is that part of this
project? Elastic IPs must never be released once registered — re-registration is manual.
`Answer:`

**Q-012** 🟠 **Scale-out policy.** You asked for an analysis of instance-size vs
Elastic-IP-count vs ap-south-1 cost. What is the planning horizon — 5 accounts, 20, 100?
*Proposed default:* design for 25 accounts, analyse cost curves at 2 / 5 / 10 / 25.
`Answer:`

**Q-013** 🟠 **EC2 uptime window.** Roughly how long is the instance up per trading day —
minutes (fire and forget) or hours (operator works through averaging and harvesting)?
This decides whether pending-order polling can be relied upon.
*Proposed default:* assume up to 60 minutes per session, operator-driven shutdown, with a
safety auto-shutdown.
`Answer:`

**Q-014** 🟠 **Auto-shutdown safety net.** If the operator forgets to stop the instance,
should it self-terminate after N idle minutes?
*Proposed default:* yes — auto-stop after 90 minutes of no console activity, with a
Telegram warning at 75 minutes.
`Answer:`

**Q-015** 🟡 **AWS region.** `ap-south-1` (Mumbai)?
*Proposed default:* yes — lowest latency to broker endpoints and correct for Indian data
residency expectations.
`Answer:`

**Q-016** 🟡 **AWS account.** Is there an existing AWS account with billing set up, and do
I assume a fresh VPC or an existing one?
`Answer:`

**Q-017** 🟠 **Instance storage and state.** When EC2 goes down, everything on it is gone
unless persisted. Confirm that **all** state lives in Supabase/S3 and the instance is
disposable (built from an AMI or a boot script).
*Proposed default:* fully disposable instance; code pulled from GitHub or baked into an AMI
at deploy time; zero local state beyond the current run's log file.
`Answer:`

**Q-018** 🟡 **Deployment mechanism to EC2.** Baked AMI, Docker image from ECR, or
`git pull` on boot?
*Proposed default:* Docker image on ECR — reproducible, and the per-account network
namespace option (Q-010c) stays open.
`Answer:`

**Q-019** 🟡 **Disaster recovery.** If the instance fails mid-run with orders placed but
sells not yet pushed, what is the expected recovery path?
*Proposed default:* every order is written to Supabase *before* it is sent to the broker,
so a restarted run reconciles from the DB and the broker order book rather than replaying.
`Answer:`

---

## C. Brokers

**Q-020** 🔴 **Which brokers are actually needed for v1 code**, versus designed-for but
not built? Building five live adapters is roughly five times the work and five times the
credential-management surface of building two.
*Proposed default:* **Upstox and Dhan fully built and tested**; Zerodha, Groww and Shoonya
specified in the adapter contract with documented stubs, built on demand.
`Answer:` **ALL FIVE brokers fully built and tested in v1** — Upstox, Dhan, Zerodha, Groww, Shoonya. *(Confirmed 2026-09-16.)* Consequence: live credentials and a funded, testable account are required for each of the five before that adapter can be validated — see Q-024, which is now a blocker.

**Q-021** 🟠 **Broker adapter contract.** Confirm the capability surface every broker
adapter must implement, so new brokers are pure configuration:
`authenticate`, `get_funds`, `get_holdings`, `get_positions`, `place_order`,
`modify_order`, `cancel_order`, `get_order_status`, `get_order_book`, `get_trade_book`,
`get_historical_candles`, `get_quote`, `get_ledger`, `get_charges`.
Anything to add or drop?
`Answer:`

**Q-022** 🔴 **Daily token flow.** You described pasting a token into the console each day.
For each broker this is actually different — most Indian brokers use a daily OAuth login
producing a `request_token` you exchange for an `access_token` valid until ~early next
morning. Do you want:
- **(a)** operator pastes the raw redirect URL / request token, engine does the exchange;
- **(b)** operator pastes the final access token obtained elsewhere;
- **(c)** console hosts the full OAuth redirect flow (needs a fixed redirect URI on the
  always-on website).

*Proposed default:* **(c)** where the broker allows it, falling back to **(a)**. Least
error-prone for a daily ritual, and the redirect URI can live on the always-on Render site.
`Answer:`

**Q-023** 🔴 **Token storage.** Access tokens are bearer credentials that can place trades.
Where do they live between the console and the engine?
*Proposed default:* encrypted at rest in Supabase (pgcrypto / app-level AES-GCM with a key
in AWS Secrets Manager), auto-expired at end of day, never written to logs.
`Answer:`

**Q-024** 🟠 **API credentials.** Do you already hold API keys/secrets for Upstox and Dhan,
and are they per-investor (Person A's own Upstox developer app) or one app used for all
accounts?
`Answer:`

**Q-025** 🟠 **Rate limits.** Each broker enforces different request-per-second and
per-day caps. Should the adapter layer include a shared token-bucket rate limiter per
broker per account?
*Proposed default:* yes, configured per broker from its documented limits, with backoff
and jitter.
`Answer:`

**Q-026** 🟡 **SDK vs raw HTTP.** Use each broker's official Python SDK where it exists, or
implement raw HTTP against the documented REST API?
*Proposed default:* **raw HTTP with `httpx`**, because SDKs vary wildly in quality and,
critically, most do not let you bind a source IP or route through a per-account proxy —
which Q-010 requires. Vendor SDKs get used only as a reference.
`Answer:`

**Q-027** 🟠 **Order types.** Confirm: buys are **MARKET** orders and sells are **LIMIT**
orders at the profit target? Or should buys also be limit orders at/near LTP?
*Proposed default:* buys as **LIMIT at LTP with a small configurable buffer** (e.g. +0.3%)
rather than MARKET — ETFs can have thin books and a market order can fill badly away from
the deviation you computed.
`Answer:`

**Q-028** 🟠 **Product type.** CNC / delivery for everything, correct? (Relevant because
"short-term capital gains" implies delivery, not intraday.)
*Proposed default:* CNC delivery only; intraday explicitly unsupported.
`Answer:`

**Q-029** 🟡 **Exchange preference.** NSE only, or NSE with BSE fallback for ETFs listed on
both?
*Proposed default:* NSE only in v1; the schema carries an exchange column so BSE can be
added.
`Answer:`

---

## D. Telegram bot, Lambda and run lifecycle

**Q-030** 🟠 **Bot command surface.** Beyond `start` and `stop`, what should the bot do?
*Proposed default:* `/start` (boot EC2 + reply with status and console URL), `/stop`,
`/status`, `/logs` (last run's files), `/funds`. Everything else lives in the console.
`Answer:`

**Q-031** 🔴 **Bot authorisation.** A Telegram bot token in the wild lets anyone who finds
it start your trading engine. How is access restricted?
*Proposed default:* hard allow-list of Telegram user IDs in Lambda config; every command
from an unknown ID is dropped and alerted.
`Answer:`

**Q-032** 🟡 **Chat topology.** One private group for commands + one channel for log files,
or everything in a single chat?
*Proposed default:* one private group for commands and status, one separate channel for log
artefacts, so logs don't bury alerts.
`Answer:`

**Q-033** 🟡 **The 5-second status reply.** EC2 typically takes 30–60 s to boot and pass
health checks; a reply at 5 s can only say "starting". Do you want a single delayed reply
once the engine is genuinely ready, or an immediate ack followed by a ready message?
*Proposed default:* immediate ack, then a second message when the engine's health endpoint
responds — with the console link in that second message.
`Answer:`

**Q-034** 🟠 **Scheduled runs.** Should the engine ever start itself (e.g. an EventBridge
rule at 09:35 on trading days), or is it strictly human-triggered?
*Proposed default:* strictly human-triggered for trading; EventBridge used only for the
Saturday universe job.
`Answer:`

**Q-035** 🟠 **Weekly job execution venue.** The Saturday volume job needs to run when the
trading EC2 is down. Where?
*Proposed default:* a separate scheduled EC2 start (or a Lambda/Fargate task if it fits in
15 minutes) — it only needs market data, not the static IPs, so it does not have to run on
the trading box.
`Answer:`

**Q-036** 🟡 **Trading-holiday awareness.** Should the engine refuse to run on NSE
holidays, and where does the holiday calendar come from?
*Proposed default:* yes — holiday calendar pulled from the broker/NSE and cached in
Supabase; the engine refuses and tells you why.
`Answer:`

**Q-037** 🟡 **Multiple runs per day.** Can the operator hit Execute twice in one day? The
"one buy per category per day" rule suggests not.
*Proposed default:* allowed, but idempotent — the second run sees the first run's buys and
will not re-buy in the same category on the same day.
`Answer:`

**Q-038** 🟡 **Concurrency.** Can two operators trigger runs simultaneously?
*Proposed default:* no — a DB-level run lock per account; the second request is rejected
with a clear message.
`Answer:`

**Q-039** 🟡 **Failure alerting.** Where do hard failures go — Telegram, email, both?
*Proposed default:* Telegram immediately; email digest optional later.
`Answer:`

---

## E. ETF universe and market data

**Q-040** 🔴 **Category classification.** How is an ETF assigned to equity / metals /
global? There is no exchange-provided field for this.
- **(a)** Manual mapping maintained in the ETF master table (operator classifies each).
- **(b)** Rule-based on name/ISIN keywords (`GOLD`, `SILVER`, `NASDAQ`, `HANGSENG` …).
- **(c)** (b) as a suggestion, (a) as the authority.

*Proposed default:* **(c)** — keyword rules propose a category when a new ETF is added, but
the stored value is whatever the operator confirms. Auto-classification alone will
misfile things like a Gold-plus-Silver fund of funds.
`Answer:`

**Q-041** 🟠 **Out-of-scope ETF types.** Indian exchanges also list **debt/G-Sec/liquid**
ETFs which fit none of your three buckets. Excluded entirely, or a fourth "ignore" bucket?
*Proposed default:* a fourth `EXCLUDED` category — recorded in the master, never traded.
Liquid ETFs in particular have huge volume and would otherwise dominate the volume ranking.
`Answer:`

**Q-042** 🔴 **Volume metric definition.** "Past 25 and 60 working days volume, arranged
descending" — what exactly is computed?
- **(a)** average daily traded **quantity** over the window;
- **(b)** total traded quantity over the window;
- **(c)** average daily traded **value** (₹ turnover).

And how do the 25-day and 60-day numbers combine into one pass/fail?
*Proposed default:* compute average daily traded quantity for **both** windows; an ETF
qualifies only if **both** exceed the threshold (a 25-day-only test lets a one-week volume
spike into the universe; a 60-day-only test keeps a dying ETF in).
`Answer:`

**Q-043** 🔴 **Threshold units.** Is "1 lakh" **100,000 units traded** or **₹1,00,000 of
turnover**? ₹1 lakh of turnover is a very low bar for an ETF; 1 lakh units is a meaningful
liquidity filter.
*Proposed default:* **100,000 units** (quantity), config-driven per category so metals and
global — which trade thinner than equity — can carry their own thresholds.
`Answer:`

**Q-044** 🔴 **Market data source.** You named Upstox for data on newly added ETFs. Is
Upstox the **single** market-data provider for the whole system, including for Person B who
has no Upstox account?
*Proposed default:* yes — one dedicated Upstox data app used purely for historical candles
and quotes, decoupled from trading credentials, so data does not depend on which brokers an
investor holds. Data calls do **not** need the per-investor static IP.
`Answer:`

**Q-045** 🟠 **Historical data depth.** Correlations want 250 days, means want up to 90.
How much history do we backfill and keep?
*Proposed default:* backfill and maintain **750 trading days** (~3 years) of daily OHLCV
per ETF. Cheap in Supabase, and it makes any future backtest possible.
`Answer:`

**Q-046** 🟠 **Corporate actions.** ETFs split and pay distributions. Unadjusted prices will
corrupt both the mean-deviation ranking and the correlations. Do we use adjusted prices?
*Proposed default:* store both raw and adjusted close; **all strategy maths uses adjusted
close**. This is a real correctness issue, not a nicety.
`Answer:`

**Q-047** 🟡 **Data refresh cadence.** Daily candle backfill — nightly, or at the start of
each run?
*Proposed default:* both — a nightly scheduled backfill, plus a gap-fill check at run start
so a missed night never silently produces a stale ranking.
`Answer:`

**Q-048** 🟡 **Minimum history for eligibility.** How many days of history must a new ETF
have before it can enter the universe?
*Proposed default:* at least the longest configured lookback plus 10 days, and at least 60
days absolute.
`Answer:`

**Q-049** 🟡 **Universe snapshot immutability.** Should each Saturday's universe be frozen
as an immutable, versioned snapshot the week's runs reference?
*Proposed default:* yes — every run records which universe snapshot ID it used, so any past
decision can be reproduced exactly.
`Answer:`

---

## F. Strategy — buy, sell, sizing

**Q-050** 🔴 **Mean or median?** You asked for both to be computed and the price differences
compared, but only one can drive the ranking.
- **(a)** rank by deviation from **mean**, show median as information;
- **(b)** rank by deviation from **median** (robust to one-off spikes);
- **(c)** rank by the **more conservative** of the two (smaller deviation);
- **(d)** config-driven per account/category.

*Proposed default:* **(d)** defaulting to **(a) mean**, with median always computed,
displayed and logged.
`Answer:`

**Q-051** 🔴 **Deviation measure — percentage or absolute rupees?** "Average 100, today 75"
is −25 in rupees and −25%. Ranking by rupee deviation would rank a ₹5,000 ETF above a ₹100
ETF for the same percentage move, which would be wrong.
*Proposed default:* rank by **percentage deviation** — `(price − mean) / mean`. I am
flagging this because the brief consistently used rupee language, and I do not want to
silently change the strategy.
`Answer:`

**Q-052** 🔴 **"Today's price" during a live run.** The brief says all calculations use the
**one-day closing price**, but runs happen after 09:30 when today has no close. Which is it?
- **(a)** previous trading day's close vs the mean of the N days before it — fully
  deterministic, reproducible, unaffected by when in the day you run;
- **(b)** **live LTP** vs the mean of the last N closes — reflects today's move, but the
  ranking changes minute to minute and is not reproducible.

*Proposed default:* **(b) live LTP** against a mean of closes, because you are placing
trades now and an ETF that gapped down 4% this morning is exactly the candidate the
strategy wants. But the *mean* uses closes only, and the LTP used is snapshotted and logged
so the decision is reproducible after the fact.
`Answer:` **(b) Live LTP against a mean of daily closes.** The LTP used for every ranking decision is snapshotted into the run record and the log so the decision stays reproducible. *(Confirmed 2026-09-16.)*

**Q-053** 🟠 **Quantity derivation.** Given a ₹10,000 per-trade budget and a price of ₹247,
quantity = floor(10000/247) = 40 (₹9,880). Confirm floor, and what happens when one unit
costs more than the budget?
*Proposed default:* floor; if one unit exceeds the budget, skip the candidate and log it
(do not overspend the configured amount).
`Answer:`

**Q-054** 🟠 **Partial funds.** ₹7,000 free against a ₹10,000 configured order.
*Proposed default:* **skip and log**, do not downsize. A downsized position distorts the
averaging maths and the fixed-percentage exit later.
`Answer:`

**Q-055** 🔴 **Sell order validity — the biggest open mechanical question.** A limit sell at
+3.5% will often not fill on the day it is placed. But a normal DAY order dies at 15:30,
and the engine is off, so nobody re-places it. Options:
- **(a)** **GTT / GTC** (Good-Till-Triggered) orders where the broker supports them —
  they survive for months server-side. Upstox and Dhan both offer a GTT facility; Zerodha
  does too; support and semantics differ per broker.
- **(b)** plain **DAY limit orders re-placed at the start of every run** — simple and
  uniform, but the position is unprotected on any day you do not run the engine.
- **(c)** GTT where available, DAY re-placement as the fallback.

*Proposed default:* **(c)**. This is the single most consequential broker-capability
difference in the project and it deserves its own design document.
`Answer:` **(c) GTT/GTC where the broker supports it, DAY limit re-placed at run start as the fallback.** Per-broker GTT semantics, validity periods and modification rules go into the broker capability matrix (doc 16) and get their own section in SELL-LOGIC (doc 20). *(Confirmed 2026-09-16.)*

**Q-056** 🟠 **Duplicate sell orders.** At run start you place sells for all holdings. If
yesterday's sell is still resting, do we skip, cancel-and-replace, or modify?
*Proposed default:* reconcile against the broker's order book; if a resting sell exists at
the correct price and quantity, leave it; if the price is wrong (e.g. after averaging),
cancel and replace; never place a second sell for the same holding.
`Answer:`

**Q-057** 🟠 **Profit target base.** Is the +3.5% computed on the raw traded price, or on
the all-in cost including brokerage, STT, GST, stamp duty and exchange fees?
*Proposed default:* **raw traded price**, with the charge-inclusive breakeven shown in the
UI and logs so you can see the true net. Charges on a ₹10,000 ETF delivery trade are small
but not zero.
`Answer:`

**Q-058** 🟠 **Tick-size rounding.** The limit price must land on a valid tick (₹0.01 for
most ETFs). Round up or down?
*Proposed default:* round **up** to the next valid tick, so the realised percentage is never
below target.
`Answer:`

**Q-059** 🟠 **Cost basis when a holding was not bought by ATOM.** If a holding pre-exists
in the broker account, or was bought manually, where does its buy price come from for the
sell-target calculation?
*Proposed default:* use the broker's reported average cost for holdings ATOM has no record
of, and flag them as `EXTERNAL` in the UI so you know the basis is the broker's, not ours.
`Answer:`

**Q-059b** 🟠 **Scope of "holdings".** Does the holdings check that blocks a re-buy look at
the **whole broker account** (including positions ATOM did not create), or only at
ATOM-managed positions?
*Proposed default:* whole account — an ETF you already own is an ETF you already own,
regardless of who bought it.
`Answer:`

---

## G. Configuration model

**Q-060** 🟠 **Config scope matrix.** Confirm which settings are per-account, per-category,
or global:

| Setting | Proposed scope |
|---|---|
| Profit target % | per account × category |
| Depth / levels | per account × category |
| Trade amount ₹ | per account × category |
| Lookback days | per account × category |
| Mean vs median | per account × category |
| Category enable/disable | per account × category |
| Category buy priority | per account (an ordering of the three) |
| Volume threshold | global, overridable per category |
| Correlation window | global |
| STCG rate | global |

`Answer:`

**Q-061** 🟠 **Config change audit.** Should every config change be versioned with who
changed it, when, and the old value — and should each run record the exact config snapshot
it used?
*Proposed default:* yes to both. This is what makes "why did it buy that?" answerable six
months later.
`Answer:`

**Q-062** 🟡 **Config edit timing.** Can configs be changed mid-run?
*Proposed default:* no — the run snapshots config at start and ignores later edits.
`Answer:`

**Q-063** 🟡 **Config defaults for a new account.** When a new investor is onboarded, what
do they start with?
*Proposed default:* a named template (equity 3.5% / metals 5% / global 2%, depth 3/3/3,
lookback 50 days, ₹10,000) that the operator adjusts.
`Answer:`

---

## H. Web console

**Q-064** 🟠 **Daily Status row count.** The brief said "top 6 or 7" in one place and
"10 securities" in another.
*Proposed default:* show **10 rows**, with rows beyond the configured depth greyed out, as
described.
`Answer:`

**Q-065** 🟠 **Daily Status history.** How many days of history should the screen offer?
*Proposed default:* a date picker over all history, defaulting to today; data retained
indefinitely in Supabase.
`Answer:`

**Q-066** 🔴 **Login-button liveness.** The site is always up on Render; the login option
should appear only when EC2 is up. How does the static site learn the engine's state?
- **(a)** the site polls a tiny always-on endpoint (a Lambda behind API Gateway) that
  reports EC2 state;
- **(b)** the engine writes a heartbeat row to Supabase and the site reads it directly;
- **(c)** the site tries the engine's own health URL and shows login if it answers.

*Proposed default:* **(b)** — Supabase is already in the stack, needs no extra
infrastructure, is free, and gives you a heartbeat history for free. Note that hiding the
button is **UX, not security** — the engine must still authenticate every request (Q-070).
`Answer:`

**Q-067** 🔴 **Where does the console UI actually run?** Two very different architectures:
- **(a)** the whole console is served **from the EC2 engine** (FastAPI + templates or a
  bundled SPA), and Render hosts only the marketing page that links to it;
- **(b)** the console SPA is **hosted on Render permanently** and calls the EC2 engine's
  API over the network when it is up.

*Proposed default:* **(a)**. It avoids exposing the engine's API to the public internet
with CORS, avoids needing a stable public DNS name and TLS certificate for an instance that
comes and goes, and means the console simply does not exist when the engine is down — which
matches the behaviour you described. Render hosts the static site and the login redirect.
`Answer:`

**Q-068** 🟠 **Engine addressing.** If (a), the EC2 instance needs a stable address and TLS
for the browser. Options: a dedicated Elastic IP + DNS A record + Let's Encrypt, or a
Cloudflare tunnel.
*Proposed default:* a **third Elastic IP dedicated to the console** (kept entirely separate
from the two broker-registered trading IPs — those must never be used for anything else),
with `app.<yourdomain>` pointing at it and a certificate baked into the image.
`Answer:`

**Q-069** 🟡 **UI framework.** You left this open.
*Proposed default:* **React + Vite + TypeScript + Tailwind**, served as static files by the
Python engine. A charting library (Recharts) for the report screens.
`Answer:`

**Q-069b** 🟡 **Mobile.** Does the console need to be usable on a phone, or desktop only?
*Proposed default:* desktop-first, responsive enough to check status on a phone; the trade
execution screens assume a desktop.
`Answer:`

---

## I. Authentication and security

**Q-070** 🔴 **Console authentication mechanism.** Free options: Supabase Auth (already in
the stack, supports email+password, Google, GitHub, magic links), Firebase Auth, or
self-rolled.
*Proposed default:* **Supabase Auth with Google sign-in restricted to an allow-list of 2–3
email addresses**, plus email+password as a fallback. No new vendor, no extra cost, and the
engine can verify the JWT locally.
`Answer:`

**Q-071** 🟠 **Two-factor.** Given this software can place real trades, do you want TOTP 2FA
on console login?
*Proposed default:* yes — Google sign-in with the Google account's own 2FA satisfies this;
password login additionally requires TOTP.
`Answer:`

**Q-072** 🟠 **Roles.** Do all 2–3 users have identical powers, or is there a read-only
role?
*Proposed default:* two roles — `ADMIN` (can execute, harvest, change configs) and
`VIEWER` (read-only on all screens).
`Answer:`

**Q-073** 🔴 **Secrets management.** Where do broker API keys/secrets, the Telegram bot
token, the Supabase service key and the Google Drive credentials live?
*Proposed default:* **AWS Secrets Manager**, fetched at engine boot via an instance role.
Nothing in the repo, nothing in a `.env` on disk, nothing in the AMI.
`Answer:`

**Q-074** 🟠 **Supabase RLS.** Should row-level security isolate data per investor, so a
future investor-facing login cannot read another investor's data?
*Proposed default:* yes — design RLS policies from day one even though only operators log
in today. Retrofitting RLS is painful.
`Answer:`

**Q-075** 🟠 **PII.** Do we store investor names, PANs or client codes? PAN is sensitive
under Indian data-protection rules.
*Proposed default:* store the broker's client code (needed for reconciliation); do **not**
store PAN or bank details.
`Answer:`

**Q-076** 🟡 **Log redaction.** Confirm that tokens, API secrets and client codes are masked
in all logs — including the `.txt` files sent to Telegram and Google Drive.
*Proposed default:* yes, a redaction filter on the log handler, with a test asserting no
secret pattern reaches a log sink.
`Answer:`

**Q-077** 🟡 **Audit trail for human actions.** Should every operator click that causes a
trade (Execute, Average, Harvest) be recorded with user, timestamp and payload?
*Proposed default:* yes, in an immutable `action_audit` table.
`Answer:`

**Q-078** 🟠 **Kill switch.** Do you want a global "halt all trading" flag that the engine
checks before every order?
*Proposed default:* yes — one row in Supabase, flippable from the console and from Telegram.
`Answer:`

**Q-079** 🟠 **Per-run and per-day spend caps.** A guard against a logic bug placing many
orders.
*Proposed default:* a hard per-account daily cap (default: sum of configured category
amounts × 2) and a max-orders-per-run cap; breaching either aborts the run and alerts.
`Answer:`

---

## J. Tax-loss harvesting

**Q-080** 🟠 **STCG rate.** 20% was stated. Should it be a config value, and do you want
surcharge and cess modelled, or is the headline rate enough for a planning estimate?
*Proposed default:* config value defaulting to 20%, headline rate only, with a visible
disclaimer that the figure is an estimate and not tax advice.
`Answer:`

**Q-081** 🔴 **Proxy cost-basis carry-over — confirm the rule.** You described selling a
₹10,000 position now worth ₹9,000, buying ₹9,000 of a proxy, and then setting the proxy's
**exit target from the original ₹10,000** (so ₹10,350 at 3.5%), not from the ₹9,000 actually
paid. That means ATOM tracks a **synthetic cost basis** that differs from the broker's. Two
consequences I want you to confirm you want:
1. The proxy must rise ~15% from ₹9,000 to hit ₹10,350, so it may sit for a long time.
2. ATOM's P&L for that position will differ from the broker's until it is closed.

*Proposed default:* implement exactly as described, with the synthetic basis stored in a
`harvest_chain` table linking the sold lot to the proxy lot, and both bases shown in the UI.
`Answer:`

**Q-082** 🔴 **Correlation definition.** On what series and what statistic?
*Proposed default:* **Pearson correlation of daily log returns** over a configurable window
defaulting to 250 trading days. Correlating raw price levels produces meaninglessly high
numbers for almost any pair of trending assets — this matters.
`Answer:`

**Q-083** 🟠 **Minimum correlation to permit a swap.** Is there a floor below which a proxy
is rejected outright?
*Proposed default:* yes — a config floor of **0.85**; pairs below it are shown but cannot be
executed without an explicit override.
`Answer:`

**Q-084** 🟠 **Proxy candidate pool.** Must the proxy come from the current tradable
universe (i.e. pass the volume filter), or can it be any ETF in the master?
*Proposed default:* it must pass the volume filter — buying an illiquid proxy defeats the
purpose.
`Answer:`

**Q-085** 🔴 **Same-day execution and settlement risk.** Selling and buying the same day
means the sale proceeds are not yet settled (T+1). Does the account have enough free cash to
fund the proxy buy before the sale settles, or do we rely on the broker's intraday limit
against sold delivery holdings?
*Proposed default:* check free funds first; if insufficient, present the harvest as
"executable tomorrow" rather than failing mid-way. This is a real operational trap.
`Answer:`

**Q-086** 🟠 **Partial-failure handling.** Sell fills, proxy buy fails (price moved, funds
short, rate limit).
*Proposed default:* never leave it silent — alert on Telegram immediately, mark the chain
`INCOMPLETE`, and present a one-click retry on the harvest screen. No automatic rollback,
because buying back the ETF you just sold would create a wash-like round trip and undo the
loss booking.
`Answer:`

**Q-087** 🟠 **Wash-sale / bed-and-breakfasting.** India has no US-style wash-sale rule, but
buying back the **same** ETF the same day can be treated as intraday and squares off the
position rather than booking a delivery loss. Confirm the proxy must always be a
**different ISIN**.
*Proposed default:* enforce different ISIN, hard constraint, not a preference.
`Answer:`

**Q-088** 🟠 **Gains scope.** Is the gain being offset only realised gains **within ATOM**,
or all realised gains in the broker account for the financial year?
*Proposed default:* all realised gains visible from the broker's trade book for the current
financial year, with ATOM's own trades identified separately.
`Answer:`

**Q-089** 🟡 **Harvest frequency.** Any limit on how often a position can be harvested, or
how many harvests per session?
*Proposed default:* no hard limit, but the screen ranks opportunities and the operator
approves each one individually.
`Answer:`

---

## K. Order lifecycle and reconciliation

**Q-090** 🔴 **Unfilled orders at shutdown.** Polling is every minute while the engine runs,
but the engine then stops. What happens to a buy that has not filled?
- **(a)** cancel all unfilled buys before shutdown;
- **(b)** leave them resting and reconcile at the start of the next run (a fill you did not
  see means no sell order was placed for it until the next run);
- **(c)** block shutdown until all orders are terminal.

*Proposed default:* **(b)** with an explicit reconciliation step at the top of every run
that finds fills which happened while the engine was down and places their missing sell
orders. Plus a Telegram warning at shutdown listing anything still pending.
`Answer:`

**Q-091** 🟠 **Polling ceiling.** How long does the engine wait for a buy to fill before
giving up and moving on?
*Proposed default:* poll for a configurable 5 minutes, then proceed; the order stays live
and is picked up by reconciliation.
`Answer:`

**Q-092** 🟠 **Partial fills.** A buy for 40 units fills 25. What is the sell quantity and
what is the average price?
*Proposed default:* place the sell for the filled quantity at the target based on the actual
fill price; leave the remainder resting; handle a later top-up fill via reconciliation.
`Answer:`

**Q-093** 🟡 **Order rejection.** Broker rejects a buy (insufficient funds, freeze quantity,
circuit limit).
*Proposed default:* log the broker's reason verbatim, surface it on Daily Status and in the
`.txt` log, do not retry automatically, and move to the next category.
`Answer:`

**Q-094** 🟠 **Idempotency.** If the engine crashes after sending an order but before
recording it, a restart must not duplicate it.
*Proposed default:* write an intent row with a client-generated idempotency tag **before**
sending; on restart, match against the broker order book by tag/timestamp before re-sending.
`Answer:`

**Q-095** 🟡 **Sell fill notification.** When a sell fills days later while the engine is
down, how do you find out?
*Proposed default:* the next run's reconciliation detects it, records the realised P&L, and
the run summary reports it. A Telegram message on newly detected fills.
`Answer:`

---

## L. Reporting and charges

**Q-096** 🟠 **Reporting period basis.** Calendar months, or Indian financial year
(Apr–Mar) periods?
*Proposed default:* both — monthly rows, with FY-to-date totals, since tax is FY-based.
`Answer:`

**Q-100** 🔴 **Charges: computed or fetched?** Two approaches, each with real trade-offs:
- **(a)** **Fetch from each broker** — contract notes / charges API / ledger. Exact, but
  every broker differs and some expose it only in a downloadable PDF or a ledger line, and
  the data arrives T+1 or later.
- **(b)** **Compute locally** from a per-broker fee schedule (brokerage, STT, exchange
  txn charge, SEBI fee, stamp duty, GST, DP charge on sells). Instant and uniform, but
  drifts when a broker changes its rate card.
- **(c)** compute locally for live estimates, reconcile against the broker's ledger monthly
  and store the difference.

*Proposed default:* **(c)**. It is the only way to get both a live net-P&L number and a
figure that ties out to the broker's statement. This is the research-heavy area you flagged
and it will get its own document.
`Answer:`

**Q-101** 🟠 **DP charges.** Depository charges are levied per scrip per day on **sells**,
by the DP, and typically appear in the **ledger**, not the trade P&L, often days later.
Confirm the report must attribute them back to the originating sell trade.
*Proposed default:* yes — attribute to the trade where possible, show as an unattributed
ledger line where not.
`Answer:`

**Q-102** 🟠 **Report granularity.** What does a monthly row look like?
*Proposed default:* per month per account per broker: trades count, turnover, gross realised
P&L, brokerage, STT, exchange+SEBI fees, stamp duty, GST, DP charges, net realised P&L,
unrealised P&L at month end, estimated STCG tax, harvested losses, and net-of-tax P&L.
`Answer:`

**Q-103** 🟡 **Export format.** CSV was named. Also want Excel or PDF?
*Proposed default:* CSV in v1; Excel later if you actually need formatting.
`Answer:`

**Q-104** 🟠 **Ledger ingestion.** Do we pull the broker ledger automatically on a schedule,
or does the operator upload statements?
*Proposed default:* pull automatically where an API exists; allow a manual CSV upload as a
fallback for brokers that do not expose it.
`Answer:`

**Q-105** 🟡 **Benchmarking.** Do you want strategy performance compared against a benchmark
(e.g. NIFTY 50) in the reports?
*Proposed default:* not in v1; the schema will not preclude it.
`Answer:`

---

## M. Logging and archival

**Q-110** 🔴 **"Local S3" clarification.** You said logs go to Google Drive and to "your
local S3", cleared monthly. Do you mean:
- **(a)** AWS S3 with a 30-day lifecycle rule (and Drive as the permanent archive);
- **(b)** local disk on the EC2 instance (which is lost on shutdown unless EBS persists);
- **(c)** both — local file during the run, uploaded to S3 and Drive at the end.

*Proposed default:* **(c)** — write locally during the run so nothing is lost to a network
blip, upload to S3 (30-day lifecycle) and Google Drive (permanent) at run end, and also
store the structured log **rows** in Supabase so they are queryable.
`Answer:`

**Q-111** 🟠 **Log granularity.** One `.txt` per account per broker per run was stated.
Confirm the file naming convention.
*Proposed default:* `YYYY-MM-DD/<run_id>/<investor>_<broker>_<run_id>.txt`.
`Answer:`

**Q-112** 🟠 **Structured vs human-readable.** The `.txt` must be readable by a human. Do we
also emit JSON lines for machine querying?
*Proposed default:* both — structured JSON to Supabase and to a `.jsonl` sibling file, plus
the human-readable `.txt` you described, generated from the same event stream so they can
never disagree.
`Answer:`

**Q-113** 🟠 **Google Drive access.** A service account with a shared folder, or OAuth
against a personal Drive? (Note: a service account's own Drive has no free storage quota —
it must write into a folder shared from a real account.)
*Proposed default:* service account writing into a folder shared by your Google account.
`Answer:`

**Q-114** 🟡 **Retention in Supabase.** How long do structured log rows and price history
stay?
*Proposed default:* indefinitely — the volumes here are small enough that deleting is a
bigger risk than keeping.
`Answer:`

**Q-115** 🟡 **Log size.** Should the Telegram upload be capped (Telegram has a ~50 MB bot
upload limit)?
*Proposed default:* gzip above 5 MB; if still too large, send the S3/Drive link instead.
`Answer:`

---

## N. Database

**Q-120** 🟠 **Supabase project.** Does one already exist, and is it free-tier or paid?
Free tier pauses after a week of inactivity, which matters for a system that only wakes on
trading days.
`Answer:`

**Q-121** 🟠 **Schema naming.** One schema (`atom`) or several (`atom_core`, `atom_market`,
`atom_audit`)?
*Proposed default:* one `atom` schema with clear table prefixes; simpler RLS and migrations.
`Answer:`

**Q-122** 🟠 **Migrations.** How are schema changes managed?
*Proposed default:* SQL migration files in the repo, applied via the Supabase CLI, reviewed
like code. No clicking in the dashboard.
`Answer:`

**Q-123** 🟠 **Money representation.** Floats will eventually cost you a rupee.
*Proposed default:* `NUMERIC(18,4)` for all money and prices; never `float8`. Quantities as
integers.
`Answer:`

**Q-124** 🟠 **Time zone.** All timestamps in `timestamptz` stored UTC, displayed IST?
*Proposed default:* yes, with a `trade_date` column in IST for day-boundary logic, because
"which trading day" must never be ambiguous.
`Answer:`

**Q-125** 🟠 **Lot-level or position-level tracking?** Averaging and harvesting both need to
know individual purchase lots.
*Proposed default:* **lot-level** (every buy is a lot with its own cost and date), with
positions derived. Required for FIFO tax computation, which India uses.
`Answer:`

**Q-126** 🟠 **Tax lot matching method.** India uses FIFO for equity/ETF capital gains.
*Proposed default:* FIFO, implemented explicitly and testable.
`Answer:`

**Q-127** 🟡 **Soft deletes.** Should anything ever be hard-deleted?
*Proposed default:* nothing in trading or audit tables; status columns only.
`Answer:`

**Q-128** 🟡 **Backups.** Beyond Supabase's own, do you want a scheduled logical dump to S3?
*Proposed default:* yes — a weekly `pg_dump` to S3, because free-tier backup retention is
short.
`Answer:`

**Q-129** 🟡 **Local development.** Do developers run Supabase locally, or share a dev
project?
*Proposed default:* a separate Supabase dev project; local Docker Supabase optional.
`Answer:`

---

## O. Operations, testing and compliance

**Q-130** 🟠 **Testing strategy.** How much confidence do you want before real money?
*Proposed default:* unit tests on all strategy maths with fixed fixtures, contract tests per
broker adapter against recorded responses, an end-to-end dry run on live data, then one
week of ₹1,000-size live trades before full size.
`Answer:`

**Q-131** 🟠 **Backtesting.** Do you want a backtest harness to validate the mean-reversion
parameters (lookback, depth, target %) against history, or is the strategy settled?
*Proposed default:* build it — the same historical data is already being stored, and picking
lookback/target by intuition is the most likely source of disappointment. It is a separate
deliverable, not a v1 blocker.
`Answer:`

**Q-132** 🟠 **Regulatory posture.** This places trades in other people's accounts using
their credentials. Are Person A and Person B family/self, or external clients?
*Proposed default (needs your confirmation, not mine):* I have assumed **self and family**,
operating your own accounts. If these are external clients paying for the service, SEBI
registration (RIA or PMS) and a much heavier compliance and disclosure surface come into
play, and the design would need to reflect that. Please confirm explicitly. `[important]`
`Answer:` **Self and family, own accounts.** No SEBI intermediary registration implied; no external-client compliance surface in scope. *(Confirmed 2026-09-16.)* If this changes, the design must be revisited — flagged in the threat model (doc 37).

**Q-133** 🟡 **Broker T&C.** Have you confirmed each broker's API terms permit automated
order placement for an account you do not personally own?
`Answer:`

**Q-134** 🟡 **Monitoring.** Beyond Telegram alerts, do you want uptime/health monitoring on
the Render site and the engine?
*Proposed default:* a free uptime monitor on the static site; the engine's health is the
Telegram flow.
`Answer:`

**Q-135** 🟡 **Cost budget.** What is the acceptable monthly infrastructure spend? This
decides EC2 size, Elastic IP count (idle EIPs are billed), and Supabase tier.
*Proposed default:* target under ₹2,000/month at two accounts.
`Answer:`

**Q-136** 🟡 **Documentation review process.** Do you want to review each document as it
lands, or all ~25 at once at the end?
*Proposed default:* in batches by area (infra, brokers, strategy, data, web, reporting) so
corrections apply to later documents.
`Answer:`

---

## Summary of blockers

The design cannot proceed past a high-level architecture sketch without these 🔴 items:

| ID | Topic |
|---|---|
| Q-010, Q-011 | Per-account static-IP egress mechanism; IP procurement status |
| Q-020, Q-022, Q-023 | Broker scope for v1; daily token flow; token storage |
| Q-031 | Telegram bot authorisation |
| Q-040, Q-042, Q-043, Q-044 | Category classification; volume metric; threshold units; data source |
| Q-050, Q-051, Q-052 | Mean vs median; % vs ₹ deviation; which price is "today's price" |
| Q-055 | Sell order validity (GTT vs DAY re-placement) |
| Q-066, Q-067 | Login liveness signal; where the console runs |
| Q-070, Q-073 | Console auth; secrets management |
| Q-081, Q-082, Q-085 | Proxy cost-basis carry-over; correlation definition; settlement funding |
| Q-090 | Unfilled orders at shutdown |
| Q-100 | Charges: computed vs fetched |
| Q-110 | "Local S3" clarification |
| Q-132 | Regulatory posture (self/family vs external clients) |
