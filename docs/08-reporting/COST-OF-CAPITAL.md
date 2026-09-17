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

## 2A. Accrual base is PRINCIPAL, split across three buckets (D-046, D-047, D-048)

### 2A.1 Profits ride free

> "The profits should not go into the interest. If a ₹50,000 trade yields ₹5,000 profit, your
> cost of capital is still going to be on the ₹50,000."

**The accrual base is borrowed principal outstanding, not the account balance.** Retained
profit sits in the account earning its keep at zero cost.

```
principal_outstanding(D)  =  Σ CAPITAL_IN  −  Σ CAPITAL_OUT     (to date D)
daily_interest(D)         =  principal_outstanding(D) × r / 365
```

Borrow ₹50,000, grow it to ₹55,000, and you still owe interest on ₹50,000. *(Q-171 resolved:
option (b).)*

### 2A.2 Ledger entry types — profit withdrawal is a distinct kind

> "There should be an entry screen where the user can add the amounts of profit being
> withdrawn — 5,000, 8,000, 2,000. That amount is treated as profit, whereas all other
> withdrawals are treated as capital inflow and outflow."

Every cash movement is **typed by the operator**, and the type decides whether principal moves:

| Type | Principal | Meaning |
|---|---|---|
| `CAPITAL_IN` | **↑** | New borrowing deployed into the account |
| `CAPITAL_OUT` | **↓** | Repayment to the lender — interest stops on this amount |
| `PROFIT_WITHDRAWAL` | **unchanged** | Taking earnings out. Principal, and therefore the interest bill, is untouched |
| `TRADE_BUY` / `TRADE_SELL` | unchanged | Moves capital between buckets |
| `CHARGES` | unchanged | Reduces cash; the borrowed amount still stands |

The distinction is **the operator's to make and cannot be inferred** — ₹5,000 leaving the
account is either a repayment or a profit take, and only they know which. Hence the dedicated
entry screen, where withdrawals are entered and classified. An unclassified withdrawal must
**block** rather than default to either type (consistent with D-038).

### 2A.3 The three buckets

On any day, borrowed principal sits in exactly one of three states:

```
principal_outstanding  =  DEPLOYED  +  SETTLEMENT  +  IDLE
```

| Bucket | Base | Attribution | Reported as |
|---|---|---|---|
| **DEPLOYED** | Open lots, at cost | **Per lot, per trade** | Cost of capital in True Profit |
| **SETTLEMENT** | Sold lots' **cost**, from sell date until funds are credited | **Unattributed** | **Settlement interest** |
| **IDLE** | `principal − deployed − settlement` | Unattributed | Idle capital drag |

### 2A.4 Settlement interest (D-048)

> "I sold something on Monday but received the funds on Tuesday or Wednesday depending on the
> security. That one day's interest is paid out of my pocket — it's not related to the trade.
> Keep track of when the funds for a sale are credited, and the difference in days is the
> settlement interest cost."

When a sell executes, the lot's own accrual **stops** — the trade is closed and its True
Profit is final. But the money has not arrived, and the lender is still charging. That gap is
its own cost, and it belongs to **neither** the trade nor idle cash.

```
settlement_days     = funds_credited_date − sell_trade_date
settlement_interest = lot_cost × r / 365 × settlement_days
```

**Rules:**
1. The base is the **lot's cost**, not the sale proceeds — the profit portion was never
   borrowed and must not accrue (§2A.1).
2. `funds_credited_date` is **observed from the broker ledger**, never assumed from a
   settlement-cycle constant. The instruction is explicit that it varies by security, and a
   holiday or exchange issue can extend it. Assuming T+1 would silently understate the cost.
3. Until the credit is observed, the amount stays in SETTLEMENT and keeps accruing — so an
   unusually long settlement shows up as a rising cost rather than disappearing.
4. Settlement interest is reported as its **own line**, never folded into a trade's True
   Profit.

### 2A.5 The invariant

```
Σ per-lot accrual  +  settlement accrual  +  idle accrual
        ==  principal_outstanding(D) × r / 365
```

This is the primary test for the subsystem. A buy moves capital IDLE→DEPLOYED, a sell moves
it DEPLOYED→SETTLEMENT, and a credit moves it SETTLEMENT→IDLE — **the total never changes on
any of those days.** Only `CAPITAL_IN` and `CAPITAL_OUT` move it.

### 2A.6 Worked example

Rate 10% p.a. Sell on day 3 of a lot that cost ₹20,000, for ₹20,700; credited day 5.

