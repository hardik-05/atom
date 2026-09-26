# System Overview

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Audience:** anyone about to write or read ATOM's code

> ATOM is a **once-daily, delivery-only, mean-reversion trading system for Indian ETFs**,
> operated by one admin on behalf of a small number of family investors, across up to five
> brokers, with every decision reconstructible from the database afterwards.

This document is the map. It says what the pieces are, what each one is allowed to know, and where
the boundaries are. Every claim here traces to a decision in
[`../00-discovery/DECISIONS.md`](../00-discovery/DECISIONS.md).

---

## 1. What the system actually does, once a day

```
                       operator (Telegram)
                              │
                              ▼
                      ┌───────────────┐
                      │ Lambda: start │  bring EC2 up on demand
                      └───────┬───────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                        EC2 instance                          │
   │                                                              │
   │   ┌────────────────────────────────────────────────────┐     │
   │   │              RUN ORCHESTRATOR                      │     │
   │   │   one run per (account, universe, day) — D-172     │     │
   │   └───┬────────────────────────────────────────────────┘     │
   │       │                                                      │
   │       ├─► 1. PRE-FLIGHT      egress IP · token · clock       │
   │       ├─► 2. REFERENCE       instrument sync · prices · NAV   │
   │       ├─► 3. RECONCILE       holdings vs ATOM's lots          │
   │       ├─► 4. SELL PASS       cancel-all → verify → place GTTs │
   │       ├─► 5. BUY PASS        deviation → gates → orders       │
   │       ├─► 6. HARVEST         operator-selected, if queued     │
   │       └─► 7. SETTLE          fills · lots · charges · accrual  │
   │                                                              │
   │   ┌──────────────┐  ┌───────────────┐  ┌────────────────┐    │
   │   │ ADAPTER      │  │ local forward │  │  web console   │    │
   │   │ ENGINE  ×5   │──│ proxy (Nginx) │  │  (served here) │    │
   │   └──────┬───────┘  └───────┬───────┘  └────────────────┘    │
   └──────────┼──────────────────┼───────────────────────────────┘
              │                  │
              │          per-investor static
              │            Elastic IP  (D-173)
              ▼                  ▼
        ┌──────────┐      ┌──────────────┐
        │ Supabase │      │ five brokers │
        │ Postgres │      └──────────────┘
        └──────────┘
```

**Seven phases, strictly ordered, linear.** Runs within a batch never execute in parallel
(D-057f). The sell pass always precedes the buy pass (D-057), because selling frees cash the buy
pass may use and because an unprotected holding is the larger risk.

---

## 2. The five things that make this system what it is

Everything else follows from these. If a future change contradicts one of them, that is a design
decision to be made deliberately, not an implementation detail.

### 2.1 Percentage deviation, not rupee deviation (D-149)

The buy signal is `(ltp − mean) / mean`, expressed as a percentage, held to **4 decimal places
internally and displayed to 2**. A rupee threshold cannot work across a universe where prices span
₹25 to ₹2,000 — an 83× dispersion within the INDEX bucket alone.

### 2.2 The universe is a first-class entity (D-156)

A **universe** is a named collection of instruments with its own configuration, its own runs, its
own P&L, and its own comparison against its peers. An instrument may sit in several universes
simultaneously. Lots belong to a universe. Membership is **SCD Type 2**, so "what was in this
universe on that date" is always answerable.

Capital, however, is held at the **account** level (D-169) — there is one real pot of money. So
reporting is three-tier: universe (pure P&L), account (adds idle drag), investor/PAN (tax only).

### 2.3 Lot-level tracking, and two different FIFOs (D-166, D-167)

**One `position_lot` per fill** — never per order, never averaged. The lot grain is the fill
because averaging fills destroys the tax basis.

Two FIFO computations run over the same lots and **must not be conflated**:

