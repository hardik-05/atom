# Charges Model

**Status:** 🟡 Structure specified · **rates require verification before go-live** (§5)
**Date:** 2026-09-26
**Basis:** D-024 (contrast view) · D-076a (`unit_cost` is all-in) · D-105 · D-179 · D-186

> ATOM computes every charge itself, and — where the broker publishes it — shows the reported figure
> beside it. Both rows coexist in `atom.charge` with a `source` of `COMPUTED` or `BROKER`. That
> contrast *is* the feature; a single number would hide which one it is.

---

## 1. Why ATOM computes charges at all

Three reasons, each independently sufficient:

1. **Two brokers cannot report per-order charges** (Upstox gives period totals, Shoonya nothing), so
   a broker-only model would leave two of five accounts with no charge attribution.
2. **`position_lot.unit_cost` is all-in** (D-076a) and must be known **at the moment the lot is
   created** — before any broker has reported anything.
3. **Dry-run mode has no broker** to report from (D-045), and dry-run charges must be real enough to
   compare against live.

So computation is the primary path and reporting is the check, not the other way round.

---

## 2. The components

`atom.charge.charge_type` — a closed set:

| Type | Applies | Basis |
|---|---|---|
| `BROKERAGE` | both sides | Per broker's plan; often ₹0 for delivery |
| `STT` | ⚠️ see §5.1 | Securities Transaction Tax |
| `EXCHANGE` | both sides | Exchange transaction charge, on turnover |
| `SEBI` | both sides | SEBI turnover fee |
| `STAMP` | **buy only** | State stamp duty, on turnover |
| `GST` | both sides | 18% on (`BROKERAGE` + `EXCHANGE` + `SEBI`) — **not** on STT or stamp duty |
| `DP` | **sell only** | Depository charge, flat per scrip per day |

### 2.1 Two rules that are easy to get wrong

**GST applies to services, not to taxes.** It is 18% of brokerage plus exchange plus SEBI turnover
fees. Applying it to STT or stamp duty would overstate charges — and since brokerage on delivery is
often ₹0, GST is frequently a rounding artefact on a tiny base.

**DP charges are flat per scrip per day, not per order or per unit.** Selling the same ETF twice in
one day incurs one DP charge; selling three different ETFs incurs three. ATOM places at most one
sell order per tranche per instrument per day, so in practice: **one DP charge per instrument sold,
per account, per day** — which must be attributed at the *instrument* level and not multiplied by
fills.

This is where Q-178 mattered, and it is now answered for one broker: **Upstox is the only broker that
names DP charges in its API** (`charges.demat_transaction`). Elsewhere it is computed only.

---

## 3. Computation

```python
turnover = quantity × fill_price          # per fill

brokerage = min(plan.pct × turnover, plan.cap)      # per broker
stt       = rate_for(instrument_class, side) × turnover     # ⚠️ §5.1
exchange  = exch_rate × turnover
sebi      = sebi_rate × turnover
stamp     = stamp_rate × turnover if side == BUY else 0
gst       = 0.18 × (brokerage + exchange + sebi)
dp        = dp_flat if side == SELL else 0           # once per instrument per day
```

| Rule | |
|---|---|
| `Decimal` throughout | Never `float` — these are money |
| Rounded to **4dp**, displayed at 2 | D-026 |
| **Every rate is configuration**, not code | D-037: no defaults; an unset rate blocks the run |
| Rates are **versioned** | `config_history`, so a past run reprices with the rates of its day |
| Per-fill, then summed per order | The lot grain is the fill (D-166) |

**Rates as versioned configuration is not over-engineering.** Charge rates change by government
circular — GST rates, STT rates and exchange charges have all moved in the last few years — and a
report for last year must use last year's rates or it is simply wrong. Hardcoding them would make
historical reports silently drift.

---

## 4. Reported charges, per broker

What each broker can actually be asked, established from their documentation:

| Broker | Per-order | Components | Endpoint | Contrast possible |
|---|---|---|---|---|
| **Dhan** | ✅ | ✅ 6 fields | `GET /v2/trades/{from}/{to}/{page}` | **Per fill, per component** |
| **Zerodha** | ✅ | ✅ 6 + GST split | `POST /charges/orders` | **Per fill, per component** — and it prices **imaginary** orders (D-186) |
| **Upstox** | ❌ period | ✅ incl. **DP** | `GET /v2/trade/profit-loss/charges` | **Period level only** |
| **Groww** | ✅ | ❌ aggregate | `brokerage_and_charges` | Total only |
| **Shoonya** | ❌ | ❌ | — | **Computed only** |

**Upstox and Groww have exactly opposite gaps** — components without attribution, and attribution
without components. Neither alone supports a per-fill component contrast.

### 4.1 Zerodha's calculator is usable three ways

`POST /charges/orders` accepts an arbitrary `order_id` — "it can be any random string to calculate
charges for an imaginary order". So it serves as:

