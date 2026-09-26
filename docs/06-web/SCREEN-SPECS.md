# Screen Specifications

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Conventions:** [`DESIGN-SYSTEM.md`](DESIGN-SYSTEM.md) — every number carries its basis and source

Thirteen screens. Account and universe are **global header context** (D-069c); each screen reads
them rather than carrying its own selector.

| # | Screen | Purpose |
|---|---|---|
| 1 | [Overview](#1-overview) | Is everything healthy, and what happened today |
| 2 | [Execute Engine](#2-execute-engine) | Run a universe; review and release orders |
| 3 | [Universe](#3-universe) | Membership, snapshots, peer comparison |
| 4 | [Holdings](#4-holdings) | Lots, tranches, reconciliation |
| 5 | [Orders](#5-orders) | Order and GTT book, fills |
| 6 | [Harvest](#6-harvest) | Pair a loss with a proxy |
| 7 | [Cash](#7-cash) | Typed cash movements |
| 8 | [Reports](#8-reports) | P&L by period, three bases |
| 9 | [Charges](#9-charges) | Computed vs reported contrast |
| 10 | [Tax](#10-tax) | Gains, set-off, exemption, liability |
| 11 | [Config](#11-config) | Resolved configuration and history |
| 12 | [Logs](#12-logs) | Run logs and candidate audit |
| 13 | [Dry Run](#13-dry-run) | The paper-trading subsystem |

---

## 1. Overview

**Answers:** *is anything broken, and what did today do?*

| Block | Content |
|---|---|
| Health strip | Engine state · egress IP ✓/✗ per account · token state per account · idle countdown |
| Today's runs | One row per `(account, universe)`: mode, status, orders, fills, skips |
| Stat tiles | Deployed · Settlement · Idle capital · today's realised · open positions |
| Attention list | Negative residuals · failed gates worth knowing · pending execution-list items · unresolved partial harvests |

**Pre-flight state is on the landing screen, not buried.** A wrong egress IP is a week-long outage on
Dhan (D-173) and an invalid token blocks everything — both must be visible before the operator tries
to run anything, not discovered by a failure.

The attention list is empty on a normal day. That emptiness is the signal.

---

## 2. Execute Engine

**Answers:** *what would ATOM do, and do I release it?* The three-stage flow (D-070b): **block →
review → release.**

```
① SELECT      account · universe(s) · mode (inherited, shown not chosen)
       ▼
② PRE-FLIGHT  egress ✓  token ✓  calendar ✓  sell-auth ✓     ← all four must pass
       ▼
③ PROPOSE     sell tranches + buy candidates, every gate shown
       ▼
④ REVIEW      operator inspects; can exclude individual lines
       ▼
⑤ RELEASE     explicit action → orders sent → live status
```

### Proposal table

| Column | Notes |
|---|---|
| Instrument | symbol + ISIN (mono) |
| Side | BUY / SELL |
| Tranche | `—` · `SYNTHETIC` · `ACTUAL` — **only shown when a synthetic tranche exists** |
| Mean / LTP / Deviation | deviation signed, 2dp, coloured |
| Basis | `<BasisLabel>` when synthetic |
| Qty | with the `floor` arithmetic in a tooltip: `₹20,000 × 99% ÷ ₹2,440 = 8.11 → 8` |
| Limit price | rounded to **ATOM's** tick (D-209) |
| Gates | `GateChip` per gate, with values |
| Est. charges | from the broker's calculator where available (Zerodha, Groww), else computed |
| Decision | BOUGHT / SKIPPED / NOT_CONSIDERED + reason |

**Skipped candidates are shown, not hidden.** *Why didn't it buy X?* is the most common question a
system like this has to answer, and hiding the row makes it unanswerable from the UI.

Suggested values are **pre-fills the operator must confirm** (D-039) — never applied silently.

---

## 3. Universe

| Tab | Content |
|---|---|
| Members | Current membership; bucket/tier classification; volume and liquidity |
| History | SCD-2 timeline — *what was in this universe on any date* |
| Snapshots | Frozen weekly snapshots; two CSVs downloadable (D-058g) |
| Config | Universe-level overrides, showing what they override |
| **Peer comparison** | Universes side by side: return, deviation capture, charges, cost of capital, turnover |

Peer comparison is the reason universes exist as an entity. Horizontal bars plus a table, **all
returns on the same basis**, with the basis named — comparing a synthetic-basis return against a
cash-basis one would be meaningless.

---

## 4. Holdings

**Answers:** *what do we hold, at what basis, and do the books agree?*

| Column | Notes |
|---|---|
| Instrument | symbol + ISIN |
| Total qty | the ownership figure |
| **Free qty** | the sellable figure — `—` where the broker does not publish it, **with a tooltip saying so** |
| T1 / Pledged | unsettled and encumbered |
| Actual avg | `<Money basis="cash">` |
| **Synthetic avg** | shown **always**; identical to actual for most rows (D-197) |
| Deviation | against synthetic |
| Lots | count; expands to a drawer |
| Residual | `0` normal · `>0` warn · `<0` 🔴 blocks the run |
| Flags | frozen · excluded · **proxy applied** · discrepancy (Zerodha) · not sellable |

**Both averages on every row.** For most of the universe they match, and that sameness is what tells
the operator at a glance which holdings carry a harvest history (D-197).

Lot drawer: one row per lot — acquired date, qty, open qty, `unit_cost`, `synthetic_cost_basis`,
provenance (`ATOM` / `EXTERNAL`), universe, and the `harvest_chain` link where one exists.

---

## 5. Orders

| Tab | Content |
|---|---|
| Today | `order_request` rows: intent → placed → filled/rejected, with verbatim `reject_reason` |
| GTT book | Resting GTTs, **ours vs unrecognised** clearly separated |
| Fills | One row per fill, with the lot it created |
| Execution list | Deferred work queued for a later run (D-022) |

**The GTT split is load-bearing.** ATOM cancels only its own (D-064), and on Zerodha an active GTT
carries no ATOM identifier at all (D-176) — so an unrecognised resting sell is either the operator's
own order or a reconciliation gap, and the screen must let them tell which. This is also the only
place an orphaned Zerodha GTT can be spotted, because there is no API path to recover one.

---

## 6. Harvest

| Block | Content |
|---|---|
| Candidates | Loss-making positions: unrealised loss, holding period, **12-month proximity warning** |
| Ineligible | Positions excluded, **with the reason** — most commonly *"already a harvest proxy; cannot be re-harvested"* (D-193) |
| Proxy picker | Any instrument in the **same universe** (D-163, Q-287); manual choice, no correlation matching in v1 |
| Preview | Loss booked · carried basis amount · resulting synthetic basis per unit · the two resulting sell tranches |
| Confirm | `ConfirmDialog` stating the consequence; writes `action_audit` |
| Chain view | `harvest_chain`: sold lot → proxy lot, booked loss, carried amount |

The preview shows the **arithmetic**, because the carried basis is an amount and the per-unit figure
is derived:

```
Harvested   X   20 units · actual cost ₹1,900 · sold at ₹86 → loss ₹180
Proxy       Y   20 units at ₹86
Carried     ₹1,900  →  synthetic basis ₹95.00/unit
Tranches    SYNTHETIC 20 @ target ₹98.33     (no ACTUAL tranche yet)
```

**"No proxy available" states the reason** rather than showing an empty list (D-163 discussion).

---

## 7. Cash

Cash movements are **typed by the operator** (D-078 discussion), never inferred.

| Type | Meaning |
|---|---|
| `DEPOSIT` | Capital in — starts accruing cost of capital |
| `WITHDRAWAL` | Repayment to the firm |
| `SETTLEMENT` | Sale proceeds landing — **observed, never assumed** (D-050/D-080) |
| `CHARGE` | Broker debit |
| `UNKNOWN` | Unrecognised; awaiting classification |

Where a broker provides a ledger (**Dhan only**), the screen shows a **reconciliation panel**:
ATOM's computed `principal_outstanding` against Dhan's `runbal`. Unmapped `voucherdesc` values
surface as `UNKNOWN` for the operator to classify (Q-276) — never guessed, because a
misclassification corrupts the cost-of-capital model silently.

---

## 8. Reports

Period selector; three tiers (D-169).

| Tier | Contains |
|---|---|
| **Universe** | Pure P&L — bought, sold, realised, unrealised, charges, cost of capital on *its own* deployed + settlement |
| **Account** | The above summed, **plus idle drag**, total principal, capital efficiency |
| **Investor (PAN)** | Tax only |

**Three return figures, always together** (D-190):

| | vs | Answers |
|---|---|---|
| Strategy return | synthetic | *Are we above the capital we committed?* |
| Cash return | actual | *What did this money actually do?* |
| Taxable gain | actual, tax FIFO | *What does the tax engine see?* |

Closed trades list each lot's holding period, cost of capital and charges. **Cost of capital and tax
are excluded from profit** and reported separately (D-057 discussion) — they are costs of the
programme, not of the trade.

Also here: the **ATOM vs Broker contrast** page (D-020) — expandable by date, showing per affected
trade what ATOM did, what ATOM's books say, and what the broker shows. It exists because the
synthetic basis makes the two legitimately disagree until a position closes.

---

## 9. Charges

The contrast view (D-024, D-179), and an honest one.

| Column | |
|---|---|
| Component | Brokerage · STT · Exchange · SEBI · Stamp · GST · DP |
| Computed | ATOM's model, `SourceBadge computed` |
| Reported | Broker's figure, `SourceBadge broker` — **`—` where unavailable** |
| Difference | Only where both exist |

Per-broker fidelity is stated on the screen, not assumed:

| Broker | Per-order | Components | Contrast available |
|---|---|---|---|
| Dhan | ✅ | ✅ | Per fill, per component |
| Zerodha | ✅ | ✅ | Per fill, per component (+ pre-trade estimates) |
| Upstox | ❌ period | ✅ incl. DP | **Period level only** |
| Groww | ✅ | ❌ | Total only |
| Shoonya | ❌ | ❌ | **Computed only** |

> A `—` with a tooltip, never `₹0.00`. Showing zero where a broker supplies nothing would read as
> "no charges were levied", which is false.

---

## 10. Tax

| Block | Content |
|---|---|
| Gains | `tax_gain` rows under **tax FIFO**, with `provenance` (ATOM / EXTERNAL, D-123) |
| Term split | STCG / LTCG per asset class — equity 20% flat, commodity/global at slab, all LTCG 12.5% |
| Loss pool | By term and vintage, 8-year window, with expiry dates |
| Set-off | How each loss was applied, in legal order (`sequence_no`) |
| Exemption | ₹1.25 L per PAN per FY, **equity only**, with a hard cap |
| Liability | Computed, recomputed as trades land |

**Total gains and ATOM gains shown separately** (D-070c): set-off uses ATOM's gains only, but the
display shows all gains, because the investor's tax position includes trades ATOM did not make.

A banner states plainly that this is a computation, not advice, and that the figures depend on the
declared slab (**X7**).

---

## 11. Config

| Tab | Content |
|---|---|
| Resolved | The effective value of every key for the selected scope, **with which level supplied it** |
| Hierarchy | Global → broker → account → universe → category, showing overrides |
| History | `config_history` — who changed what, when, from what to what |
| Run snapshots | The frozen `config_snapshot` of any past run (D-061) |

**No defaults anywhere** (D-037). A key with no value is shown as *unset* and blocks the run that
needs it — it does not silently fall back.

The run-snapshot tab is what makes a year-old decision explicable: it shows the thresholds as they
were that day, not as they are now.

---

## 12. Logs

| Tab | Content |
|---|---|
| Runs | `run` rows; drill into phases and timings |
| Candidates | `run_candidate` — every instrument, every gate input and verdict, decision + reason |
| Structured | `run_log` rows, filterable by level and phase |
| Files | Detailed `.log` downloads; also pushed to Telegram (D-031) |
| Actions | `action_audit` — every operator override, with reason |

The candidates tab is D-035 made visible: the decision is reconstructible **without reading a log
file**.

---

## 13. Dry Run

Dry running is a first-class subsystem (D-041), so it gets its own screen.

| Block | Content |
|---|---|
| Per-account mode | `DRY` / `LIVE`, and the promotion control |
| Price source | Which source dry runs use (configurable, D-041) |
| Simulated fills | What `DryGateway` filled, at what price, with what slippage assumption |
| Charges | Computed, plus the broker's calculator where it prices imaginary orders (**Zerodha**, D-186) |
| Paper vs live | Confirmation that the two books never mix (`execution_mode` on the account, D-041) |

Promotion to `LIVE` requires: a passing pre-flight, at least one completed dry run, and — where the
broker needs it — sell authorisation done (Upstox EDIS / Zerodha DDPI or CDSL).

---

## 14. Cross-screen rules

| Rule | |
|---|---|
| Account + universe are header context | Never a per-screen selector |
| Every number carries basis and source | `<BasisLabel>` · `<SourceBadge>` |
| `DRY` shows an undismissable strip | |
| Drill-down opens a drawer | The list keeps its scroll position |
| Every table exports CSV | |
| Empty states explain *why* | Never "no data" |
| Audited actions use `ConfirmDialog` | And state the consequence, not "are you sure?" |
| Engine offline keeps cached data, timestamped | Never a blank screen |
