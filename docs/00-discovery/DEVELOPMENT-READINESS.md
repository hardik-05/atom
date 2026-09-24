# Development Readiness Assessment

**Date:** 2026-09-24 · **updated after the prior-art review (round 21–22)**
**Question:** are we ready to start writing application code?
**Short answer:** **Partially. Enough to start one specific slice; not enough to start broadly —
and one document should be written first regardless.**

---

## 1. Where the design actually stands

| | |
|---|---|
| Decisions recorded | **143** (D-001 … D-143) |
| Documents | 27, ~7,200 lines |
| Committed artefacts | 3 working scripts, 3 generated datasets, 5 raw source files |
| Design questions open | **0** — all answered, deferred to v2 with reasoning, or converted to research |

**The strategy is unusually well specified for this stage.** Ranking, the NAV gate, depth/skip,
category priority, the GTT cycle with cancel-first, exclusions and freezes, corporate-action
blocking with peer comparison, the three-tier taxonomy, cost of capital in three buckets,
per-bucket taxation at PAN level — all decided, with the reasoning recorded and the edge cases
named.

That is the hard part of a trading system, and it is done.

---

## 2. What is missing — honestly

Measured against the 40-document plan in [`../README.md`](../README.md):

| Batch | Written | Planned | Gap |
|---|---|---|---|
| Architecture | 2 | 4 | System overview, run lifecycle, module map |
| Infrastructure | 1 | 5 | **AWS topology, static-IP design**, Lambda/Telegram, deployment |
| Brokers | 8 | 7 | ✅ Complete (adapter contract still to formalise) |
| Strategy | 6 | 7 | Buy logic, averaging, harvesting, order lifecycle consolidation |
| **Data** | **0** | **4** | 🔴 **Schema, data dictionary, market-data pipeline, traceability** |
| **Web** | **0** | **4** | 🔴 **UI architecture, screen specs, design system, auth** |
| Observability / reporting / ops | 4 | 9 | Logging spec, charges model, runbook, threat model, testing strategy |
| Diagrams | 0 | 8 | All |

### 🔴 The one genuine blocker: the database schema

**Nothing should be written before this.** Every other gap can be filled while coding; the schema
cannot, because everything persists into it and a mistake there is expensive to unwind after
code exists.

It is also no longer a small job. The design has accumulated real structure:

- **Lot-level tracking** — mandatory, because position-level cannot represent averaging (D-045)
- **Typed cash ledger** — `CAPITAL_IN` / `CAPITAL_OUT` / `PROFIT_WITHDRAWAL`, since principal
  and profit behave differently (D-047)
- **Settlement dates per sale** — `funds_credited_date`, observed never assumed (D-050)
- **Config versioning** with per-run snapshots, and no defaults (D-038, D-061)
- **Exclusions and freezes** as quantities, not flags (D-062)
- **Universe snapshots**, frozen weekly and referenced by every run (D-058e)
- **Per-candidate decision logs** with every gate's inputs (D-035)
- **Tax lots**: FIFO per demat account, aggregation per PAN (D-127)
- **Three-tier ETF taxonomy** with AUTO/MANUAL/UNASSIGNED status (D-108)
- **Dry-run isolation** — every portfolio query scoped by `(account, execution_mode)` (D-041)

That last one is a schema-level invariant. So is the FIFO-per-account/aggregate-per-PAN split.
Both are cheap now and painful later.

### 🟠 Second: the broker adapter contract, as code

The 17 methods are agreed (D-066) and the capability flag is defined (D-142), but the canonical
models — what an Order, Holding, Lot, Fill, LedgerEntry actually look like across five brokers —
are not written down. Five adapters will be built against it. Writing it after adapter #1 means
adapter #1 defines it by accident.

### 🟡 Everything else can proceed in parallel

Screen specs, design system, logging format, runbook, diagrams — all genuinely useful, none
blocking. They can be written while the engine is built, and several will be better for it.

---

## 3. External blockers — not documentation

These need you, and some have lead times measured in days:

| # | Item | Blocks | Status |
|---|---|---|---|
| **B1** | 🔴 **Broker T&C review** — confirm automated order placement is permitted | **Any live trading** (D-074c) | Not started |
| **B2** | Two Elastic IPv4s procured, registered with each broker | All live trading (D-007) | Not started |
| **B3** | Supabase project created (prod + dev) | All persistence (D-073a) | Not started |
| **B4** | Broker API credentials, all five | Adapter testing (D-056a) | Partial |
| **B5** | AWS account + billing alert at $15 | Deployment (D-055f) | Not started |
| **B6** | Domain switch test — build all three, measure | Web hosting (D-055h) | Not started |
| **B7** | Declared income + slab rate per investor | Tax engine (D-119) | Not started |

**B1 is the one to start today.** It is the only item that could invalidate work already planned,
and it depends on five third parties responding.

**B3 is the cheapest unblock.** Creating the Supabase project takes minutes and unblocks all
schema work.

---

## 4. Verdict

> **Not ready for broad development. Ready for a specific, well-chosen slice — after the schema
> is written.**

### What can start immediately, and why

The dry-run architecture (D-041) makes one path genuinely independent of every external blocker:

```
Upstox read-only  →  universe job  →  ranking  →  NAV gate  →  depth/skip
                                                                    ↓
                                                         PaperOrderGateway
```

This needs **no static IP, no order credentials, no SEBI registration, no T&C outcome** — only
market data. It exercises the most valuable and most error-prone logic in the system, against
real prices, with nothing at risk. That is the correct first slice, and it was the plan (D-054a).

### Recommended sequence

