# Taxation Model — Indian ETFs

**Status:** 🟠 Researched · needs operator confirmation on slab rate and boundary policy
**Implements:** D-116 · supersedes the single 20% STCG rate in D-070a
**Date:** 2026-09-23

> Design-constraints summary from public sources. **Not tax advice.** Confirm with a CA before
> filing. Rates below reflect the Finance (No. 2) Act 2024 regime as it stands for FY 2025-26
> and FY 2026-27.

---

## 1. The three buckets are taxed differently — confirmed

> "As per my awareness there is different taxation for all of these, and hence one tax number
> should not be for everything."

Correct, and the difference is larger than a rate change — the **basis** differs.

| | **EQUITY** | **COMMODITY** (gold/silver) | **GLOBAL** |
|---|---|---|---|
| **STCG** (held ≤12 months) | **20% flat** | **Investor's slab rate** | **Investor's slab rate** |
| **LTCG** (held >12 months) | 12.5% | 12.5% | 12.5% |
| Indexation | No | **No** (withdrawn) | No |
| Annual exemption | **₹1.25 lakh** on LTCG | **None** | **None** |
| STT on trade | Yes | **No** | No |
| Holding period for LTCG | 12 months | 12 months | 12 months |

Plus **4% health and education cess** on the computed tax, and surcharge at higher incomes.

### Why commodity and global are not a fixed percentage

Their STCG is taxed **at the investor's marginal slab rate**, not at a statutory flat rate. So
it depends on that person's total income for the year and can be 5%, 20%, or 30% — before
surcharge and cess. **This cannot be a system-wide constant**; it is a per-investor input that
may change year to year.

*This is the substantive correction to D-070a, which assumed a single 20% STCG rate for
everything. For a 30%-slab investor, commodity STCG is 30% + cess ≈ **31.2%**, over half again
the equity rate.*

### Recent changes that matter

- **Finance (No. 2) Act 2024**, from 23 July 2024: LTCG unified at 12.5% without indexation;
  holding period for listed securities set at 12 months.
- **From FY 2025-26:** gold, silver and international ETFs left **Section 50AA**. Only funds
  holding >65% in debt/money-market instruments remain within it. This is why they now get the
  12-month/12.5% treatment rather than always-slab.

---

## 2. What this changes in ATOM

### 2.1 Config (D-116)

Replacing the single `stcg_rate_pct`:

| Key | Scope | Meaning |
|---|---|---|
| `stcg_rate_equity_pct` | trading account | Statutory flat rate — 20.0000 today |
| `stcg_rate_commodity_pct` | trading account | **The investor's marginal slab rate** |
| `stcg_rate_global_pct` | trading account | **The investor's marginal slab rate** |
| `ltcg_rate_pct` | trading account | 12.5000, all three buckets |
| `cess_pct` | trading account | 4.0000 on computed tax |
| `ltcg_exemption_equity_inr` | trading account | 125000.0000 — **equity only** |
| `ltcg_holding_days` | global | 365 |

All with **no defaults** (D-038) — the operator supplies each one, which matters most for the
slab rates, since only they know their income bracket.

### 2.2 🔴 Harvesting must rank by tax saved, not by loss size

The harvest screen currently ranks loss-making positions by size. With three different rates
that is wrong:

| Position | Loss | Bucket | Rate | **Tax saved** |
|---|---|---|---|---|
| A | ₹12,000 | Equity | 20% + cess = 20.8% | **₹2,496** |
| B | ₹10,000 | Commodity | 30% + cess = 31.2% | **₹3,120** |

**Position B is the better harvest despite the smaller loss.** Ranking by loss would pick A and
leave ₹624 on the table. The screen must show and sort by **estimated tax saved**.

### 2.3 🔴 Set-off rules constrain which losses offset which gains

| Loss type | Can offset |
|---|---|
| **Short-term capital loss** | STCG **and** LTCG |
| **Long-term capital loss** | **LTCG only** |

