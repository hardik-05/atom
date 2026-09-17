# Cost of Capital

**Status:** 🟠 Specified, with open questions that change the numbers materially
**Implements:** D-045 · new screen
**Explicitly out of scope:** taxation. Per instruction, tax and tax-loss harvesting are
**excluded** from this calculation. Cost of capital stands alone.

---

## 1. Why this exists

> "The funds used in this system are **borrowed funds**, and borrowed funds come with a cost
> — a per-annum cost. To give a true picture of what profit was actually made in a month or a
> week, we need to take the cost of capital into account alongside the trades and their P&L."

A 3.5% gain on a position held 4 days is a very different outcome from the same 3.5% held
90 days, once the money has a rental price. Gross P&L cannot distinguish them. This screen
does.

```
TRUE PROFIT  =  Realised P&L  −  Charges  −  Cost of capital for the days held
```

---

## 2. The model

### 2.1 Accrual is per lot, daily, on all seven days

> "Every day you keep adding the interest cost on those holdings… this interest keeps running
> on all seven days."

Interest accrues on **calendar days**, not trading days. A position held over a weekend costs
three days of interest, not one. Holidays likewise.

For a lot of value `V` at annual rate `r`:

```
daily_interest = V × r / 365
```

Accrued from the **buy date** to the **sell date** for closed lots, and from the buy date to
**today** for open ones.

### 2.2 Lot-level accrual handles averaging for free

The requirement:

> "Once you average it, that holding becomes ₹20,000, so now the interest is on ₹20,000
> rather than on ₹10,000."

This needs no special case if accrual is **per lot** rather than per position:

| Date | Event | Lots open | Daily accrual base |
|---|---|---|---|
| 1 Jan | Buy ₹10,000 | L1 = ₹10,000 | ₹10,000 |
| 1–19 Jan | Holding | L1 | ₹10,000/day |
| 20 Jan | **Average** +₹10,000 | L1 + L2 | **₹20,000** |
| 20 Jan → | Holding | L1 + L2 | ₹20,000/day |

Summing per-lot accruals produces exactly the described behaviour: ₹10,000 before the
averaging date, ₹20,000 after. This is the strongest argument yet for lot-level position
tracking (already proposed in Q-125) — **position-level tracking cannot represent this
correctly.**

### 2.3 Partial sells

> "You bought ₹30,000 of ETFs; at some point ₹20,000 were sold. Track the interest charged on
> that ₹20,000 during its holding period, and the remaining ₹10,000 keeps accumulating."

Lots are closed **FIFO** (matching Indian capital-gains treatment, D/Q-126). Each closed lot
freezes its accrued interest at its sell date; surviving lots continue accruing.

### 2.4 Worked example

Rate 10% p.a. → ₹10,000 costs **₹2.7397/day**.

| | Lot | Bought | Value | Sold | Days | Interest | Realised P&L | Charges | **True profit** |
|---|---|---|---|---|---|---|---|---|---|
| Closed | L1 | 1 Jan | ₹10,000 | 8 Jan | 7 | ₹19.18 | ₹350.00 | ₹22.40 | **₹308.42** |
| Closed | L2 | 5 Jan | ₹10,000 | 10 Jan | 5 | ₹13.70 | ₹350.00 | ₹22.40 | **₹313.90** |
| Open | L3 | 3 Jan | ₹10,000 | — | 27* | ₹73.97 | — | — | **−₹73.97** so far |

\* to the period end, 30 Jan, and still running.

Gross P&L reads ₹700. True profit on closed trades is ₹622.32, and the open position is
₹73.97 in the hole before it has done anything. That gap is the number this screen exists to
show.

---

## 3. The screen

**Input:** a date range (e.g. 1 Jan – 30 Jan).

### Section A — Closed trades in the period
Bought, sold, days held, quantity, buy value, sell value, gross P&L, charges, **cost of
capital**, **true profit**, and true return %.