1. **Pre-trade estimate** on the execution list, before the operator releases
2. **Dry-run charges** from the broker's own calculator rather than ATOM's model
3. **Post-trade actual**, called with the achieved `average_price`

Both (1) and (3) land in `atom.charge` — as `COMPUTED` and `BROKER` respectively — which gives
Zerodha a genuine estimated-vs-actual contrast without waiting for a statement.

### 4.2 Degradation is displayed, never silent

Where a broker supplies nothing, the reported column shows **`—` with a tooltip naming the
limitation**. Never `₹0.00`.

> `₹0.00` reads as "no charge was levied". `—` reads as "we cannot know". Those are different facts
> and conflating them would make the contrast view actively misleading — which would be worse than
> not having it.

---

## 5. 🔴 Rates that must be verified before go-live

The structure above is sound. The **numbers** are not yet verified from primary sources, and two of
them could be materially wrong.

### 5.1 🔴 STT on ETFs is probably not the equity-share rate — Q-313

Delivery equity **shares** attract STT at **0.1% on both buy and sell**. But an ETF is a *unit of a
scheme*, and units of an **equity-oriented fund** sold on an exchange attract STT at **0.001% on the
sell side only**.

**That is a 100× difference on the sell side and possibly nothing on the buy side.** On a ₹20,000
sell it is the difference between ₹20 and ₹0.20.

And it very likely **splits by ETF category**, which ATOM already classifies (D-101):

| Bucket | Likely STT treatment | Confidence |
|---|---|---|
| INDEX / SECTOR / FACTOR (equity ETFs) | Equity-oriented fund units — 0.001% sell only | Medium |
| COMMODITY (gold, silver) | **Not** equity-oriented — different treatment | Low |
| GLOBAL (overseas funds-of-funds) | **Not** equity-oriented | Low |

This mirrors the taxation model, which already treats the three classes differently (equity STCG 20%
flat vs commodity/global at slab). It would be consistent for STT to split the same way — but
consistency is not evidence.

> **I am not going to assert these rates.** Getting STT wrong by 100× would corrupt every `unit_cost`,
> every realised P&L figure and every charges contrast. The rate table must be built from the Finance
> Act schedule and each broker's published charge list, and **validated against a real contract
> note per ETF category** before live trading. Until then the configured rates are provisional and
> the charges screen should say so.

### 5.2 Other rates to confirm

| Item | Question |
|---|---|
| Exchange transaction charge | NSE cash-segment rate, and whether ETFs differ from shares — **Q-314** |
| SEBI turnover fee | Current rate per crore — **Q-315** |
| Stamp duty | 0.015% on buy is the common figure; confirm it applies to ETF units and is uniform post-2020 — **Q-316** |
| DP charge | Flat amount **per broker** (varies), and which brokers waive it — **Q-317** |
| Brokerage | Each broker's delivery plan, including whether ETFs are treated as delivery equity — **Q-318** |

### 5.3 How the rates get validated

The cheapest reliable method, and it is already available:

1. Configure provisional rates
2. Place **one small real order per ETF category, per broker**
3. Compare ATOM's computed breakdown against the broker's reported one (Dhan and Zerodha give both
   per component)
4. Correct the rate table; re-run the comparison until it matches to the paisa

**Dhan and Zerodha make this a measurement rather than a research exercise** — which is a concrete
argument for onboarding those two first (`MODULE-MAP.md` §7).

---

## 6. Where charges land

| Consumer | Uses | Basis |
|---|---|---|
| `position_lot.unit_cost` | Buy-side charges, **all-in** (D-076a) | actual |
| `lot_closure.unit_proceeds` | Net of sell-side charges | actual |
| Realised P&L | Both sides | actual |
| Tax computation | Both sides — charges are part of cost of acquisition and transfer expenses | actual |
| Charges screen | Computed **and** reported | both |
| Cost of capital | ❌ **not** a charge | separate (D-057) |

**Cost of capital is not a charge** and never enters `atom.charge`. It is the cost of the *programme*,
not of the trade, and it is reported on its own screen (`COST-OF-CAPITAL.md`).

---

## 7. Open items

| ID | Question | Severity |
|---|---|---|
| **Q-313** | 🔴 STT rate for ETF units, per bucket — equity-oriented vs commodity vs global | **Blocks accurate `unit_cost`** |
| Q-314 | NSE exchange transaction charge for ETFs | High |
| Q-315 | Current SEBI turnover fee | Medium |
| Q-316 | Stamp duty on ETF units, buy side | Medium |
| Q-317 | DP charge per broker, and waivers | Medium |
| Q-318 | Each broker's delivery brokerage plan for ETFs | Medium |
| Q-178 | 🟡 DP charge visibility — answered for Upstox (`demat_transaction`); computed elsewhere | Closed enough |
| Q-273 | 🟡 Per-broker charge availability — fully mapped in §4 | Closed |