So a short-term loss is strictly more useful. Unabsorbed losses carry forward **8 assessment
years**, but only if the return is filed on time. ATOM should track losses by type and vintage,
not as one pooled number.

### 2.4 ⚠️ The 12-month boundary creates a real conflict with the sell rule

The strategy exits at a fixed profit target, so nearly every trade is short-term. But a
position that has *not* hit its target and is approaching 12 months is about to get materially
cheaper to sell:

| Bucket | Sell at 11 months | Sell at 12 months + 1 day | Saving |
|---|---|---|---|
| Equity | 20% | 12.5% | **7.5 points** |
| Commodity/global at 30% slab | 30% | 12.5% | **17.5 points** |

On a ₹10,000 gain in a commodity ETF, waiting a few extra days is worth **₹1,750**.

**But ATOM places a sell order every morning regardless of holding period** (D-063), so a
position that hits its target at day 360 is sold at the short-term rate when five more days
would have halved the tax.

*This is not a bug in anything decided so far — it is an interaction nobody has ruled on.*
Options (Q-208):

| Option | Effect |
|---|---|
| **(a)** Ignore it | Simple. Leaves money on the table occasionally |
| **(b)** Warn only | Daily Status flags "LTCG in N days" on positions within a configurable window; operator decides |
| **(c)** Defer the sell | Suppress the sell order for positions within N days of 12 months, unless overridden |

*Recommendation: **(b)**. It surfaces the fact without the engine silently overriding a target
the operator set, and it matches the advisory-with-override pattern used everywhere else
(D-094, D-113).*

### 2.5 Reporting

The tax screen must separate: **STCG by bucket** (three different rates), **LTCG by bucket**
(one rate, but the equity exemption applies only to equity), cess, and carried-forward losses
by type. One blended number would be wrong in both directions.

---

## 3. Open items

| ID | Item |
|---|---|
| Q-208 | 12-month boundary policy — ignore, warn, or defer the sell |
| Q-209 | What is the investor's marginal slab rate for commodity/global STCG? Needed per investor |
| Q-210 | Should surcharge be modelled, or is slab + cess sufficient for a planning estimate? *(Rec: slab + cess; surcharge applies above ₹50 lakh total income)* |
| Q-211 | Track carried-forward losses across financial years, or start each FY clean? *(Rec: track — they are worth real money for 8 years)* |
| Q-212 | Confirm the ₹1.25 lakh equity LTCG exemption is applied at investor level across all their accounts, not per trading account |

---

## Sources

- [Finnovate — ETF taxation India 2026](https://www.finnovate.in/learn/blog/etf-taxation-india)
- [HDFC Sky — ETF taxation, capital gains and dividend rules](https://hdfcsky.com/sky-learn/etf/taxation-on-etf-capital-gains-taxation-on-etfs)
- [IIFL — Gold ETF capital gains tax post Finance Act 2024](https://www.iifl.com/blogs/gold-loan/gold-etf-tax-in-india-2026-post-finance-act-2024-rules)
- [TaxGuru — Gold, silver ETF and fund taxation](https://taxguru.in/income-tax/gold-etf-silver-etf-gold-silver-mutual-fund-taxation-india-complete-guide-income-tax-act-2025.html)
- [Angel One — Foreign stocks, mutual funds and ETFs FY2025-26](https://www.angelone.in/news/taxation/how-are-foreign-stocks-mutual-funds-and-etfs-taxed-in-fy2025-26)
- [Business Standard — Budget 2024 relief for gold ETFs and international schemes](https://www.business-standard.com/amp/budget/news/budget-2024-brings-relief-for-gold-etfs-equity-fofs-international-schemes-124072301258_1.html)
- [Zerodha Varsity — Foreign stocks and taxation](https://zerodha.com/varsity/chapter/foreign-stocks-and-taxation/)
