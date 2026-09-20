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
| **INDEX** | 27 | 100 | 30 | **Split by index segment — see §2A.** Not one pool |
| **SECTOR** | 46 | 108 | 43 | Split into sector groups (§3) |
| **FACTOR** | 33 | 52 | 18 | Momentum, quality, value, low-volatility, equal-weight, ESG |

**Every bucket splits further. None is a correlation pool in itself.** A momentum ETF is not a
proxy for a Nifty 50 ETF even though both track broad-ish baskets — the factor tilt *is* the
exposure being sold.

---

## 2A. INDEX buckets — split by market-cap segment (D-100)

> "Create buckets on index ETFs too — Nifty 50 ETF bucket, Smallcap 250 ETF bucket. Why are
> they ignored?"

**A fair correction of the first pass.** It demanded sector-level precision for SECTOR while
leaving 100 index trackers in one undifferentiated pool — which would permit swapping a
Nifty 50 ETF for a Smallcap 250 ETF. That books the loss but changes the market-cap exposure
completely, the very error the sector rule exists to prevent.

| Index bucket | ETFs | Liquid | Harvest | Indices covered |
|---|---|---|---|---|
| **LARGECAP_50** | 32 | **7** | ✅ | Nifty 50, BSE Sensex |
| **MIDCAP** | 16 | **9** | ✅ | Nifty Midcap 150 / 100 / 50, BSE Midcap Select |
| **SMALLCAP** | 8 | **5** | ✅ | Nifty Smallcap 250, Smallcap 100 |
| **BROAD_MARKET_500** | 7 | **4** | ✅ | Nifty 500, BSE 500, Total Market, Multicap |
| **NEXT_50** | 15 | 3 | ⚠️ thin | Nifty Next 50, BSE Sensex Next 30/50 |
| **NIFTY_100** | 6 | 2 | ⚠️ thin | Nifty 100 |
| **NIFTY_200** | 1 | **0** | ❌ | Nifty 200 |
| **MSCI_INDIA** | 4 | **0** | ❌ | MSCI India |
| **IPO_THEME** | 2 | **0** | ❌ | BSE Select IPO |

**LARGECAP_50 deliberately merges Nifty 50 and BSE Sensex.** They track the same large-cap
segment and historically correlate around 0.99, so they are near-perfect proxies for each other.
The 0.85 correlation floor (D-070a) independently validates every pair before it is offered, so
a merge that turned out to be wrong would be caught by the floor rather than silently executed.

**Liquid LARGECAP_50 pool:** BSLNIFTY, GROWWNIFTY, NIFTYBEES, NIFTYCASE, NIFTYETF, NIFTYIETF,
SETFNIF50 — seven mutually substitutable trackers. Along with GOLD (17) and SILVER (14), this is
among the cleanest harvesting available.

> ⚠️ **Whether NEXT_50 should merge into LARGECAP_50 is a genuine question (Q-200).** Nifty
> Next 50 is a *different* basket — companies ranked 51–100 — and historically correlates with
> Nifty 50 at roughly 0.85–0.90, right at the floor. Merging would grow a thin pool from 3 to
> 10; keeping them apart is more conservative. *Recommendation: keep separate, and let an
> operator who disagrees lower the correlation floor.*

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
| `BSE Top 10 Banks` | INDEX | **SECTOR / BANKING** | "top 10" matched a broad-market rule first |
| `Nifty 500 Healthcare` | INDEX / BROAD_MARKET_500 | **SECTOR / PHARMA** | "nifty 500" matched before "healthcare" — the symbol `HEALTHCARE` landed in a broad-market pool |
| `BSE MidSmall Private Banks` | INDEX / MIDSMALLCAP | **SECTOR / BANKING** | "midsmall" matched before "banks" |
| `Nifty LargeMidcap 250` | INDEX / MIDCAP | **INDEX / LARGEMIDCAP** | "midcap" matched before "largemid" |
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
| Q-196 | Confirm the three-bucket split (INDEX / SECTOR / FACTOR), the 9 index buckets and the 15 sector groups |
| ~~Q-197~~ | ✅ Resolved by D-100 — index ETFs harvest within their own market-cap segment, not across INDEX as a whole |
| Q-200 | Merge NEXT_50 into LARGECAP_50? Correlation sits at roughly 0.85–0.90, right on the floor *(Rec: keep separate)* |
| Q-198 | Should FACTOR ETFs be harvestable within-factor only (momentum→momentum), or across factors? *(Rec: within-factor only)* |
| Q-199 | Sector groups are a maintained mapping. Who adds a group when NSE lists a new theme — the LLM proposes and the operator confirms, same as classification? |

