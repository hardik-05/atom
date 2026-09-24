# Holdings Attribution — Per-Universe Positions from an Aggregate Broker View

**Status:** 🟢 Specified
**Implements:** D-162 · resolves Q-258
**Problem:** the broker reports **one quantity per instrument per account**. ATOM needs to know
how much of it belongs to which universe — and the broker will never tell us.

---

## 1. The principle

> "We maintain an internal holdings database. Every morning pull holdings and compute the holding
> on a per-universe basis. All this can be tracked through the order placed and the quantity
> bought, quantity sold or quantity punched."

```
ATOM's lot ledger        =  the SOURCE OF TRUTH for per-universe attribution
Broker's holdings call   =  a RECONCILIATION CHECK on the total only
```

Attribution is never *read* from the broker, because the broker does not have it. It is
**derived from our own order and fill history** and then **verified** against the broker's total.
Those are different jobs and the design keeps them apart.

### The reconciliation identity

For every `(trading_account, instrument)`:

```
broker_quantity  =  Σ open ATOM lots (across all universes)
                 +  excluded_quantity        (pre-existing at onboarding, D-137)
                 +  unattributed_quantity    (residual — should be zero)
```

**`unattributed_quantity` is the health signal.** Zero means our books agree with the broker's.
Anything else means something happened that ATOM did not do:

| Residual | Meaning | Action |
|---|---|---|
| `= 0` | Books agree | Normal |
| `> 0` | Stock appeared — manual buy, bonus, split, demat transfer in | Flag; **never auto-attribute to a universe** (D-086) |
| `< 0` | Stock disappeared — manual sell, transfer out | Flag; ATOM believes it holds what it does not |

> ⚠️ **A negative residual is the dangerous one.** ATOM would place sell orders for quantity that
> is no longer there, and the broker would reject them. The morning reconciliation must run
> **before** the sell pass, and a negative residual blocks that account's run.

---

## 2. Why attribution is derivable at all

Every lot carries `universe_id` (D-156) and is created only by a **fill** on an ATOM order. So
the chain is complete and closed:

```
run (universe_id) → order_request (universe_id) → order_fill → position_lot (universe_id)
                                                        │
                                                   lot_closure ← sell order (universe_id)
```

Nothing enters `position_lot` except through a fill ATOM recorded. That is what makes the
attribution sound: it is not an inference about the broker's data, it is our own transaction
history.

---

## 3. Fill scenarios — the three that matter

| Outcome | Lot created | Notes |
|---|---|---|
| **Fully filled** | One lot, full quantity, at the fill price | The simple case |
| **Partially filled** | One lot for the **filled quantity only** | The remainder is not a lot and has no cost basis. The sell target uses the actual fill price, and quantity changes while the average does not (D-071b) |
| **Not filled** | **No lot** | The order expires at end of day; nothing enters the books |
| **Filled in several tranches** | **One lot per fill**, or one lot with a weighted average | See §6 — a design choice with consequences |

**Fills, not orders, create lots.** An order is an intent; only a fill is a position. This is why
`order_fill` is a separate table and why `position_lot.quantity` comes from fills rather than
from `order_request.quantity`.

---

## 4. Worked permutations

Instrument X, one trading account, two universes.

### Case 1 — buy in two universes on different days

| Day | Event | U-A lots | U-B lots | ATOM total | Broker says |
|---|---|---|---|---|---|
| Mon | U-A buys 10 @ ₹100 | 10 @ 100 | — | 10 | 10 ✅ |
| Tue | U-B buys 20 @ ₹102 | 10 @ 100 | 20 @ 102 | 30 | 30 ✅ |
| Wed | — | 10 @ 100 | 20 @ 102 | 30 | 30 ✅ |

Broker shows **30 @ avg 101.33**. ATOM shows **U-A 10 @ 100** and **U-B 20 @ 102**, and places
**two sell orders** at each universe's own target (D-156).

### Case 2 — sell from one universe

| Day | Event | U-A | U-B | ATOM | Broker |
|---|---|---|---|---|---|
| Thu | U-A's sell fills, 10 | — | 20 @ 102 | 20 | 20 ✅ |

FIFO applies **within the universe** — U-A's lots close, U-B's are untouched. *(Note the
divergence in §7.)*

### Case 3 — averaging

| Day | Event | U-A | U-B | ATOM | Broker |
|---|---|---|---|---|---|
| Fri | U-A averages +10 @ ₹90 | 10 @ 100 **+ 10 @ 90** | 20 @ 102 | 40 | 40 ✅ |

U-A is now **20 units at a ₹95 weighted average**, as a **second lot**, not a mutation of the
first (D-045). U-A's resting sell is cancelled and re-placed for 20 at target(95). U-B's order is
untouched.

