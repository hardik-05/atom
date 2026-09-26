# Unified P&L

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Basis:** D-169 (three tiers) · D-190 (three bases) · D-167 (two FIFOs) · D-057 (what profit means)

> There is no single number called "profit". There are **three**, they legitimately disagree, and the
> UI never shows one without saying which it is. This document defines each precisely and says which
> question each answers.

---

## 1. The three numbers

| | Basis | FIFO | Answers |
|---|---|---|---|
| **Strategy return** | `synthetic_cost_basis` (falling back to `unit_cost`) | universe | *Are we above the capital we committed?* |
| **Cash return** | `unit_cost` | universe | *What did this position's money actually do?* |
| **Taxable gain** | `unit_cost` | **tax** (PAN-wide) | *What does the tax engine see?* |

For a position with no harvest history, **all three agree**. They diverge in exactly two situations,
and both are intentional:

| Divergence | Cause |
|---|---|
| Strategy ≠ Cash | A harvest proxy carries forward the harvested security's committed capital (D-188) |
| Cash ≠ Taxable | Tax FIFO may pair a disposal with a lot from a different universe (D-167) |

### 1.1 Why not collapse them

The temptation is to pick one and call it profit. Each choice breaks something specific:

- **Strategy only** → the tax figure is wrong, and the investor's actual cash position is invisible.
- **Cash only** → a harvest reports a gain while the investor is below committed capital. This is the
  phantom-profit failure the synthetic basis exists to prevent (`../04-strategy/HARVEST-COST-BASIS.md`
  §1).
- **Taxable only** → strategy performance becomes unmeasurable, and universes cannot be compared.

So all three are computed and all three are shown. **The cost of three labelled numbers is mild
confusion; the cost of one unlabelled number is a wrong decision.**

---

## 2. Realised P&L

Per `lot_closure`, then aggregated:

```
proceeds      = quantity × unit_proceeds          # net of sell charges
cash_cost     = quantity × lot.unit_cost          # all-in, incl. buy charges (D-076a)
synth_cost    = quantity × COALESCE(lot.synthetic_cost_basis, lot.unit_cost)

cash_realised     = proceeds − cash_cost
strategy_realised = proceeds − synth_cost
```

**Charges are already inside both cost figures** (D-076a), so realised P&L is net by construction —
there is no separate "less charges" line to forget.

### 2.1 What is excluded from profit

| Excluded | Reported where | Why |
|---|---|---|
| **Cost of capital** | Its own screen (`COST-OF-CAPITAL.md`) | A cost of the programme, not of the trade (D-057) |
| **Tax liability** | Tax screen | Depends on PAN-wide position, not on this trade |
| **DP charges** | Charges screen, and inside `unit_proceeds` | Per scrip per day, not per trade — attribution is at the instrument level |

Cost of capital is the one most likely to be argued about. It is excluded because a position's
performance and the cost of funding it are separate facts: a trade can be a good trade and still lose
money after interest, and merging them hides which of the two needs fixing.

---

## 3. Unrealised P&L

```
mark          = quantity_open × last_price
cash_unreal      = mark − quantity_open × unit_cost
strategy_unreal  = mark − quantity_open × COALESCE(synthetic_cost_basis, unit_cost)
```

Marked from the **end-of-day snapshot**, not live prices (D-041). Every unrealised figure carries its
`as_of` timestamp, because an unrealised number without one invites the reader to assume it is current.

**No taxable unrealised.** Tax arises on disposal; an unrealised taxable gain is not a thing, and
showing one would imply a liability that does not exist.

---

## 4. The three reporting tiers (D-169)

```
account ₹60,000
   ├── universe 1 : ₹20,000 deployed   → P&L reported here
   ├── universe 2 : ₹30,000 deployed   → P&L reported here
   └── idle       : ₹10,000            → ACCOUNT level only
```

| Tier | Contains | Does **not** contain |
|---|---|---|
| **Universe** | Realised + unrealised on its own lots, its charges, cost of capital on **its own** deployed + settlement capital | Idle cash, other universes, tax |
| **Account** | Every universe summed, **plus idle drag**, total principal, capital efficiency | Tax |
| **Investor (PAN)** | Tax only — pooled gains, set-off, exemption, liability | Strategy performance |

### 4.1 Why idle cash is an account-level fact only