---

## 7. Full census — every one of the 350 ETFs is bucketed (D-101)

**Unbucketed: 0.** Every ETF in the NSE universe lands in a defined bucket once classification
is evaluated **sector-first, then factor, then index**. That ordering is itself the fix for the
bugs in §4: `BSE Top 10 Banks` and `BSE MidSmall Private Banks` both resolve correctly to
SECTOR/BANKING instead of being mis-read as market-cap segments.

| Bucket | ETFs | Liquid | | Bucket | ETFs | Liquid |
|---|---|---|---|---|---|---|
| FACTOR *(split, §8)* | 57 | 18 | | SECTOR/FINANCIAL_SERVICES | 5 | 3 |
| EXCLUDED_DEBT | 38 | 14 | | SECTOR/PSU | 5 | 2 |
| SECTOR/BANKING | 37 | 9 | | SECTOR/AUTO | 5 | 5 |
| INDEX/LARGECAP_50 | 32 | 7 | | SECTOR/MANUFACTURING | 4 | 0 |
| COMMODITY/GOLD | 26 | 17 | | SECTOR/OTHER_THEMATIC | 4 | 0 |
| COMMODITY/SILVER | 19 | 14 | | INDEX/MSCI_INDIA | 4 | 0 |
| INDEX/NEXT_50 | 15 | 3 | | SECTOR/DEFENCE | 3 | 3 |
| INDEX/MIDCAP | 15 | 9 | | SECTOR/CHEMICALS | 2 | 1 |
| SECTOR/IT | 10 | 4 | | SECTOR/INTERNET | 2 | 1 |
| INDEX/SMALLCAP | 8 | 5 | | INDEX/IPO_THEME | 2 | 0 |
| SECTOR/PHARMA_HEALTHCARE | 8 | 5 | | INDEX/LARGEMIDCAP | 1 | 0 |
| SECTOR/FMCG_CONSUMPTION | 8 | 1 | | INDEX/NIFTY_200 | 1 | 0 |
| SECTOR/INFRA | 8 | 4 | | EXCLUDED_HYBRID | 1 | 0 |
| GLOBAL | 6 | 5 | | | | |
| SECTOR/ENERGY | 6 | 3 | | | | |
| SECTOR/METALS | 6 | 3 | | | | |
| INDEX/NIFTY_100 | 6 | 2 | | | | |
| INDEX/BROAD_500 | 6 | 3 | | | | |

**Two proposed buckets are empty and are removed:** `INDEX/CONCENTRATED_TOP_N` and
`INDEX/MIDSMALLCAP`. Both existed only to catch ETFs that the sector-first ordering now places
correctly.

### Two buckets are not real correlation pools

| Bucket | Members | Problem |
|---|---|---|
| **SECTOR/OTHER_THEMATIC** | Nifty India Tourism, Nifty MNC ×2, Nifty Services Sector | **A catch-all, not a sector.** Tourism and MNC have no common exposure. Harvesting between them would swap one theme for an unrelated one |
| **SECTOR/MANUFACTURING** | Nifty India Manufacturing ×3, **Nifty Commodities** | Manufacturing and Commodities are different exposures sharing a bucket only through a keyword |

