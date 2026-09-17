# Sell Logic

**Status:** 🟢 Specified
**Implements:** D-054 … D-058 · **supersedes D-003 (GTT)**

---

## 1. GTT is removed from the design (D-054)

> "This brings up a very important question about GTT. A GTT is triggered, and when you average,
> the GTT order still stays intact. So let's get rid of GTT — only place limit orders, so every
> morning when you run, you place fresh sell orders based on your computation. Some brokers
> offer GTT, some do not. Every morning, fresh limit orders, and by default by 4:15 the broker
> cancels them."

**Decision reversed.** D-003 chose GTT-where-supported with a DAY fallback. That is now
withdrawn. ATOM places **plain DAY limit sell orders only**.

### Why the reversal is correct

| Problem with GTT | Consequence |
|---|---|
| **A resting GTT goes stale on averaging** | Averaging changes the weighted-average buy price, so the old target is wrong. A GTT placed weeks ago silently sells at the pre-averaging target |
| Cancel-and-replace is required anyway | Any position that averages needs its GTT cancelled and rewritten — so the "set and forget" benefit evaporates exactly where it mattered |
| Broker support is uneven | Five brokers, five sets of GTT semantics, validity rules and modification quirks — the largest single source of adapter divergence |
| GTT state lives at the broker | ATOM's view and the broker's view can drift with no reconciliation point |

**Placing fresh orders each morning eliminates all four.** The target is always computed from
the current average buy price, on current holdings, under the current config.

### The daily cycle

```
Morning run
  ├── read holdings from the broker
  ├── apply exclusions and freezes (§3)
  ├── recompute weighted-average buy price per security
  ├── compute target = avg_buy_price × (1 + profit_target_pct)
  ├── round UP to the nearest valid tick
  └── place ONE DAY limit sell per sellable security

15:30  market closes
~16:15 broker cancels all unfilled DAY orders

Next morning — repeat, on whatever the holdings now are
```

**Consequence to accept:** a position is **unprotected on any day the engine is not run**. If
the target is hit on a day you do not start the engine, the sale does not happen. This is the
deliberate trade-off for always-correct pricing, and it makes running the engine every trading
day an operational requirement rather than an option.

*This also materially simplifies the broker layer — no GTT endpoint, no GTT semantics, no GTT
reconciliation in any of the five adapters.*

---

## 2. One sell order per security (D-055)

Never two. At the start of each run, reconcile against the broker's order book:

| Found | Action |
|---|---|
| No resting sell | Place one |
| Resting sell, correct price and quantity | Leave it |
| Resting sell, wrong price or quantity | **Cancel and replace** |
| Resting sell for an excluded/frozen quantity | Cancel down to the sellable quantity |

In practice DAY orders expire overnight, so most runs start from a clean book. The
reconciliation exists for same-day re-runs and for orders placed by other means.

---

## 3. Sellable quantity comes from exclusions

```
sellable_quantity = holding_quantity − excluded_quantity − frozen_quantity
```

If `sellable_quantity ≤ 0`, no sell order is placed. See
[`EXCLUSION-AND-FREEZE.md`](./EXCLUSION-AND-FREEZE.md).

**The weighted-average buy price is recomputed on every run**, over the sellable quantity only,
from ATOM's own lot records (D-045). Never cached, never taken from a previous run.

---

## 4. Target price (D-056)

```
target      = weighted_avg_buy_price × (1 + profit_target_pct)
limit_price = round_UP_to_tick(target)
```

Rounding is always **up**, so the realised percentage is never below target.

`profit_target_pct` is config per (trading account × category), with no default (D-038).

---

## 5. What "profit" means (D-057)

> "In profit, consider your selling price, buying price and the charges as well as the
> depository charges. Cost of capital should not be part of profit, and tax should not be part
> of profit."

```
PROFIT  =  sell_value − buy_value − brokerage − STT − exchange fees
                      − SEBI fees − stamp duty − GST − depository (DP) charges
```

**Excluded from profit, reported separately:**

| Item | Where it appears |
|---|---|
| **Cost of capital** | Cost of Capital screen — `True Profit = Profit − cost of capital` |
| **Settlement interest** | Cost of Capital screen, its own line |
| **Tax / STCG** | Tax screens only |

> ⚠️ **DP charges are the hard part.** Some brokers include depository charges in the P&L
> statement; others expose them only in the ledger, often days later. Profit is therefore not
> final at the moment of sale for every broker. Each adapter must declare **where** DP charges
> surface and **when**, and the UI must distinguish a provisional profit from a reconciled one.
> This feeds the charges model (D-024) and is in the round 2 broker research scope.

---

## 6. Sell orders always run

Sells are placed for every sellable holding **regardless of `category_enabled`**. Disabling a
category suppresses **buying only**.

---

## 7. Open items

| ID | Item |
|---|---|
| Q-177 | Is a position left unprotected on a non-run day acceptable, or should a "sells-only" quick run mode exist for days you do not want to buy? |
| Q-178 | Per broker: where and when DP charges surface (P&L vs ledger, same-day vs T+n) — round 2 research |
| Q-179 | Tick size per ETF — is ₹0.01 universal on NSE ETFs, or does it vary by price band? |
