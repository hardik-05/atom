# Report Specifications

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Basis:** D-058g (weekly CSVs to Telegram) · D-072e (archived) · D-169 (three tiers) · D-190 (three bases)

> ATOM's own reporting system (not a broker's). Every report is reproducible from the database, names
> the basis of every figure, and is archived permanently.

---

## 1. Inventory

| # | Report | Frequency | Format | Delivery |
|---|---|---|---|---|
| R1 | Daily run summary | per run | Telegram + console | push |
| R2 | Detailed run log | per run | `.log` file | Telegram · S3 · Drive |
| R3 | Weekly universe snapshot | Saturday | 2 × CSV | Telegram · S3 · Drive |
| R4 | Universe performance | on demand | console + CSV | — |
| R5 | Peer comparison | on demand | console + CSV | — |
| R6 | Account statement | monthly | PDF + CSV | Drive |
| R7 | Closed-trade register | on demand | CSV | — |
| R8 | Charges contrast | on demand | console + CSV | — |
| R9 | Cost of capital | on demand | console + CSV | — |
| R10 | Tax computation | quarterly + FY end | PDF + CSV | Drive, **permanent** |
| R11 | ATOM vs broker contrast | on demand | console | — |
| R12 | Reconciliation exceptions | per run, if non-empty | Telegram | push |

**R12 is push-only when non-empty.** A daily "nothing to report" message trains the operator to
ignore the channel, so silence is the normal state and a message means something needs attention.

---

## 2. Universal rules

Applied to every report, and each exists to prevent a specific misreading.

| Rule | Prevents |
|---|---|
| **Every monetary figure names its basis** — strategy / cash / taxable | Reading a harvest-inflated target as realised profit |
| **Every charge names its source** — computed / broker | Treating ATOM's model as the broker's statement |
| `—` where a value cannot be known; never `0` | "No charge levied" vs "we cannot tell" |
| Header carries: period, account, universe, **basis**, generated-at, `run_id` where applicable | A screenshot circulating without context |
| Currency 2dp displayed / 4dp stored · percentages 2dp / 4dp | Rounding drift between report and database |
| Indian digit grouping, ₹ symbol | — |
| **Financial year = April–March** | Calendar-year tax figures, which would be simply wrong |
| Every report has a CSV form | A PDF that cannot be checked |
| Reproducible from a documented query | A number nobody can re-derive |

> **A report that cannot be re-derived from the database is not a report, it is an assertion.** Every
> spec below names the tables it reads.

---

## 3. R1 — Daily run summary

**Reads:** `run` · `run_candidate` · `order_request` · `order_fill`

```
ATOM · 26 Sep 2026 · Investor A · Universe: Core ETF · LIVE

Pre-flight    egress ✓   token ✓   calendar ✓   sell-auth ✓
Sell           3 GTTs cancelled · 3 verified · 4 placed (1 SYNTHETIC tranche)
Buy            18 evaluated · 2 bought · 16 skipped
               NIFTYBEES  10 @ ₹284.50   dev −4.12%
               GOLDBEES    8 @ ₹ 71.20   dev −6.08%
Skipped        11 threshold · 3 one-lot-per-day · 1 NAV premium 18.9% · 1 proxy blocked
Charges        est. ₹12.40 (computed)
Status         COMPLETED in 4m 12s            run_id 8871
```

The skipped breakdown is the useful part. *Why didn't it buy X?* is the question this report exists to
pre-empt.

---

## 4. R3 — Weekly universe snapshot (D-058g)

Two CSVs, every Saturday, to Telegram and archived.

**`universe-YYYY-MM-DD.csv`** — the frozen membership:
`isin, symbol, name, bucket, tier2_group, tier1_index, asset_class, lot_size, tick_size, status`

**`volumes-YYYY-MM-DD.csv`** — the liquidity evidence:
`isin, symbol, avg_volume_{window}d, avg_turnover, passes_liquidity_gate, threshold_used`

Frozen as a `universe_snapshot`, so a past run's membership is recoverable exactly (SCD-2 plus the
snapshot). `threshold_used` is in the CSV deliberately: a row failing the gate is only interpretable
if the threshold that day is beside it.

---

## 5. R4 — Universe performance

**Reads:** `position_lot` · `lot_closure` · `charge` · `capital_accrual_universe_daily`

| Section | Content |
|---|---|
| Header | Universe · period · account · **basis stated** |
| Capital | Deployed · settlement · peak · average |
| Returns | **Strategy** and **cash**, realised + unrealised, side by side |
| Activity | Buys · sells · turnover · churn |
| Charges | By component, computed vs reported |
| Cost of capital | Attributable only — deployed + settlement, no idle |
| Positions | Open lots with both bases and both deviations |
| Closed | Per lot: holding period, both P&Ls, charges, interest |