| Phase | Work | Gated by |
|---|---|---|
| **0** | **Write the database schema + adapter contract** | Nothing — start now |
| **1** | Supabase project, migrations, repo scaffold, `HttpCore` | B3 |
| **2** | Upstox read-only adapter + egress verification | B4 (Upstox only) |
| **3** | Universe job, ranking, NAV gate, taxonomy load | Phase 2 |
| **4** | Paper gateway, dry-run portfolio, daily snapshots | Phase 3 |
| **5** | Console skeleton, config screens, daily status | Phase 1 |
| **6** | Live order path, GTT cycle, reconciliation | **B1, B2** |
| **7** | Averaging, harvesting, cost of capital, tax engine | Phase 6 |
| **8** | Reports, charges model, logging archival | Phase 7 |

Phases 0–5 can be built **entirely without resolving B1, B2, B5, B6 or B7**. That is roughly
half the system, and the half where the strategy actually lives.

---

## 5. What I would write before the first line of code

Two documents, in this order:

1. **`05-data/DATABASE-SCHEMA.md`** — every table, column, type, constraint, index, with the ER
   diagram and the invariants stated as constraints rather than conventions.
2. **`03-brokers/BROKER-ADAPTER-CONTRACT.md`** — the 17 methods with canonical request/response
   models, the capability flags, and the error taxonomy.

Everything else is genuinely parallelisable.

---

## 6. Risks worth naming

| Risk | Assessment |
|---|---|
| **T&C outcome (B1)** | If a broker prohibits automated placement for its accounts, that broker is out. Unlikely given SEBI's framework explicitly contemplates retail API trading below TOPS, but it is unverified and it is the only item that could remove a broker entirely |
| **Shoonya GTT unknown** (Q-237) | Blocks Phase E only. Mitigated by the DAY-order fallback (D-142) — Shoonya can ship without GTT |
| **Groww/Shoonya have no charges API** | Reporting degrades to computed-only for two brokers. Known, documented, not blocking |
| **Config surface is large** | No defaults anywhere (D-038) means onboarding an account is a real data-entry task. The pre-flight check makes it safe, but it will feel heavy the first time |
| **Design drift during build** | 143 decisions is a lot to hold. The decision log is the guard — every module should cite the D-numbers it implements |

---

## 7. Update — 2026-09-24, after the prior-art review

Four things closed since this assessment was written:

| Was | Now |
|---|---|
| **B6** domain switch — build and measure three options | ✅ **Removed.** The Cloudflare Worker pattern answers it (D-055h withdrawn) |
| Per-account proxy — squid assumed | ✅ Narrowed: **evaluate Nginx first** (D-144), already proven in the archive |
| NSE downloads blocked by bot detection | ✅ **Solved** — Selenium/Chrome (D-145) |
| Domain undecided | ✅ **`metaalgocapital.com`** (D-148) |
| Deviation metric questioned | ✅ **Percentage, confirmed on real data** (D-149) |

One item was **added**: 🔴 **rotate the exposed Upstox credentials** (Q-242).

### The remaining list, precisely

**Blocking — must exist before the first line of application code (2 documents)**

| # | Document | Why blocking |
|---|---|---|
| 1 | `05-data/DATABASE-SCHEMA.md` | Everything persists into it. Carries invariants that are cheap now and painful later: lot-level tracking, FIFO-per-account with aggregation-per-PAN, dry-run isolation by `(account, execution_mode)`, typed cash ledger, config versioning |
| 2 | `03-brokers/BROKER-ADAPTER-CONTRACT.md` | Five adapters get built against it. Written after adapter #1, adapter #1 defines it by accident |

**Parallel — useful, none blocking (≈14 documents)**

Architecture (system overview, run lifecycle, module map) · Infrastructure (AWS topology,
static-IP design, Lambda/Telegram, deployment) · Strategy consolidation (buy logic, averaging,
harvesting, order lifecycle, universe construction) · Web (UI architecture, screen specs, design
system, auth) · Observability (logging spec, archival) · Reporting (charges model, unified P&L,
report specs) · Security (threat model, secrets) · Ops (runbook, testing strategy) · Diagrams.

**External — needs the operator, with lead times**

| # | Item | Blocks | Urgency |
|---|---|---|---|
| **X1** | 🔴 Rotate exposed Upstox key/secret | — | **Today** |
| **X2** | 🔴 Broker T&C review, all five | Any live trading | **Start now** — five third parties |
| **X3** | Supabase project (prod + dev) | All persistence | Cheapest unblock, minutes |
| **X4** | AWS account + billing alert at $15 | Deployment | Before phase 1 |
| **X5** | Two Elastic IPv4s, registered per broker | Live trading | Before phase 6 |
| **X6** | Broker API credentials, five | Adapter testing | Per phase |
| **X7** | Declared income + slab per investor | Tax engine | Before phase 7 |

**Information still to gather (none blocking phases 0–5)**

Rate limits for Upstox, Groww, Shoonya · token lifetimes for Zerodha, Shoonya · IP whitelisting
procedure per broker · **Shoonya GTT endpoint and alert-type enum** (Q-237, mitigated by the DAY
fallback D-142) · Groww Smart Order payload (Q-233) · whether Groww and Shoonya expose any
ledger or charges API (Q-234, Q-238) · API subscription costs (Q-224) · NSE ETF tick size
(Q-179).

Most require the broker developer portals, which are egress-blocked here — faster for the
operator to check directly.

### Verdict, unchanged

**Two documents stand between here and writing code.** Everything else proceeds in parallel, and
phases 0–5 need none of X2, X4, X5 or X7.
