# NAV Premium Check

**Status:** 🟢 Specified · backed by live NSE data (17-Sep-2026, 350 ETFs)
**Implements:** D-034, D-035 · resolves Q-147, Q-148
**Data:** `docs/99-vendor-docs/nse/MW-ETF-17-Sep-2026.csv`

---

## 1. What this feature does

An ETF has two prices: what it **trades at** (LTP) and what its **underlying assets are
worth** (NAV / i-NAV). The gap is a premium or discount.

The mean-reversion engine ranks on deviation from an ETF's *own price history*. That says
nothing about whether the price is sane relative to the assets it holds. A fund can be well
below its own 50-day mean **and simultaneously** 40% above the value of what it owns — and
buying it means paying ₹140 for ₹100 of assets.

The NAV premium check is a **veto gate**, applied after ranking and before ordering.

### The rule

```
if not nav_check_enabled:            → PASS
if LTP <= NAV:                       → PASS   (trading at or below asset value)
if (LTP - NAV) / NAV <= tolerance:   → PASS   (premium within category tolerance)
otherwise:                           → BLOCK  (reason logged, next candidate considered)
```

**Trading below NAV is always acceptable** — there is no lower bound. The tolerance only
constrains how far *above* NAV a purchase may go.

### Configuration

| Setting | Scope | Default | Notes |
|---|---|---|---|
| `nav_check_enabled` | **trading account × category** | **ON** | Master toggle; OFF disables the gate entirely |
| `nav_premium_tolerance_pct` | **trading account × category** | Equity 2.00 · Commodity 2.00 · Global **see §4** | Editable before any run |

A **trading account is one investor's account at one broker** (D-037), so Person A's Upstox
equity tolerance and Person A's Dhan equity tolerance are separate, independently editable
values. Every figure in this document is a **default**, not a constant — see
[`../01-architecture/CONFIGURATION-MODEL.md`](../01-architecture/CONFIGURATION-MODEL.md).

Stored and compared at **4 decimal places**, displayed at 2 (D-026).

---

## 2. Category rename (D-034a)

The third bucket is renamed from **Metals** to **Commodity**, matching NSE's own vocabulary.
The canonical buckets are now **EQUITY · COMMODITY · GLOBAL**.

### NSE CATEGORY values as actually published

Verified against all 350 rows. Note the **inconsistent casing and the trailing word** —
string matching must normalise, not compare literally:

| NSE `CATEGORY` (verbatim) | Count | ATOM bucket |
|---|---|---|
| `EQUITY` | 260 | **EQUITY** |
| `COMMODITY` | 45 | **COMMODITY** (GOLD 26, SILVER 19) |
| `DEBT` | 38 | **EXCLUDED** (Overnight/Liquid 20, GSECS/GILT 14, Bond 4) |
| `GLOBAL INDICES` | 6 | **GLOBAL** ← *not* the string `GLOBAL` |
| `Hybrid` | 1 | **EXCLUDED** — sub-category `Equity/Debt` |

> ⚠️ Two traps for the ETL: the global category is **`GLOBAL INDICES`**, and **`Hybrid`** is
> title-case while every other value is upper-case. Normalise with
> `strip().upper()` and map explicitly; never assume the bucket name equals the NSE string.
> Q-148 is closed by this table.

---

## 3. Impact on EQUITY and COMMODITY — negligible, as intended

Measured across the 17-Sep snapshot:

| Bucket | n | Median premium | Above NAV | Above +2% | Above +2% **and** liquid |
|---|---|---|---|---|---|
| **EQUITY** | 259 | **+0.74%** | 209 | 14 | **4** |
| **COMMODITY** | 44 | **−0.64%** | **0** | 0 | 0 |

- **Commodity never binds.** Not one gold or silver ETF traded above NAV. The gate is
  effectively inert here, which is the right outcome — these track a physical asset with
  functioning arbitrage.
- **Equity barely binds.** At a 2% tolerance only 4 liquid candidates are blocked:
  `INSUREIETF` (+2.73%), `HEALTHY` (+2.39%), `GROWWHOSPI` (+2.22%), `HEALTHIETF` (+2.00%).
  That is ~4% of the 91 liquid equity ETFs — a precise filter, not a blunt one.

A 2% default for both buckets is well calibrated.

---

## 4. ⚠️ GLOBAL — the check disables the entire category

**Every liquid global ETF on NSE trades at a structural premium far beyond any sane
tolerance.** All six, with the volume filter applied:

| Symbol | Volume | LTP | NAV | **Premium** | Passes 1L volume |
|---|---|---|---|---|---|
| MONQ50 | 20,80,987 | 330.33 | 116.69 | **+183.08%** | ✅ |
| MASPTOP50 | 11,26,886 | 104.80 | 66.66 | **+57.22%** | ✅ |
| MAFANG | 6,51,437 | 238.90 | 173.63 | **+37.59%** | ✅ |
| MAHKTECH | 10,36,306 | 21.90 | 17.81 | **+22.96%** | ✅ |
| MON100 | 12,75,524 | 322.85 | 271.53 | **+18.90%** | ✅ |
| HNGSNGBEES | 69,972 | 463.01 | 450.28 | +2.83% | ❌ fails volume |

**With `nav_check_enabled = ON` and any tolerance below ~19%, the global bucket buys
nothing, ever.** The only ETF near a normal premium is the one that fails the liquidity
filter.

### Why this happens — it is not a data error

These premiums are a known structural feature, not noise. SEBI's industry-wide cap on
overseas investment by Indian mutual funds has left these schemes unable to create new units,
so the authorised-participant arbitrage that normally holds an ETF near its NAV **cannot
operate**. Price is set purely by domestic demand against a frozen unit supply, and the
premium persists indefinitely. MONQ50 at +183% means paying **₹330 for ₹117 of assets**.

### Why this matters to the strategy specifically

Mean reversion on *price* offers no protection here. A global ETF can revert to its own mean
while its premium collapses, and the premium is the larger number by far. A 183% premium
normalising is a **−65% move** that no price-history model would anticipate. This is the
single largest tail risk in the current design.

### Options (operator decision required — Q-149)

| # | Option | Consequence |
|---|---|---|
| **A** | Keep tolerance at 2%, accept global is dormant | Safest. Global buys nothing until premiums normalise — which may be years, or never. Two live categories instead of three. |
| **B** | Set global tolerance to ~20% | Admits MON100 and MAHKTECH only. Still paying a ~19% premium, with the collapse risk intact. |
| **C** | Disable the NAV check for global only | Restores the category as originally specified, and accepts the tail risk explicitly rather than by omission. |
| **D** | Rank global on **premium-to-NAV** instead of price deviation | Buy the *least* over-priced global ETF rather than the most price-oversold. A different strategy for this bucket, but arguably the correct one given a frozen unit supply. |
| **E** | Drop global from the strategy | Cleanest. Six instruments, five liquid, all structurally mispriced. |

**Recommendation: A now, D later.** Ship with the 2% tolerance so nothing is bought at a
183% premium by accident, and treat global as a separate design question rather than forcing
it through machinery built for arbitraged instruments.

---

## 5. Logging requirement (D-035)

Every candidate evaluated must record **why it was or was not bought**, with each gate's
result shown separately. The stated requirement: it must be visible that the deviation
condition passed while the NAV condition failed.

Required per-candidate log line, in the `.txt`/`.log` run file and as a structured row:

```
[EQUITY] rank 2/10  INSUREIETF
    mean(50d)        = 24.8130
    LTP              = 25.9100
    deviation        = -4.2310%     → PASS  (most negative among unheld)
    holdings check   = not held     → PASS
    NAV              = 25.2210
    premium to NAV   = +2.7300%     → FAIL  (tolerance 2.0000% for EQUITY)
    funds available  = 20,000.00    → PASS
    DECISION         = SKIPPED — NAV premium 2.7300% exceeds EQUITY tolerance 2.0000%
    next action      = evaluate rank 3 candidate
```

**Rules:**
1. Every gate is logged with its **input values**, not just its verdict — a reader must be
   able to recompute the decision from the log alone.
2. Gates are evaluated and logged **in order**, and evaluation stops at the first failure,
   with the reason naming the failing gate and the threshold it breached.
3. A skipped candidate always states **what happens next** (evaluate next rank / no buy).
4. The same structure applies to sells, averaging and harvest decisions.

Structured columns: `run_id`, `account_id`, `category`, `rank`, `symbol`, `mean_price`,
`ltp`, `deviation_pct`, `nav`, `nav_premium_pct`, `nav_tolerance_pct`, `holdings_status`,
`funds_available`, `gate_failed`, `decision`, `decision_reason`.

---

## 6. Open items

| ID | Item |
|---|---|
| Q-149 | Global category: choose option A–E in §4 |
| Q-150 | i-NAV is missing for 18 of 350 rows, and 3 rows lack NAV or LTP. Behaviour when NAV is unavailable — block, allow, or fall back to i-NAV? |
| Q-151 | Use NAV (end-of-day) or i-NAV (intraday indicative) for the live check? i-NAV is the correct intraday reference but has thinner coverage |
| Q-152 | `Hybrid` — confirm exclusion (1 ETF, sub-category Equity/Debt) |