| | Orders by | Scope | Used for |
|---|---|---|---|
| **Universe FIFO** | acquisition within a universe | one universe | strategy P&L, sell selection |
| **Tax FIFO** | acquisition across the whole PAN | investor | `tax_gain`, set-off, liability |

A disposal may pair with a lot from a different universe under tax FIFO. That is correct and
intended.

### 2.4 Two cost bases per lot (D-188 … D-206)

| | Column | Drives |
|---|---|---|
| **Actual** | `unit_cost` | tax · real P&L · cost of capital · broker reconciliation |
| **Synthetic** | `synthetic_cost_basis` | deviation · sell trigger · GTT price · averaging |

Normally identical. They diverge only after a tax-loss harvest, where the proxy inherits the
harvested security's committed capital so that harvesting changes the **tax** outcome and nothing
else. Full model in [`../04-strategy/HARVEST-COST-BASIS.md`](../04-strategy/HARVEST-COST-BASIS.md).

### 2.5 Brokers are an input, normalised at one boundary (D-185)

Five brokers disagree on nearly everything that is not the price of a share. **None of it leaks
past the adapter engine.** The strategy, tax, reporting and web layers never contain a broker
name, never branch on which broker an account uses, and never see `tsym` or `securityId`.

Full specification: [`../03-brokers/ADAPTER-ENGINE.md`](../03-brokers/ADAPTER-ENGINE.md).

---

## 3. Layers, and what each is allowed to know

```
┌───────────────────────────────────────────────────────────────────┐
│  WEB CONSOLE          React · TS · Tailwind · navy · light+dark   │
│  knows: canonical models, ₹, %, universe names                    │
│  never: broker fields, HTTP, SQL                                  │
├───────────────────────────────────────────────────────────────────┤
│  REPORTING            P&L · charges · cost of capital · tax       │
│  knows: lots, closures, charges, accruals, config snapshots       │
│  never: brokers, live prices                                      │
├───────────────────────────────────────────────────────────────────┤
│  STRATEGY             deviation · gates · sell logic · harvest     │
│  knows: instrument_id, universes, config, canonical models         │
│  never: which broker, how an order is serialised                   │
├───────────────────────────────────────────────────────────────────┤
│  ORCHESTRATION        run lifecycle · batches · execution list     │
│  knows: everything above; owns transactions and ordering           │
├───────────────────────────────────────────────────────────────────┤
│  ADAPTER ENGINE       5 adapters · canonical models · capabilities  │
│  knows: one broker's dialect each                                  │
│  never: strategy, thresholds, universes, DB writes                  │
├───────────────────────────────────────────────────────────────────┤
│  PERSISTENCE          38 tables · invariants as CHECK constraints   │
├───────────────────────────────────────────────────────────────────┤
│  INFRASTRUCTURE       EC2 · Lambda · proxy · static IP · SSM         │
└───────────────────────────────────────────────────────────────────┘
```

**The rule that makes this testable:** each layer depends only on the one below it, and adapters
depend on nothing but their own broker. So the strategy layer is tested with a fake adapter and no
network; adapters are tested with recorded vendor fixtures and no database.

---

## 4. Execution modes — the seam that makes this safe to build (D-045)

Every run carries an `execution_mode`, **frozen at run start** from the account:

| Mode | Orders | Prices | Charges | Everything else |
|---|---|---|---|---|
| **`DRY`** | simulated at the `OrderGateway` seam | configurable source | computed, and from the broker's calculator where available | identical |
| **`LIVE`** | sent to the broker | broker LTP | computed **and** reported | identical |

The seam is a single interface. **Dry and live share every line of strategy, gate, lot, tax and
reporting code** — which is what makes dry-run output meaningful rather than a separate program
that happens to look similar.

Constraint enforced in the schema: a `LIVE` account **must** have both `egress_ip` and `proxy_url`
set (`trading_account_live_needs_proxy_ck`). A live account cannot exist without its static-IP
plumbing.

---

## 5. Non-negotiables

Stated as bare rules because each has a specific failure it prevents.

