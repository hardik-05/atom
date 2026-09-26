# Sell Logic

**Status:** 🟢 Specified
**Implements:** D-063 … D-066 · **restores D-003 (GTT), withdrawing D-060**

---

## 1. GTT, with a mandatory cancel-all first (D-063)

> "If you go ahead with GTT and implement one change — you cancel all the sell orders right
> before doing anything. Every day you cancel each and every sell order, then validate the
> order queue is fresh, then start running the engine. That way the GTT considers the average
> buy price for the action that happened yesterday. If for two days the user was not able to
> run the engine, this will not lose us selling our securities at profit."

**GTT is reinstated.** D-060 (remove GTT) is withdrawn; D-003 is restored with one addition
that removes the reason it was dropped.

### Why this resolves the staleness problem

GTT was removed because a resting order goes stale the moment a position is averaged. But
averaging only ever happens **during a run** — so if every run begins by cancelling every
resting sell and then re-placing from freshly computed averages, a stale GTT cannot survive a
run. Between runs, the resting GTT is by definition consistent with the last run's state.

The benefit that removal sacrificed is recovered in full: **a position stays protected on days
the engine is not run.** Miss two days and the target can still be hit and filled.

### The run sequence

```
1. CANCEL      cancel every ATOM-placed GTT sell order for this account
2. VERIFY      re-read the order book; confirm the queue is clean
                 └─ any survivor → HALT, do not proceed, alert
3. HOLDINGS    read current holdings from the broker
4. EXCLUDE     subtract excluded and frozen quantities (D-062)
5. RECOMPUTE   weighted-average buy price over sellable quantity
6. PLACE       one fresh GTT sell per sellable security, at
                 round_UP_to_tick(avg_buy × (1 + profit_target_pct))
7. BUY LOOP    only now does the buy side run
```

**Step 2 is not optional.** Proceeding while an old sell order survives would leave two live
sells for one holding — the exact failure mode D-055 forbids. A failed cancellation halts the
run and alerts, rather than continuing and hoping.

> ⚠️ **Cancel only ATOM's own GTT orders — never blindly cancel everything.**
> The account may carry GTT orders the operator placed by hand, including for excluded holdings
> (D-062). A blanket "cancel all" would silently destroy them.
> **Requirement:** every GTT ATOM places is recorded with its broker-assigned ID, and only
> those IDs are cancelled. A resting sell that ATOM has no record of is **reported, not
> cancelled** — it is either a manual order to leave alone, or a reconciliation gap worth
> knowing about. See Q-184.

### 1a. GTT is a per-broker capability, with a DAY-order fallback (D-142)

> "If GTT is not available in Shoonya, let's go ahead with the normal order. Anyway at 4:15 the
> broker itself will cut down the orders, and next day we can just see if there are any orders —
> if no orders, then we can start placing."

Each adapter declares `supports_gtt`, and the sell path branches on it:

| | `supports_gtt = True` | `supports_gtt = False` |
|---|---|---|
| Order type | GTT / Forever Order | **Plain DAY limit** |
| Run start | Cancel ATOM's GTTs, verify clean, re-place | **Check the order book; place only what is missing** |
| End of day | Survives | **Broker cancels at ~16:15** |
| Protection between runs | ✅ Holds | ❌ **None** |

The run sequence is unchanged in shape — the fallback simply finds an empty book most mornings,
because the broker cleared it overnight, and places a fresh DAY limit for every sellable holding.

> ⚠️ **The trade-off D-063 was created to avoid returns for these brokers, and only these.**
> A DAY order dies at 16:15, so on any day the engine is not run, a position at a
> `supports_gtt = False` broker is **unprotected** — if the target is hit, the sale does not
> happen. That is acceptable as a broker-specific limitation but it is not a free choice:
> **those accounts require a daily run**, and the console should say so against them.

*Capability flags, not broker names, drive this. The strategy code never asks "is this
Shoonya?" — it asks "does this adapter support GTT?" That is what keeps broker #6 a
configuration change.*

### Consequences for the broker layer

GTT support is back in scope for all five adapters, and its uneven semantics return with it:
validity periods, modification rules, and whether a GTT survives the underlying holding being
sold by other means. This is documented per broker in the capability matrix. ATOM only ever
**places** and **cancels** GTTs — never modifies them — which keeps the required surface
minimal even where broker behaviour differs.

## 2. One sell order per security — **amended: one per tranche** (D-055, amended by D-195)

> ⚠️ **D-055's "never two" now has exactly one exception.** Where a harvest proxy has been
> averaged, the position splits into **two tranches** with two separate targets and two separate
> GTTs. Everything else in this section is unchanged, and for the overwhelming majority of
> instruments there is still exactly one sell order.
>
> | Tranche | Lots | Target |
> |---|---|---|
> | **S — synthetic** | `synthetic_cost_basis IS NOT NULL` | weighted synthetic avg × (1 + threshold) |
> | **A — actual** | `synthetic_cost_basis IS NULL` | weighted `unit_cost` avg × (1 + threshold) |
>
> **The ceiling is two, always.** Multiple synthetic lots blend with each other inside tranche S;
> only the S/A boundary splits. Blending across it would exit a proxy unit below the capital it
> is recovering and book the shortfall as a gain — see
> [`HARVEST-COST-BASIS.md`](HARVEST-COST-BASIS.md) §4.1 for the worked failure.
>
> **Consequence for the sell pass:** it emits a *list of tranches* per instrument, not a single
> order. An instrument with no synthetic lots yields a one-element list, which is today's
> behaviour exactly. D-156 already requires multiple GTTs per instrument and D-164 confirmed all
> five brokers support it, so no new broker capability is needed.
>
> **Consequence for the cancel-all-first step:** the reconciliation below must expect **up to two**
> ATOM sell orders per instrument. A second recorded GTT on one instrument is normal, not a
> duplicate to halt on.

Never two — except per the amendment above. At the start of each run, reconcile against the broker's order book:

Because step 1 cancels every ATOM sell order before anything else, each run starts from a
clean book by construction. The remaining cases are:

| Found after the cancel pass | Action |
|---|---|
| Nothing resting | Normal — place the fresh GTT |
| An ATOM order that failed to cancel | **HALT the run** and alert (step 2) |
| A sell ATOM has no record of | **Leave it, report it** — manual order or reconciliation gap |

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
| ~~Q-177~~ | ✅ Withdrawn — GTT reinstated (D-063), so positions stay protected on non-run days |
| Q-184 | Confirm: cancel only ATOM-recorded GTT IDs, and report rather than cancel unrecognised resting sells |
| Q-185 | Per broker: does cancelling a GTT return a synchronous confirmation, or must the order book be re-polled to verify? Affects step 2 |
| Q-178 | Per broker: where and when DP charges surface (P&L vs ledger, same-day vs T+n) — round 2 research |
| Q-179 | Tick size per ETF — is ₹0.01 universal on NSE ETFs, or does it vary by price band? (see also Q-300 — Upstox reports tick size in paise in JSON but rupees in its deprecated CSV) |
| Q-296 | When a two-tranche position is partially sold, which tranche's GTT is re-placed first on the next run? Proposed: synthetic first, since it is the older capital |