### Case 4 — partial fill

| Day | Event | Result |
|---|---|---|
| Mon | U-A orders 40, **12 fill** | Lot of **12** at the actual fill price. Sell target from that price. The unfilled 28 expire at EOD and leave no trace in the books |

### Case 5 — the operator sells manually at the broker

| Day | Event | ATOM | Broker | Residual |
|---|---|---|---|---|
| Sat | Operator sells 15 in the app | 40 | 25 | **−15** 🔴 |

ATOM cannot know which universe lost the stock — **the broker sold from one undifferentiated
pile**. The run is blocked and the operator resolves it (§5).

### Case 6 — a corporate action changes the quantity

| Day | Event | ATOM | Broker | Residual |
|---|---|---|---|---|
| Mon | 1:2 split | 40 | **80** | **+40** 🔴 |

The instrument is already `BLOCKED` by the corporate-action check (D-090), which stops *buying* —
but the **holdings reconciliation still breaks**, because lot quantities are stale. Splits must
be applied to lots, not just detected. **(Q-260)**

---

## 5. Resolving a residual

Residuals are **never auto-attributed** — consistent with D-086, and because the information
genuinely does not exist. The operator is shown the discrepancy and chooses:

| Option | Effect |
|---|---|
| **Add to exclusions** | Treat the surplus as not ATOM's. The common case for a manual buy |
| **Attribute to a universe** | Creates a lot with an operator-supplied cost and date, marked `provenance = EXTERNAL` |
| **Reduce a universe's lots** | For a negative residual: the operator names which universe lost the stock |
| **Accept and re-baseline** | Records the broker as authoritative and writes an adjustment with a reason |

Every choice writes to `action_audit` with the residual, the decision and the reason.

---

## 6. Multiple fills on one order — the design choice

An order for 40 may fill as 12 + 18 + 10, possibly at different prices.

| Option | Consequence |
|---|---|
| **(a) One lot per fill** | Exact cost basis per tranche; FIFO is precise; more rows |
| **(b) One lot, weighted average** | Fewer rows; loses the individual fill prices; FIFO within the order becomes approximate |

**Recommended: (a), one lot per fill.** Lots are already the unit of everything — cost of capital,
FIFO, tax classification — and collapsing them discards information that cannot be recovered.
Row volume is trivial at ATOM's order rate. `order_fill` already models this; `position_lot`
simply gains an `order_fill_id`. **(Q-261)**

---

## 7. ⚠️ Universe FIFO and tax FIFO are different orderings

This falls out of D-156 and is worth stating plainly, because it will otherwise surface as a
reconciliation puzzle a year from now.

- **ATOM closes lots FIFO within a universe**, because that is what makes per-universe P&L mean
  anything.
- **The Income-tax Act applies FIFO per demat account** (D-127), across everything in it,
  regardless of which universe ATOM thinks a lot belongs to.

So selling U-A's 10 units may, for tax purposes, close the **oldest lot in the account** — which
could be U-B's.

**Both are correct for their own purpose, and both must be computed:**

| Ledger | Ordering | Used for |
|---|---|---|
| **Universe ledger** | FIFO within universe | Per-universe P&L, targets, averaging, reporting |
| **Tax ledger** | FIFO within demat account | Capital gains, set-off, exemption |

They are separate computations over the same fills. `lot_closure` supports the universe view;
the tax engine derives its own matching from the same `order_fill` rows. **Neither is a rounding
of the other, and reports must never blend them.** **(Q-262)**

---

## 8. The morning sequence

```
1. PULL       broker holdings + order book + trade book
2. REBUILD    apply overnight fills to lots (D-029: fills while the engine was down)
3. RECONCILE  broker_qty vs Σ lots + exclusions, per instrument
4. BLOCK      any negative residual halts this account's run
5. ATTRIBUTE  compute per-universe positions from lots
6. SELL       one order per (instrument, universe)  (D-156)
7. BUY        per universe, per category
```

Reconciliation sits **before** the sell pass deliberately: placing sell orders against a position
we do not actually hold is the failure this ordering prevents.

---

## 9. Open questions

| ID | Item |
|---|---|
| Q-260 | 🔴 Corporate actions change broker quantity but not ATOM's lots. Apply the ratio to lots on operator confirmation? |
| Q-261 | One lot per fill, or one lot per order at a weighted average? *(Rec: per fill)* |
| Q-262 | Confirm the universe ledger and the tax ledger are maintained as two separate FIFO computations |
| Q-263 | Should a positive residual block the run, or only a negative one? *(Rec: negative blocks, positive warns — surplus stock cannot cause a rejected order)* |
