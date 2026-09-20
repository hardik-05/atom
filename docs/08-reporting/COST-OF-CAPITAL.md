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

### 2A.7 Profit is never reinvested — this is a system invariant (D-049)

> "In this system profit will never be reinvested. Capital will be borrowed, capital will be
> traded, profits will go out, and the capital will be repaid."

The capital lifecycle is closed and one-directional:

```
CAPITAL_IN  →  deployed in lots  →  sold  →  settled
                                              ├─→ PROFIT_WITHDRAWAL   (profit leaves)
                                              └─→ redeployed or CAPITAL_OUT   (principal only)
```

Therefore **deployed + settlement can never exceed principal**, and the pro-rata attribution
once contemplated in Q-174 is unnecessary. It becomes an assertion instead:

```
assert deployed + settlement <= principal_outstanding    # for every account, every day
```

> ⚠️ **This invariant is a policy, not a mechanism, so it must be monitored.** The engine
> places orders and the broker fills them from whatever cash is present — it cannot tell
> principal-cash from profit-cash. If realised profit is left sitting in the account, the next
> run will happily deploy it, silently breaking the assumption and understating the interest
> base.
>
> **Required guard:** whenever `deployed + settlement > principal_outstanding`, raise an alert
> naming the excess and prompting the operator either to record a `PROFIT_WITHDRAWAL` (if the
> profit has left) or to reclassify it as `CAPITAL_IN` (if it is being treated as working
> capital). The run is not blocked, but the discrepancy is never absorbed silently.

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

**~~Q-163~~ ✅ Resolved — simple interest.** `V × r / 365` per day, never compounding on
accrued-but-unpaid interest. Confirmed for the borrowed-capital facility, which is the only
interest in the system.

**~~Q-164~~ ✅ Resolved — Actual/365.**

**~~Q-165~~ ✅ Resolved by D-053 — the rate is per trading account**, i.e. per
(investor, broker). Person A's rate at Broker A may differ from Person A's at Broker B. This
keeps cost of capital on the same config grain as everything else, and means accruals are
computed per trading account and rolled up to the investor for consolidated reporting.

**~~Q-166~~ ✅ Resolved — dated rate series, applied forward only.** A rate change takes
effect from its effective date onward. **Historical accruals are never restated** — days
already accrued keep the rate that was in force. Storage is a dated series per trading
account (D-053).

**~~Q-167~~ ✅ Resolved — original cost**, not current value.

**~~Q-168~~ ✅ Resolved (D-070) — the sell day IS counted.**

> "You buy on day one, so you count your cost of capital starting from day one. At day five
> you make a sale and clear off. So ideally you have held it for five days, so the sale day
> should be considered in the cost of capital interest. And probably day six will be your
> settlement date — so the sixth day's cost comes under a different heading."

| Phase | Days | Bucket |
|---|---|---|
| Held | buy_date **… sell_date inclusive** | DEPLOYED, per lot |
| In settlement | sell_date + 1 **… credit_date inclusive** | SETTLEMENT |
| Available | credit_date + 1 onward | IDLE |

`deployed_days = sell_date − buy_date + 1` · `settlement_days = credit_date − sell_date`

Buy day 1, sell day 5, credited day 6 → **5 deployed days, 1 settlement day**, no gap and no
overlap. *(Q-189: confirm the boundary — settlement counts the credit date itself, and idle
starts the day after.)*

**~~Q-169~~ ✅ Resolved — yes, the all-in cost** including brokerage, STT and the rest.

**~~Q-171~~ ✅ Resolved by D-047** — principal only; retained profit does not accrue.
**~~Q-172~~ ✅ Resolved by D-048** — neither. Proceeds sit in a third SETTLEMENT bucket from
trade date until the observed credit date.

**~~Q-174~~ ✅ Resolved by D-049** — profit is never reinvested, so deployed never exceeds
principal. Enforced as a monitored assertion rather than handled by pro-rata attribution.

**~~Q-175~~ ✅ Confirmed** — `funds_credited_date` is obtained per broker as part of the
broker research, and **never hard-coded to T+1**. A security sold on Friday may credit on
Monday, which already exceeds T+1; holidays extend it further. Each broker adapter must expose
the actual credit date and event, with FIFO matching of credits to sales where a broker does
not attribute a credit to a specific trade. Tracked in the broker capability matrix.

**~~Q-176~~ ✅ Resolved** — a `PROFIT_WITHDRAWAL` greater than realised profit to date is
**rejected at entry** with a validation message. The operator must either reduce the amount or
reclassify the excess as `CAPITAL_OUT`.

**~~Q-173~~ ✅ Resolved — call the broker's funds API.** The opening balance is fetched from
the account rather than typed in, and reconstruction proceeds forward from that reading.
