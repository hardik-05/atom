# Tax Engine

**Status:** 🟠 Specified · the most intricate module in the system
**Implements:** D-127 · builds on [`TAXATION-MODEL.md`](./TAXATION-MODEL.md) (rates)
**Date:** 2026-09-23

> Design-constraints summary from public sources. **Not tax advice.** Every figure ATOM
> produces is an **estimate for planning**, and the UI must say so. Filing is the operator's
> responsibility with their CA.

---

## 1. The two levels — and why they differ

This is the structural heart of the engine, and getting it wrong produces confidently wrong
numbers.

```
        PAN  (the assessee — where tax is actually computed)
         │
         ├── Trading account: Investor A · Upstox   ← FIFO chain 1
         ├── Trading account: Investor A · Dhan     ← FIFO chain 2
         └── Trading account: Investor A · Zerodha  ← FIFO chain 3
```

| Computation | Level | Authority |
|---|---|---|
| **Cost basis / FIFO matching** | **Per demat account** | CBDT Circular 768 (24-6-1998): FIFO applies *vis-à-vis each demat account* — securities in another account cannot be construed as sold |
| **Gain aggregation, set-off, exemption, surcharge, cess, final liability** | **Per PAN** | The assessee is the person, not the account |

**So a lot matched in the Upstox account is never matched against a lot in Dhan** — each
account keeps its own FIFO queue — **but the resulting gains are pooled at PAN level** before
anything else happens.

*Practical consequence the operator already identified: one person holding three broker
accounts has one tax liability, not three, and it cannot be computed correctly by summing three
independently-computed numbers — because the exemption, the set-off and the surcharge are all
applied once, to the pooled figure.*

> ⚠️ **Conflicts with D-075 ("never store PAN").** PAN-level aggregation needs a grouping key.
> It does **not** need the PAN digits: an internal `investor_id` that trading accounts hang off
> serves identically, and a masked PAN (`XXXXX1234X`) is enough to verify a broker statement
> belongs to the right person. **Recommendation: store `investor_id` + masked PAN only, never
> the full number.** See Q-214.

---

## 2. Classifying a gain

Every closed lot produces one gain record:

```
holding_days = sell_date − buy_date          (per D-076c, sell day counts)
term         = LONG if holding_days > 365 else SHORT
bucket       = EQUITY | COMMODITY | GLOBAL   (from the taxonomy)
→ six gain classes: {EQUITY, COMMODITY, GLOBAL} × {SHORT, LONG}
```

### Rates per class

| Class | Rate | Statutory basis | Surcharge |
|---|---|---|---|
| EQUITY · SHORT | **20% flat** | s.111A | **capped 15%** |
| COMMODITY · SHORT | **slab rate** | normal provisions | **NOT capped** ⚠️ |
| GLOBAL · SHORT | **slab rate** | normal provisions | **NOT capped** ⚠️ |
| EQUITY · LONG | 12.5% after ₹1.25L exemption | s.112A | capped 15% |
| COMMODITY · LONG | 12.5% | s.112 | capped 15% |
| GLOBAL · LONG | 12.5% | s.112 | capped 15% |

> ⚠️ **The surcharge cap does not reach commodity and global short-term gains.** The 15% cap
> applies to gains under sections 111A, 112A and 112. Commodity and global STCG fall under
> normal provisions, so at high income they attract the **full** surcharge (25% or 37%) on top
> of a slab rate that may already be 30%. This is the single most expensive combination in the
> system and it deserves to be visible in the UI.

Plus **4% health and education cess** on (tax + surcharge).

---

## 3. Deductible costs — not all charges are equal

When computing the gain, transfer expenses reduce it — but **STT does not**.

| Charge | Deductible from capital gain? |
|---|---|
| Brokerage | ✅ Yes |
| Exchange transaction charges | ✅ Yes |
| SEBI turnover fees | ✅ Yes |
| Stamp duty | ✅ Yes |
| DP / depository charges on sell | ✅ Yes |
| GST on the above | ✅ Yes |
| **STT** | ❌ **No** — expressly disallowed for gains taxed under s.111A/112A |

*This means the "profit" figure in D-061 and the "taxable gain" figure are **not the same
number**. D-061 subtracts everything including STT; the tax computation adds STT back. Both are
correct for their purpose, and the reports must not conflate them.* (Q-215)

---

## 4. Set-off, in the legally required order

Capital losses can **only** offset capital gains — never salary, business or other income.

```
1. CURRENT-YEAR losses first
   ├── Short-term capital loss  → may offset  STCG and LTCG
   └── Long-term capital loss   → may offset  LTCG only
2. BROUGHT-FORWARD losses next, oldest vintage first (8-year window)
3. Residual loss carries forward, tagged with its assessment year
```

**Short-term losses are strictly more valuable** — they can absorb either kind of gain. The
harvest screen should prefer generating short-term losses, which it naturally does, since the
strategy is short-term by design.

Carry-forward requires the **return to be filed by the due date**; a late return forfeits it.
ATOM cannot enforce that, but the screen should state it where carried-forward losses are shown.

---

## 5. The ₹1.25 lakh exemption

- Applies **only to EQUITY · LONG** gains (s.112A).
- **Once per PAN per financial year**, across every account and every source — including
  trades ATOM did not make.