**No idle cash anywhere in this report** (D-169 / `UNIFIED-PNL.md` §4.1). Its presence would make the
peer comparison measure cash management rather than strategy.

---

## 6. R5 — Peer comparison

**One table, one basis, named in the header.**

| Universe | Deployed | Strategy ret % | Cash ret % | Charges % | CoC % | Turnover | Hit rate | Avg hold |
|---|---|---|---|---|---|---|---|---|

Plus horizontal bars for the chosen metric. A basis toggle switches every column at once — it is
never possible to have one universe on strategy basis and another on cash.

---

## 7. R6 — Monthly account statement

**Reads:** everything. The document an investor actually receives.

| Section | Notes |
|---|---|
| Cover | Investor (surrogate key, **no PAN**), account, broker, period |
| Capital | Opening · deposits · withdrawals · closing |
| Per universe | Deployed, return on both bases, charges |
| Account roll-up | Universes summed **plus idle drag** |
| Cost of capital | Three buckets, rate, Actual/365 |
| Charges | By component, computed vs reported |
| Holdings | At period end, both bases |
| Closed trades | The register |
| Notes | Any reconciliation exception, any provisional charge rate |

The notes section is not filler. If a charge rate is still provisional (`CHARGES-MODEL.md` §5) or a
reconciliation exception is open, the statement says so — a clean-looking statement over an unresolved
discrepancy is worse than a caveated one.

---

## 8. R7 — Closed-trade register

One row per `lot_closure`. The workhorse CSV.

```
closure_id, universe, isin, symbol, acquired_on, closed_on, holding_days,
quantity, unit_cost, synthetic_cost_basis, unit_proceeds,
cash_pnl, strategy_pnl, buy_charges, sell_charges,
cost_of_capital, provenance, harvest_chain_id, term, funds_credited_on
```

`synthetic_cost_basis` and `harvest_chain_id` are present on every row even when null — their
presence is what makes a harvested position traceable years later without joining to guess.

`funds_credited_on` is **observed, never assumed** (D-050/D-080), so it may be null for a recent sale.

---

## 9. R10 — Tax computation

**Reads:** `tax_gain` · `tax_loss_pool` · `tax_setoff` · `tax_exemption_usage` · `tax_computation`

| Section | Content |
|---|---|
| Header | Investor (surrogate key), FY, **declared slab**, generated-at |
| Gains | Per disposal under **tax FIFO**, with `provenance` (ATOM / EXTERNAL) |
| Class split | Equity · commodity · global — **different rates apply** |
| Term split | STCG / LTCG per class |
| Loss pool | By term and vintage, 8-year window, with expiry |
| Set-off | Each application, in legal order (`sequence_no`) |
| Exemption | ₹1.25 L, **equity LTCG only**, per PAN per FY |
| Liability | Computed |
| **Total vs ATOM gains** | Both shown; set-off uses ATOM's only (D-070c) |
| Disclaimer | A computation, not advice; depends on the declared slab (**X7**) |

Rates applied: equity STCG **20% flat**, commodity and global STCG at the **investor's slab**, all
LTCG **12.5%**, exemption ₹1.25 L equity-only per PAN.

> Two caveats printed on the report itself, not buried: the figures depend on a **declared slab**
> ATOM cannot verify, and they cover only what ATOM knows — an investor with trades elsewhere has a
> different real position. The report is an input to a return, not the return.

---

## 10. R12 — Reconciliation exceptions

Push to Telegram **only when non-empty** (§1).

| Exception | Severity |
|---|---|
| Negative residual | 🔴 blocks the run |
| Positive residual | ⚠️ warn |
| `free_quantity` unavailable | ⚠️ warn |
| Unrecognised resting sell | ⚠️ warn |
| Zerodha `discrepancy` flag | ⚠️ warn |
| Broker token changed for an ISIN | ⚠️ warn |
| Dhan `runbal` vs computed principal mismatch | ⚠️ warn |
| Unmapped ledger narration | ⚠️ needs classification |

---

## 11. Generation and archival

| | |
|---|---|
| On demand | Console, rendered from the API |
| Scheduled | R3 Saturday · R6 month end · R10 quarterly + FY end |
| PDF | Server-side from the same data as the CSV — **never a screenshot** |
| Archive | S3 + Drive; **R10 permanent** |
| Naming | `{report}-{scope}-{period}.{ext}` |

---

## 12. Open items

| ID | Item |
|---|---|
| — | R6 PDF template and branding (navy, matching the console) |
| — | Confirm whether investors receive R6 by email or Drive link only. **Proposed: Drive link**, since email would need an address stored and D-069e minimises stored personal data |
| **Q-313** | 🔴 Provisional STT rates make every charge figure provisional until verified (`CHARGES-MODEL.md` §5.1) |