### Section B — Open holdings
Bought, days held **so far**, current value, accrued interest **to date**, and a clear
"still accruing" marker. **No P&L is shown** — per instruction, unrealised gain is not
reported here, only the interest that is definitely being incurred.

### Section C — Period summary

| | |
|---|---|
| Gross realised P&L | |
| Less: charges | |
| Less: cost of capital on closed lots | |
| **= True realised profit** | |
| Memo: interest accrued on open holdings | |
| **= Net economic result for the period** | |

### Section D — Per trading account and consolidated
Same structure per account (D-037), plus an investor-level roll-up.

---

## 4. Interaction with the rest of the system

| Area | Effect |
|---|---|
| **Dry run** (D-041) | Applies identically — a paper portfolio accrues cost of capital, so dry-run returns are judged on the same basis as live |
| **Averaging** (D-022) | Increases the accrual base from the averaging date, automatically via lot accrual |
| **Harvesting** (D-019) | A proxy lot begins accruing from its own buy date. Note the synthetic-basis rule means these lots can be held a long time, so their interest cost will be visible and material — which is exactly the transparency intended |
| **Reports** (D-024) | Cost of capital becomes a line in the monthly report alongside charges |
| **Config** (D-038) | The rate is a config value with no default; it must be explicitly set before it can be computed |

---

## 5. Open questions — these change the numbers materially

**Q-162 🔴 — Does idle cash accrue interest?**
This is the most consequential question here. If ₹50,000 is borrowed and only ₹30,000 is
deployed, the lender charges on ₹50,000 — but the model above only accrues on deployed lots.

- **(a)** Accrue only on deployed lots (as specified above). Simple, attributable per trade,
  but **understates the true cost** and flatters the strategy on days when capital sits idle.
- **(b)** Accrue on the **full borrowed balance**, then allocate across lots. Economically
  honest, and it correctly penalises idle capital — which matters, because your depth/skip
  rules deliberately produce days with no buys at all.
- **(c)** Both: per-lot for trade attribution, plus a separate "idle capital drag" line in
  the period summary.

*Recommendation: **(c)**. It preserves per-trade attribution while keeping the period summary
economically truthful.*

**Q-163 🟠 — Simple or compound?** Simple interest at `V × r / 365` per day, or compounding
on unpaid accrued interest?
*Recommendation: simple. Matches how a per-annum facility is typically charged, and keeps the
per-lot arithmetic auditable.*

**Q-164 🟠 — Day-count convention.** Actual/365, actual/360, or 30/360?
*Recommendation: **Actual/365**, standard for INR facilities, and it matches the stated
"interest runs on all seven days".*

**Q-165 🟠 — Is the rate per trading account, per investor, or global?** Different investors
may borrow at different rates, and Person A's Upstox and Dhan capital may come from the same
facility.
*Recommendation: **per investor**, since a borrowing facility belongs to a person, not to a
broker relationship. But this cuts against the (trading_account, category) config grain, so
it needs your call.*

**Q-166 🟠 — Can the rate change over time?** If the facility re-prices (say 10% → 11% in
March), historical accruals must not be retroactively restated.
*Recommendation: store the rate as a **dated series**, and accrue each day at the rate in
force that day. Materially more correct, and only slightly more work.*

**Q-167 🟠 — Accrual base: cost or current value?** A lot bought at ₹10,000 now worth ₹9,000 —
does it accrue on ₹10,000 or ₹9,000?
*Recommendation: **cost**. You borrowed ₹10,000; the market price of what you bought with it
does not change what you owe.*

**Q-168 🟡 — Does the sell day count?** Buy 1 Jan, sell 8 Jan — 7 days or 8?
*Recommendation: count the buy day, exclude the sell day (7 days), the usual convention.*

**Q-169 🟡 — Are charges included in the accrual base?** Brokerage and STT are also paid from
borrowed money.
*Recommendation: yes — accrue on the all-in cost, not the bare traded value. Small, but free
to get right.*
