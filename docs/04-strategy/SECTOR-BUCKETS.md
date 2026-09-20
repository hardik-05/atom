# Sector Buckets and Correlation Pools

**Status:** 🟠 First-pass analysis complete · classification needs operator review
**Implements:** D-096 · supports tax-loss harvesting proxy matching
**Data:** all 350 ETFs, `99-vendor-docs/nse/MW-ETF-17-Sep-2026.csv`

---

## 1. Why this exists

> "Correlation should be among the same sector only. An auto sector ETF should compute
> correlation with auto only, not a Nifty 50 ETF. We need a thorough analysis on category, bucket
> all the equity in these buckets, and do the correlation computation for each bucket only."

Two reasons this is right:

1. **Correctness.** A harvest proxy must preserve the exposure being sold. Selling an auto ETF
   and buying a Nifty 50 ETF books the loss but silently changes what you own.
2. **Cost.** All-pairs correlation over 350 ETFs is ~61,000 pairs. Restricted to within-bucket
   pairs it collapses to a few hundred — and every discarded pair was one that should never
   have been a candidate anyway.

---

## 2. Three-level scheme

```
CATEGORY (NSE)  →  BUCKET  →  SECTOR GROUP  →  correlation pool
   EQUITY          SECTOR       BANKING         9 liquid ETFs
   EQUITY          BROAD        NIFTY_50        pool of Nifty 50 trackers
   COMMODITY       —            GOLD            17 liquid ETFs
```

### Equity buckets

| Bucket | Sub-categories | ETFs | Liquid | Correlation pool |
|---|---|---|---|---|
| **BROAD** | 27 | 100 | 30 | Broad-market trackers — Nifty 50, Sensex, Next 50, midcap, smallcap |
| **SECTOR** | 46 | 108 | 43 | Further split into sector groups (§3) |
| **FACTOR** | 33 | 52 | 18 | Momentum, quality, value, low-volatility, equal-weight, ESG |

**A proxy must come from the same bucket, and within SECTOR from the same group.** A momentum
ETF is not a proxy for a Nifty 50 ETF even though both are broad-ish — the factor tilt is the
exposure.

---

## 3. Sector groups and proxy availability — the operational finding

Harvesting only works if a **liquid, differently-ISIN'd proxy exists**. Measured on 17-Sep:

| Sector group | ETFs | Liquid | Harvest viable? |
|---|---|---|---|
| BANKING | 37 | **9** | ✅ |
| PHARMA / HEALTHCARE | 8 | **5** | ✅ |
| AUTO | 5 | **5** | ✅ |
| IT | 10 | **4** | ✅ |
| INFRA | 8 | **4** | ✅ |
| ENERGY | 6 | 3 | ⚠️ thin |
| METALS | 6 | 3 | ⚠️ thin |
| FINANCIAL SERVICES | 5 | 3 | ⚠️ thin |
| DEFENCE | 3 | 3 | ⚠️ thin |
| PSU | 5 | 2 | ⚠️ thin |
| **FMCG / CONSUMPTION** | 8 | **1** | ❌ **impossible** |
| **CHEMICALS** | 2 | **1** | ❌ **impossible** |
| **INTERNET** | 2 | **1** | ❌ **impossible** |
| **MANUFACTURING** | 4 | **0** | ❌ **impossible** |
| **OTHER THEMATIC** | 4 | **0** | ❌ **impossible** |
| GOLD | 26 | **17** | ✅ best pool |
| SILVER | 19 | **14** | ✅ |

> ⚠️ **Five sector groups cannot be harvested at all**, because only one liquid ETF exists (or
> none) and a proxy must be a different ISIN (D-070a). If FMCGIETF is sitting at a loss, there
> is no way to book it while keeping FMCG exposure.
>
> **This must be visible in the UI, not discovered at execution.** The harvest screen should
> mark such holdings **"no proxy available"** with the reason, rather than simply omitting them
> and leaving the operator wondering why a loss-making position never appears.

**The corollary is a genuinely useful planning insight:** gold, silver, banking, pharma and auto
holdings are the ones that can be harvested reliably. That is worth knowing *before* a position
is opened, not after it has fallen.

---

## 4. ⚠️ The classification is not trustworthy yet

The first pass was rule-based, and it is demonstrably wrong in places:

| Sub-category | Rule said | Should be | Why it failed |
|---|---|---|---|
| `BSE Top 10 Banks` | BROAD | **SECTOR / BANKING** | "top 10" matched a broad-market rule first |
| `Nifty 500 Healthcare` | BROAD | **SECTOR / PHARMA** | "nifty 500" matched before "healthcare" |
| `Nifty Dividend Opportunities 50` | SECTOR | **FACTOR** | "dividend" was treated as a sector word |
| `BSE 500 Dividend Leaders 50` | BROAD | **FACTOR** | same |
| `Nifty 50 Shariah` | BROAD | arguable — a screened variant | no rule covers screens |

**This is the argument for D-032's pipeline, demonstrated rather than asserted.** Keyword rules
get roughly the right shape and then fail on ordering and ambiguity. So:

1. Rules produce a **first-pass proposal**.
2. The **LLM classifier** (NVIDIA five-model cascade, D-015) handles sector assignment, which is
   exactly the judgement task rules are bad at.
3. **The operator confirms**, and the stored value is authoritative.
4. A mis-bucketed ETF is a **correctness bug in harvesting**, not a cosmetic issue — it would
   swap exposure while appearing to preserve it. Review is not optional.

---

## 5. Correlation computation

- **On demand only** (D-095) — computed when the operator requests a harvest proposal, never on
  a schedule.
- **Within-pool only.** Pairs are formed inside a sector group (or BROAD/FACTOR pool); cross-pool
  pairs are never computed or offered.
- **Pearson on daily log returns**, 250-day window (D-070a).
- Both ETFs must pass the volume filter (D-070a) and be a different ISIN.
- Minimum correlation is a config floor, default 0.85 (D-070a).

Cost at these pool sizes is trivial — the largest pool is 9 liquid banking ETFs, or 36 pairs.

---

## 6. Open items

| ID | Item |
|---|---|
| Q-196 | Confirm the three-bucket split (BROAD / SECTOR / FACTOR) and the 15 sector groups |
| Q-197 | Should BROAD ETFs be harvestable against each other (e.g. one Nifty 50 tracker for another)? *(Rec: yes — 22 Nifty 50 ETFs exist and they are near-perfect proxies, arguably the cleanest harvest in the whole universe)* |
| Q-198 | Should FACTOR ETFs be harvestable within-factor only (momentum→momentum), or across factors? *(Rec: within-factor only)* |
| Q-199 | Sector groups are a maintained mapping. Who adds a group when NSE lists a new theme — the LLM proposes and the operator confirms, same as classification? |