- Config value `ltcg_exemption_inr` (D-122), so a statutory change is an edit.
- Consumed **before** the 12.5% rate is applied.

The tax screen shows **consumed / remaining** at PAN level, with each account's contribution
beneath it.

---

## 6. External trades must be ingested (D-123)

A broker's capital-gains statement contains every trade in that account, not only ATOM's. Those
gains **consume the same exemption and the same set-off pools**, so omitting them produces a
number that is wrong in the operator's favour — the worst direction.

- Ingest the full statement per account.
- Tag every trade `ATOM` or `EXTERNAL` (same provenance logic as D-062).
- Report ATOM-only, external-only and combined.

> **State the boundary honestly:** ATOM's tax view covers the accounts connected to it. A gain
> in an account ATOM cannot see is not counted, and the screen must say so rather than imply a
> complete picture of the PAN.

---

## 7. Nuances that are easy to miss

| # | Nuance | Effect on ATOM |
|---|---|---|
| 1 | **Advance tax** — capital gains create an instalment obligation (15/45/75/100% by 15 Jun/Sep/Dec/Mar), with interest under s.234B/234C if short | An active short-term strategy generates liability all year. **The tax screen should show the next instalment date and estimated amount** — otherwise the first surprise is an interest demand. (Q-216) |
| 2 | **Dividend stripping, s.94(7)** — buy within 3 months before a record date and sell within 3 months after, and the loss is disallowed to the extent of the dividend | ETFs do distribute. A harvest sale could land inside this window and have its loss **disallowed** — silently defeating the harvest. Needs a check. (Q-217) |
| 3 | **Bonus stripping, s.94(8)** — applies to units | Same shape; rarer for ETFs |
| 4 | **Grandfathering (31 Jan 2018)** — cost stepped up for equity acquired before that date | Only affects pre-2018 holdings. Relevant if any `EXTERNAL` holding predates it |
| 5 | **Speculative income** — same-scrip intraday is business income, not capital gains | ATOM is delivery-only (D-056b), so it cannot create this. An external intraday trade can, and must not be pooled with capital gains |
| 6 | **Financial year boundary** — 1 Apr to 31 Mar | Gains are assigned by **sell date**, not settlement date |
| 7 | **Rounding** — tax rounded to the nearest ₹10 (s.288B) | Applied once at the end, never per trade |
| 8 | **Dividends are taxable even though ATOM ignores them** | D-099 excludes dividends from the *trading* engine because they hit the bank account. They remain **taxable at slab as income from other sources**, with TDS above ₹10,000. The tax screen should note the omission rather than imply dividends are tax-free. (Q-218) |
| 9 | **Marginal relief on surcharge** | Applies where income just crosses a surcharge threshold |
| 10 | **Buy-side charges join the cost of acquisition**, sell-side charges reduce consideration | Affects which side each charge lands on |

---

## 8. Computation order

```
per demat account:
    1. FIFO-match sells to buys        → closed lots
    2. gain = consideration − (cost + buy charges) − sell charges, EXCLUDING STT
    3. classify: bucket × term         → six classes

pooled per PAN:
    4. sum each class across all accounts, ATOM and EXTERNAL
    5. apply ₹1.25L exemption to EQUITY·LONG
    6. set off current-year losses  (STCL → any; LTCL → long only)
    7. set off brought-forward losses, oldest first
    8. apply rates per class
    9. surcharge — capped 15% for 111A/112A/112; uncapped for slab-rate STCG
   10. cess 4% on (tax + surcharge)
   11. round to nearest ₹10
   12. carry forward the residual loss with its assessment year
```

**Every step is shown in the UI**, not just the final number — the same
show-your-working principle as the decision logs (D-035). A tax figure nobody can reconstruct
is a tax figure nobody can trust.

---

## 9. Open items

| ID | Item |
|---|---|
| Q-214 | 🔴 Store `investor_id` + masked PAN only, never the full PAN? (conflicts with D-075) |
| Q-215 | Confirm "profit" (D-061, STT deducted) and "taxable gain" (STT added back) are reported as two distinct figures |
| Q-216 | Show advance-tax instalment dates and estimates? |
| Q-217 | Check harvest sales against the s.94(7) dividend-stripping window? |
| Q-218 | Note dividend income on the tax screen as out of scope but taxable? |
| Q-219 | Should ATOM ever *propose* a tax action beyond harvesting — e.g. flagging a position 5 days from LTCG — or stay purely descriptive? |

---

## Sources

- [CBDT Circular 768 of 24-6-1998 — FIFO per demat account](https://incometaxindia.gov.in/communications/circular/910110000000000355.htm)
- [Income Tax India — Capital Gains](https://www.incometaxindia.gov.in/w/capital-gain)
- [ClearTax — surcharge rates and marginal relief AY 2026-27](https://cleartax.in/s/marginal-relief-surcharge)
- [Bajaj Finserv — Section 112A and the LTCG exemption](https://www.bajajfinserv.in/investments/section-112a-income-tax-act)
- [VRD Nation — Sections 111A vs 112A](https://www.vrdnation.com/section-111a-112a-explained/)
- [Business Standard — capital gains across multiple demat accounts](https://www.business-standard.com/finance/personal-finance/explained-how-to-calculate-capital-gains-tax-on-multiple-demat-accounts-124080200149_1.html)
