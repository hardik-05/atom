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

## 2A. Two accrual buckets: deployed and idle (D-046)

> "Go ahead with both. Per-lot attribution gives the actual trade-system picture, and the
> idle capital drag can be gathered from per-day funds held. If ₹50,000 is present and
> ₹20,000 goes into lots, the ₹20,000 accrues per the lots; the ₹30,000 in the account also
> gains interest, but it is not associated to the trades — it is an idle cash cost. If the
> next day the user withdraws ₹20,000, that ₹20,000 has been paid back, so the idle cash cost
> comes to ₹10,000."

Every rupee in an account is borrowed and accrues from the day it arrives until the day it is
repaid. It sits in exactly one of two buckets on any given day:

```
TOTAL BORROWED CAPITAL  =  DEPLOYED (open lots, at cost)  +  IDLE (cash balance)

daily_interest_total  =  (deployed + idle) × r / 365
```

| Bucket | Base | Attribution |
|---|---|---|
| **Deployed** | Sum of open lots at cost | **Per lot**, per trade — flows into True Profit (§2) |
| **Idle** | Account cash balance | **Unattributed** — reported as "idle capital drag" |

### 2A.1 The invariant

A buy moves capital from idle to deployed; a sell moves it back. **Total interest is
continuous across the move** — no gap on the buy day, no double count. This is the primary
test for the whole subsystem:

```
sum(per-lot accrual for day D) + idle accrual for day D
    ==  total borrowed capital on day D × r / 365
```

Any discrepancy means capital has been lost or duplicated between the buckets.

### 2A.2 Capital events

| Event | Effect on borrowed capital |
|---|---|
| **Deposit** | Additional borrowing — increases the idle base from that day |
| **Withdrawal** | **Repayment** — reduces the idle base from that day. Interest stops on the repaid amount |
| **Buy** | Idle → deployed, same total |
| **Sell** | Deployed → idle, same total; the lot's accrual freezes |
| **Charges paid** | Leave the account — reduce the idle base |

### 2A.3 Worked example

Rate 10% p.a. → **₹0.000274 per rupee per day**.

| Day | Event | Deployed | Idle | Total | Deployed int. | Idle int. | Day total |
|---|---|---|---|---|---|---|---|
| 1 | ₹50,000 deposited | 0 | 50,000 | 50,000 | ₹0.00 | ₹13.70 | ₹13.70 |
| 2 | Buy ₹20,000 | 20,000 | 30,000 | 50,000 | ₹5.48 | ₹8.22 | ₹13.70 |
| 3 | **Withdraw ₹20,000** | 20,000 | 10,000 | **30,000** | ₹5.48 | ₹2.74 | **₹8.22** |

Day 3 matches the instruction exactly: the withdrawn ₹20,000 is repaid, and idle cost falls
to the ₹10,000 that remains. Note the total cost drops from ₹13.70 to ₹8.22 — **repaying
capital is the only way to reduce it**, which is precisely the behaviour the screen should
make visible.

### 2A.4 Where the daily cash balance comes from — a real problem

Daily accrual needs a **cash balance for every calendar day**, but the engine only runs on
demand and is switched off most of the time (D-013). Nobody is there to take a daily reading.

| Option | Assessment |
|---|---|
| **(a)** Daily scheduled snapshot | Requires starting EC2 every day purely to read a balance — undermines the on-demand cost model, and still misses non-trading days unless run all seven |
| **(b)** Reconstruct from a transaction ledger | Anchor on a known balance, then apply every deposit, withdrawal, buy, sell and charge to derive the balance for each day. No daily run needed; every day including weekends is covered |
| **(c)** Snapshot on each run and interpolate | Cheap but wrong — a deposit between runs would be back-dated or missed entirely |

**Recommended: (b), reconstructed, reconciled against broker-reported balances whenever the
engine does run.** A drift between derived and broker-reported balance is then a *signal* —
it means a cash movement happened that ATOM does not know about (an outside transfer,
dividends, a charge levied directly), and it should be surfaced rather than silently
absorbed.

*This makes a complete cash ledger per trading account a hard requirement of the data model,
not an optional convenience.*

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

### Section B2 — Idle capital
Daily cash balance over the period, interest accrued on it, and the capital events (deposits
and withdrawals) that moved it. Withdrawals are shown as **repayments**, with the interest
saved from that day forward.

### Section C — Period summary

| | |
|---|---|
| Gross realised P&L | |
| Less: charges | |
| Less: cost of capital on closed lots (**deployed, attributed**) | |
| **= True realised profit** | |
| Less: idle capital drag (**unattributed**) | |
| **= Net result after all capital cost** | |
| Memo: interest accrued on open holdings, still running | |
| Memo: total borrowed capital, period average | |
| Memo: **capital efficiency** — % of days capital was deployed vs idle | |

**Capital efficiency is the number this screen ultimately exists to produce.** The depth and
skip rules (D/§6.2) deliberately produce days with no buys, and every such day is a day the
borrowed capital earns nothing while still costing. This line quantifies that trade-off for
the first time.

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

**~~Q-162~~ ✅ Resolved by D-046** — both buckets, per §2A.

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

**Q-171 🔴 — Does retained profit accrue interest?**
D-046 accrues on the **actual cash balance**, and a profitable sale returns more cash than the
lot cost. So ₹50,000 borrowed that grows to ₹55,000 would accrue on ₹55,000 from that day,
unless the ₹5,000 is withdrawn.

- **(a)** Accrue on the actual balance (as specified). Treats retained profit as capital the
  firm has left deployed, and is the literal reading of "funds held in the account".
- **(b)** Accrue only on **principal** — cumulative deposits minus withdrawals — so profit is
  yours and rides free.

*This needs your decision: (a) charges you for your own profits, (b) requires tracking
principal separately from balance. **(b)** is the more conventional treatment of a borrowing
facility, but **(a)** is what you described.*

**Q-172 🟠 — Are un-withdrawn sale proceeds idle capital on the sell day itself?**
T+1 settlement means proceeds are not spendable for a day. Do they accrue as idle from the
trade date or the settlement date?
*Recommendation: **trade date**, matching how the lot's accrual stops, so the buckets stay
continuous.*

**Q-173 🟠 — How is the opening balance anchored?**
Reconstruction (§2A.4) needs a starting point per trading account: a date and a known balance.
*Recommendation: the operator enters an opening balance and date at onboarding, and the
system reconciles forward from there.*