Charging idle cash to a universe would distort exactly the comparison universes exist to enable
(D-169). If universe 1 happened to be running while ₹10,000 sat uninvested, it would carry an
interest cost it did not cause — and the peer comparison between universe 1 and 2 would measure the
operator's cash management rather than the strategies.

So `capital_accrual_universe_daily` holds only the **attributable** portion (deployed +
settlement), and idle drag appears once, at the account.

---

## 5. Peer comparison

The reason universes exist as a first-class entity. Universes are compared on:

| Metric | Basis |
|---|---|
| Return % on deployed capital | **strategy** |
| Return % on deployed capital | **cash** |
| Realised vs unrealised split | both |
| Charges as % of turnover | actual |
| Cost of capital as % of deployed | actual |
| Turnover / churn | — |
| Deviation capture — average deviation at entry vs at exit | strategy |
| Hit rate — closed lots above target | strategy |

**Every comparison uses the same basis across universes, and names it.** Comparing one universe's
strategy return against another's cash return would be meaningless, and the failure would be
invisible — which is why the basis is a label on the chart, not a footnote.

---

## 6. The ATOM vs Broker contrast (D-020)

The broker's P&L and ATOM's will legitimately disagree, and the contrast page exists to explain why
rather than to hide it.

| Source of difference | Direction |
|---|---|
| **Synthetic basis** after a harvest | ATOM's strategy figure differs from the broker's; ATOM's *cash* figure should match |
| **Universe attribution** | The broker has no concept of universes and reports one blended average |
| **Lot grain** | ATOM holds one lot per fill; the broker shows a single weighted average |
| **Charge timing** | DP and some charges land later on the broker's side |
| **Excluded holdings** (D-137) | Pre-existing stock ATOM does not manage still appears in the broker's P&L |

Expandable by date (D-020): clicking a date reveals, per affected trade, what ATOM did, what ATOM's
books say, and what the broker shows.

> **The reconciliation target is the *cash* figure, not the strategy figure.** ATOM's cash P&L and the
> broker's should agree once charges have settled. A mismatch there is a bug. A mismatch in the
> strategy figure is expected and is the whole point of the synthetic basis.

That sentence is the most useful thing on the page, because without it every harvest looks like a
reconciliation failure.

---

## 7. Period handling

| | |
|---|---|
| Periods | Day · month · quarter · **financial year (Apr–Mar)** · custom |
| Default | Financial year to date |
| Boundaries | IST, inclusive |
| Realised | Attributed to `lot_closure.closed_on` |
| Unrealised | Marked at the period's last snapshot |
| Cost of capital | Accrued daily, summed over the period (Actual/365) |

**Financial year means April to March**, not January to December. Every tax figure and most reports
depend on it, and a calendar-year default would silently produce wrong tax numbers.

---

## 8. Worked example — the three numbers diverging

A harvest, then an average, then a partial sell.

```
① Buy A          10 @ ₹100      unit_cost ₹100   synthetic NULL
② A → ₹90, harvest: sell A, buy proxy B 10 @ ₹90
                                unit_cost ₹90    synthetic ₹100
                                booked loss ₹100  (taxable, now)
③ B → ₹85, operator overrides the block and averages
   lot B2         10 @ ₹85      unit_cost ₹85    synthetic NULL
④ Tranches:  SYNTHETIC 10 @ target ₹103.50   ·   ACTUAL 10 @ target ₹87.98
⑤ The ACTUAL tranche fills at ₹88
```

| Number | Value | Reading |
|---|---|---|
| Cash realised | 10 × (88 − 85) = **+₹30** | The averaged lot made ₹30 |
| Strategy realised | same, **+₹30** | That lot had no carried basis |
| Taxable gain | **+₹30**, less the ₹100 loss already booked at ② | Net **−₹70** for the year so far |
| Remaining position | 10 units, synthetic ₹100, actual ₹90 | Still needs ₹103.50 to clear committed capital |

**All three reports are correct and they say different things.** The trade made ₹30, the tax position
is −₹70, and the original ₹1,000 is not yet recovered. Any single number would have concealed two of
those three facts.

---

## 9. Related

[`CHARGES-MODEL.md`](CHARGES-MODEL.md) · [`COST-OF-CAPITAL.md`](COST-OF-CAPITAL.md) ·
[`TAX-ENGINE.md`](TAX-ENGINE.md) · [`REPORT-SPECS.md`](REPORT-SPECS.md) ·
[`../04-strategy/HARVEST-COST-BASIS.md`](../04-strategy/HARVEST-COST-BASIS.md)