| Day | Event | Deployed | Settlement | Idle | Principal | Deployed | Settl. | Idle | **Total** |
|---|---|---|---|---|---|---|---|---|---|
| 1 | ₹50,000 `CAPITAL_IN` | 0 | 0 | 50,000 | 50,000 | ₹0.00 | ₹0.00 | ₹13.70 | ₹13.70 |
| 2 | Buy ₹20,000 | 20,000 | 0 | 30,000 | 50,000 | ₹5.48 | ₹0.00 | ₹8.22 | ₹13.70 |
| 3 | **Sell** for ₹20,700 | 0 | 20,000 | 30,000 | 50,000 | ₹0.00 | **₹5.48** | ₹8.22 | ₹13.70 |
| 4 | Awaiting credit | 0 | 20,000 | 30,000 | 50,000 | ₹0.00 | **₹5.48** | ₹8.22 | ₹13.70 |
| 5 | **Funds credited** | 0 | 0 | 50,000 | 50,000 | ₹0.00 | ₹0.00 | ₹13.70 | ₹13.70 |
| 6 | ₹700 `PROFIT_WITHDRAWAL` | 0 | 0 | 50,000 | **50,000** | ₹0.00 | ₹0.00 | ₹13.70 | ₹13.70 |
| 7 | ₹20,000 `CAPITAL_OUT` | 0 | 0 | 30,000 | **30,000** | ₹0.00 | ₹0.00 | ₹8.22 | **₹8.22** |

Three things to read from this:
- **Days 3–4:** the trade is closed and its True Profit is fixed, yet ₹10.96 of settlement
  interest is still being incurred. Invisible without this bucket.
- **Day 6:** withdrawing the ₹700 profit changes nothing — principal is untouched.
- **Day 7:** repaying ₹20,000 is the only event that reduces the bill.

### 2A.7 When deployed exceeds principal

Retained profits get reinvested, so lots at cost can exceed principal outstanding. Interest
must still only be charged on principal.

*Recommendation (Q-174): attribute **pro-rata**. If lots total ₹55,000 against ₹50,000
principal, each lot accrues on 50/55ths of its cost, and IDLE and SETTLEMENT are zero. The
invariant holds and no lot is charged for capital that was never borrowed.*

### 2A.8 Where the daily balances come from

Daily accrual needs, for every calendar day, the principal outstanding and the split across
buckets — but the engine runs on demand and is off most days (D-013). Nobody takes a daily
reading.

| Option | Assessment |
|---|---|
| **(a)** Daily scheduled snapshot | Starting EC2 daily just to read balances undermines the on-demand cost model |
| **(b)** Reconstruct from the ledger | Every bucket is derivable from typed ledger entries plus lot open/close/credit dates. No daily run; all seven days covered |
| **(c)** Snapshot per run and interpolate | Wrong — a deposit between runs is back-dated or lost |

**Recommended: (b)**, reconciled against broker-reported balances whenever the engine runs.
Drift between derived and reported balance is a **signal** — cash moved without ATOM knowing
(an outside transfer, a dividend, a directly-levied charge) — and is surfaced for the operator
to classify, not silently absorbed.

*This makes a complete typed cash ledger per trading account a hard requirement of the data
model, and makes `funds_credited_date` per sale a tracked field.*

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

### Section B1 — Settlement interest
Each sale in the period with its sell date, observed credit date, days in settlement, lot
cost and interest incurred. Sales still awaiting credit are flagged and still accruing.

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
| Less: **settlement interest** (unattributed) | |
| Less: idle capital drag (unattributed) | |
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

**~~Q-171~~ ✅ Resolved by D-047** — principal only; retained profit does not accrue.
**~~Q-172~~ ✅ Resolved by D-048** — neither. Proceeds sit in a third SETTLEMENT bucket from
trade date until the observed credit date.

**Q-174 🟠 — Pro-rata attribution when deployed exceeds principal?** See §2A.7.

**Q-175 🟠 — How is `funds_credited_date` obtained per broker?** It must come from the ledger
or funds API. Brokers expose this differently, and some may not attribute a credit to a
specific trade — in which case FIFO matching of credits to sales is needed. Feeds the round 2
broker research.

**Q-176 🟡 — Does a `PROFIT_WITHDRAWAL` exceeding retained profit get rejected?** Withdrawing
₹10,000 of "profit" when only ₹6,000 has been earned is really a ₹4,000 repayment.
*Recommendation: validate against realised profit to date and require the excess be
reclassified as `CAPITAL_OUT`.*

**Q-173 🟠 — How is the opening balance anchored?**
Reconstruction (§2A.4) needs a starting point per trading account: a date and a known balance.
*Recommendation: the operator enters an opening balance and date at onboarding, and the
system reconciles forward from there.*