| Rule | Prevents |
|---|---|
| **Limit orders only. No `MARKET`, ever** (D-174) | Market orders are no longer permitted via API since 1 Apr 2026; also uncontrolled fills |
| **Delivery / CNC only. No margin, MTF, intraday, leverage or pledging** (D-207) | Borrowed money in a system designed for owned money |
| **One lot per instrument per day, per account** (D-036) | Runaway accumulation from a repeated signal |
| **Write order intent before sending** (D-094) | A crash mid-placement producing a duplicate order |
| **Unknown order status = in-flight, never terminal** (D-180) | Re-placing an order that is about to fill |
| **Cancel only ATOM's own GTTs** (D-064) | Destroying the investor's manually placed orders |
| **Token validity tested, never computed** (D-170) | Trusting a documented lifetime that changed |
| **Egress IP verified as a separate pre-flight gate** (D-173) | Dhan whitelists writes only, so the token probe passes while orders fail |
| **Never auto-un-release a blocked instrument** (D-091) | A silent return to trading something withdrawn for a reason |
| **Unrecognised cash narration → `UNKNOWN`, never guessed** | A misclassified event corrupting the cost-of-capital model |
| **Sell pass caps at `free_quantity`, defers the rest** (D-182) | A foreseeable rejection treated as an accepted outcome |
| **≤ 2 OPS, hard-capped** (D-088) | Crossing the SEBI/NSE 10 OPS registration threshold |

---

## 6. What ATOM deliberately is not

Recorded so nobody re-derives these as gaps.

| Not | Why |
|---|---|
| Intraday or high-frequency | One run a day (D-057e); ~1 OPS |
| A backtesting platform | Out of scope for v1 |
| Multi-tenant or a product | Single admin, one family (D-133) |
| Correlation-matched harvest proxies | Researched and parked as **V2-14**; v1 proxies are chosen manually (D-163) |
| Chained harvests | Explicitly disallowed (D-193) |
| Dividend-aware | Dividends and dividend stripping are out of scope |
| A margin or derivatives system | D-207 |
| Fractional-share capable | Indian markets have none; `floor` is explicit (D-059b) |

---

## 7. Technology

| Layer | Choice | Note |
|---|---|---|
| Backend | **Python** | Raw HTTP to brokers, no vendor SDKs (D-056b) |
| Database | **Supabase Postgres** | 38 tables, RLS, schema `atom` |
| Compute | **AWS EC2**, on demand | Started by Lambda via Telegram; ~$8.58/mo at 2 accounts |
| Egress | **Elastic IP per investor** + local forward proxy | Mandatory since 1 Apr 2026 (D-173) |
| Secrets | **AWS SSM Parameter Store** | `broker_session` stores the *path*, never the token (D-079) |
| Web | **React · TypeScript · Tailwind** | Navy financial theme, light **and** dark |
| Static failover | Render | Same look; only the login button differs |
| Logs | Local → **S3** → Google Drive | |
| Domain | `metalcocapital.com` | Auto-switches between EC2 and the static site |

---

## 8. Where to read next

| To understand | Read |
|---|---|
| What happens in a run, step by step | [`RUN-LIFECYCLE.md`](RUN-LIFECYCLE.md) |
| Which module owns what | [`MODULE-MAP.md`](MODULE-MAP.md) |
| How config resolves | [`CONFIGURATION-MODEL.md`](CONFIGURATION-MODEL.md) |
| Dry run vs live | [`EXECUTION-MODES-AND-DRY-RUN.md`](EXECUTION-MODES-AND-DRY-RUN.md) |
| Broker translation | [`../03-brokers/ADAPTER-ENGINE.md`](../03-brokers/ADAPTER-ENGINE.md) |
| The data model | [`../05-data/DATABASE-SCHEMA.md`](../05-data/DATABASE-SCHEMA.md) |
| Why any decision is what it is | [`../00-discovery/DECISIONS.md`](../00-discovery/DECISIONS.md) |
