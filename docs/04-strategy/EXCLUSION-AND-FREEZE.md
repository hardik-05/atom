# Exclusion and Freeze

**Status:** 🟢 Specified · **new requirement**
**Implements:** D-058

---

## 1. The problem

ATOM does not own the broker account. The same account can hold:

- positions **ATOM bought** under the strategy,
- positions the user bought **manually** — including *more of the same ETF*,
- entirely unrelated holdings (individual shares, other instruments).

Without a guard, the morning sell pass would place a limit sell over **everything it finds**,
including holdings that were never the strategy's to touch.

> "The same account — user can buy some stocks and we do not want to place a sell order for
> them. Or the user might buy the same ETF manually and not want to sell that."

---

## 2. The rule

```
sellable_quantity = holding_quantity − excluded_quantity − frozen_quantity
```

- `sellable_quantity > 0` → place one DAY limit sell for exactly that quantity
- `sellable_quantity ≤ 0` → place nothing, log the reason

**Default behaviour is to sell.** If a holding appears and has no exclusion entry, ATOM
**does** place a sell at that account's configured percentage:

> "If something is not there in the exclusion system but appears in the holdings, make sure you
> sell it off at the required percentage."

This is a deliberate fail-forward: the strategy keeps working on anything it finds, and the
operator opts specific quantities *out*.

> ⚠️ **Operational consequence.** A manual purchase made *before* an exclusion is recorded will
> be sold by the next run. The exclusion entry must be made **before** the next run, and the
> screen should say so plainly.

---

## 3. Two mechanisms, deliberately distinct

| | **Exclusion** | **Freeze** |
|---|---|---|
| Applies to | Quantity ATOM did not buy | Quantity ATOM **did** buy |
| Meaning | "This was never the strategy's" | "Hold this; don't sell it yet" |
| Typical use | Manual purchase of the same ETF, or an unrelated share | Conviction hold on a strategy position |
| Effect on cost basis | Removed from ATOM's average entirely | Removed from the **sellable** average |
| Typical lifetime | Permanent | Temporary |
| Cost of capital | **Never accrues** — not ATOM capital | **Accrues** — deployed ATOM capital |
| Expected frequency | The normal case | "Highly unlikely" — rare, per the operator |

Both reduce sellable quantity; separating them keeps the reporting honest about what the
strategy actually did.

### Worked example — exclusion

Holding: 130 NIFTYBEES. ATOM bought 100; you bought 30 yourself.
Record an exclusion of **30**. Sellable = 100. The 30 are never sold, and never enter ATOM's
average or its P&L.

### Worked example — freeze

Holding: 100 NIFTYBEES, all bought by ATOM. You want to keep half.
Freeze **50**. Sellable = 50, and **the average buy price is recomputed over the 50 sellable
units** before the target is calculated — not over all 100.

---

## 4. The Exclusion screen

| Element | Behaviour |
|---|---|
| **Account selector** | Per trading account (D-037) |
| **Search** | By symbol **or ISIN**, across current holdings |
| **Per row** | Symbol, ISIN, total quantity, quantity bought by ATOM, quantity unidentified, already excluded, already frozen, **sellable** |
| **Exclude** | Enter a quantity to exclude (≤ total) |
| **Freeze** | Enter a quantity to freeze (≤ ATOM-bought quantity) |
| **Release** | Remove an exclusion or freeze; the quantity becomes sellable from the next run |
| **Validation** | `excluded + frozen ≤ holding_quantity`, always |

Entries are **quantities, not flags** — partial exclusion of a holding is the normal case.

---

## 5. Provenance flags on the Holdings screen

Every holding is labelled:

| Flag | Meaning |
|---|---|
| **`ATOM`** | Matched to an ATOM order in our own records |
| **`UNIDENTIFIED`** | Present at the broker with no matching ATOM order |

> "All the trades which you are not able to identify as part of your process should go as
> unidentified. The other ones should have a flag like 'bought by ATOM'."

Where a holding's quantity **exceeds** what ATOM bought, the row splits: the ATOM quantity and
the unidentified remainder are shown separately, since each is treated differently.

Provenance is **derived by reconciliation**, not asserted: ATOM's order and lot records are
matched against broker holdings by symbol and quantity. An unidentified quantity appearing
where ATOM expected none is a **reconciliation signal** and should be surfaced, not absorbed —
it may mean an order filled that ATOM never recorded.

---

## 6. Interaction with the rest of the system

| Area | Effect |
|---|---|
| **Sell logic** (D-054) | Sells only the sellable quantity, at an average recomputed over it |
| **Buy logic** | The holdings-skip check uses the **whole broker account** (Q-059b) — an excluded ETF still counts as held and is still skipped when ranking |
| **Averaging** | Only sellable quantity is averaged; excluded quantity is untouched |
| **Cost of capital** (D-045) | **Confirmed by the operator:** frozen quantity **is** ATOM capital and continues to accrue — it is deployed, just not for sale. Excluded quantity was bought outside the system, is **not** ATOM capital, and never accrues |
| **Reports** | Excluded quantity is outside ATOM's P&L entirely; frozen quantity is inside it, held |

> The cost-of-capital row above is the subtle one: **freezing a position does not stop its
> interest clock.** Holding for conviction has a carrying cost, and the screen will show it.

---

## 7. Open items

| ID | Item |
|---|---|
| Q-180 | Should a freeze carry an optional expiry date, auto-releasing after N days? |
| Q-181 | If holdings drop below the excluded quantity (the user sold manually), auto-reduce the exclusion or flag it? |
| Q-182 | Should ATOM ever auto-create an exclusion when it detects an unidentified quantity, or always require explicit operator action? |