*Neither currently matters — no member is liquid, so none enters the universe. But a fake pool
is a latent correctness bug, so:* **recommended fix — dissolve `OTHER_THEMATIC` into
single-member buckets (explicitly "no proxy available"), and split `Nifty Commodities` out of
MANUFACTURING.* (Q-201)

---

## 8. FACTOR must split too — the same error, found again (D-102)

The INDEX correction in §2A applies equally here, and was missed for the same reason: **57 ETFs
sat in one FACTOR pool.** Momentum, value, quality and low-volatility are *different, often
inversely-behaving* exposures. Harvesting a momentum ETF into a value ETF would swap the factor
while appearing to preserve it — precisely the error the bucket scheme exists to prevent.

| Factor sub-bucket | ETFs | Liquid | Harvest |
|---|---|---|---|
| **MOMENTUM** | 10 | **7** | ✅ HDFCMOMENT, MOM30IETF, MOMENTUM30, MOMENTUM50, MOMMIDCAP, MOMOMENTUM, SBIMIDMOM |
| VALUE | 9 | 2 | ⚠️ NV20IETF, VAL30IETF |
| QUALITY | 8 | 2 | ⚠️ FLEXIADD, NIFTYQLITY |
| LOW_VOLATILITY | 6 | 2 | ⚠️ ALPL30IETF, LOWVOLIETF |
| MOMENTUM_QUALITY_COMBO | 5 | 2 | ⚠️ MIDSMALL, SMALLCAP |
| ALPHA | 3 | 2 | ⚠️ ALPHA, ALPHAETF |
| EQUAL_WEIGHT | 9 | **1** | ❌ no proxy |
| DIVIDEND | 4 | **0** | ❌ no proxy |
| SHARIAH / ESG / GROWTH | 1 each | **0** | ❌ no proxy |

**Only MOMENTUM is reliably harvestable** among factor ETFs. Everything else is thin or
impossible.

> A further question this raises (Q-202): should a factor bucket also be split by **market-cap
> segment**? `MOMENTUM` currently mixes `Nifty 200 Momentum 30` with `Nifty Midcap 150 Momentum
> 50` — same factor, different cap. *Recommendation: yes for correctness, but it would reduce
> the only healthy factor pool from 7 to roughly 4 and 3. The 0.85 correlation floor may be the
> better filter here — let it decide rather than pre-splitting.*

---

## 9. Harvest viability — the complete picture

> ⚠️ **SUPERSEDED BY D-112.** The counts in this section were computed with a liquidity
> filter applied to proxies, which was wrong: bucketing is purely tracking-based, and a dormant
> ETF tracking the same index is still a valid proxy. On the corrected basis **262 of 311
> tradable ETFs (84%) have a same-index proxy**, 29 have a same-group proxy, and only **20**
> have none. Liquidity is handled at execution as an advisory with override (D-113).


**Reliably harvestable (≥4 liquid proxies):** GOLD 17 · SILVER 14 · BANKING 9 · MIDCAP 9 ·
LARGECAP_50 7 · MOMENTUM 7 · PHARMA/HEALTHCARE 5 · AUTO 5 · SMALLCAP 5 · GLOBAL 5 · IT 4 ·
INFRA 4

**Thin (2–3):** NEXT_50 · BROAD_500 · ENERGY · METALS · FINANCIAL_SERVICES · DEFENCE · PSU ·
NIFTY_100 · VALUE · QUALITY · LOW_VOLATILITY · ALPHA · MOMENTUM_QUALITY_COMBO

**Impossible (0–1):** FMCG_CONSUMPTION · CHEMICALS · INTERNET · MANUFACTURING · OTHER_THEMATIC ·
MSCI_INDIA · IPO_THEME · NIFTY_200 · LARGEMIDCAP · EQUAL_WEIGHT · DIVIDEND · SHARIAH · ESG ·
GROWTH

**14 buckets cannot be harvested at all.** Every holding in one of them is a position that can
never have its loss booked while keeping exposure — which the harvest screen must state plainly
against the holding, with the reason.
