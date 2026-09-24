# Why Deviation Is Measured in Percent, Not Rupees

**Status:** 🟢 Analysis · supports D-026
**Date:** 2026-09-24
**Data:** 127 liquid tradable ETFs, real prices, 17-Sep-2026

The archived system ranked on **rupee difference** (`current − mean`). ATOM ranks on
**percentage**. This document shows what actually changes, using real ETFs at real prices.

---

## 1. The fact that decides it: price dispersion within a category

| Bucket | Liquid ETFs | Min LTP | Median | Max LTP | **Spread** |
|---|---|---|---|---|---|
| INDEX | 29 | ₹9.35 | ₹23.25 | ₹773.40 | **83×** |
| SECTOR | 44 | ₹9.40 | ₹32.25 | ₹582.09 | **62×** |
| COMMODITY | 31 | ₹8.68 | ₹126.80 | ₹226.51 | 26× |
| GLOBAL | 5 | ₹21.90 | ₹238.90 | ₹330.33 | 15× |
| FACTOR | 18 | ₹9.77 | ₹30.12 | ₹85.50 | 9× |
| **All** | **127** | **₹8.68** | **₹32.46** | **₹773.40** | **89×** |

**Within a single category, ETFs differ in price by up to 83×.** That is what makes the choice
consequential. If every ETF in a bucket traded near ₹100, the two metrics would rank almost
identically and this would not be worth a document.

A 5% fall is worth ₹1.09 on MAHKTECH (₹21.90) and ₹23.15 on HNGSNGBEES (₹463.01) — **21× more
rupees for exactly the same discount.**

---

## 2. Worked scenario — one morning, five real ETFs

Real symbols, real 17-Sep prices, with the cheaper ETFs genuinely the most oversold:

| Symbol | Price | 50-day mean | % below | ₹ below |
|---|---|---|---|---|
| JUNIORBEES | 773.40 | 781.21 | −1.0% | **−7.81** |
| NIFTYBEES | 266.36 | 270.42 | −1.5% | −4.06 |
| MONIFTY500 | 23.25 | 24.22 | −4.0% | −0.97 |
| GROWWNIFTY | 9.45 | 10.74 | −12.0% | −1.29 |
| NIFTYCASE | 9.35 | 11.40 | **−18.0%** | −2.05 |

### Ranked by rupee difference (archived system)
```
1. JUNIORBEES    -7.81   (-1.0%)   ← BOUGHT
2. NIFTYBEES     -4.06   (-1.5%)
3. NIFTYCASE     -2.05  (-18.0%)
4. GROWWNIFTY    -1.29  (-12.0%)
5. MONIFTY500    -0.97   (-4.0%)
```

### Ranked by percentage (ATOM)
```
1. NIFTYCASE    -18.0%  (₹-2.05)   ← BOUGHT
2. GROWWNIFTY   -12.0%  (₹-1.29)
3. MONIFTY500    -4.0%  (₹-0.97)
4. NIFTYBEES     -1.5%  (₹-4.06)
5. JUNIORBEES    -1.0%  (₹-7.81)
```

**The two orderings are almost exactly inverted.** Rupee ranking buys the ETF that has barely
moved and puts the most oversold one third.

### What that costs — same ₹10,000, recovery to the mean

| Symbol | Qty | Cost | Value at mean | Gain | **Return** |
|---|---|---|---|---|---|
| **JUNIORBEES** *(rupee pick)* | 12 | ₹9,281 | ₹9,375 | **₹94** | **1.0%** |
| NIFTYBEES | 37 | ₹9,855 | ₹10,005 | ₹150 | 1.5% |
| MONIFTY500 | 425 | ₹9,881 | ₹10,293 | ₹412 | 4.2% |
| GROWWNIFTY | 1,047 | ₹9,894 | ₹11,243 | ₹1,349 | 13.6% |
| **NIFTYCASE** *(% pick)* | 1,058 | ₹9,892 | ₹12,064 | **₹2,171** | **22.0%** |

**₹94 against ₹2,171 — a 23× difference on the same capital, on the same morning.**

---

## 3. Why rupee ranking fails here, precisely

**It ranks price level, not cheapness.** Because rupee gap scales with price, an expensive ETF
drifting 1% outranks a cheap one collapsing 18%. At 83× dispersion, the metric is close to
"always buy the most expensive ETF in the category" — the price tag does the sorting, and the
actual dislocation barely registers.

**Two further inconsistencies:**

1. **The exit is already a percentage.** The profit target is 3.5% (D-056), not ₹3.50. Ranking
   entries in rupees while exiting in percent means the two halves of the strategy measure
   different things. A ₹7.81 gap on JUNIORBEES is 1.0% — nowhere near a 3.5% target — while a
   ₹2.05 gap on NIFTYCASE is 18%, five times the target.

2. **Order size is fixed in rupees, so quantity adjusts.** Buying ₹10,000 of a ₹773 ETF gets 12
   units; of a ₹9.35 ETF, 1,058 units. The per-unit rupee gap therefore says nothing about the
   position's outcome — only the percentage does. **Rupee-per-unit is not a quantity the
   portfolio ever experiences.**

---

## 4. When rupee ranking would be defensible

To be fair to it: if every ETF in a category traded in a narrow band — say ₹90 to ₹110 — the two
metrics would agree almost perfectly, and rupee difference would be marginally cheaper to
compute. Some strategies also deliberately want a price-level tilt.

Neither applies here. The dispersion is 83× within a single category, and no decision anywhere
in ATOM expresses a preference for expensive instruments.

---

## 5. Conclusion

**Percentage, at 4 decimal places internally and 2 for display (D-026).**

The archived system's rupee ranking was systematically buying whichever ETF happened to carry
the largest price tag, and calling it the most oversold. **ATOM will pick differently, and
visibly so** — that is the correction working, not a regression. Worth confirming on history
before going live (V2-1).

---

## Appendix — the guard this implies

Percentage ranking has one failure mode rupee ranking does not: **a very cheap ETF makes large
percentage moves on small absolute moves.** An ETF at ₹9.35 moving one tick (₹0.01) is 0.107%;
the same tick on JUNIORBEES is 0.0013%. Sub-rupee instruments are therefore noisier in percentage
terms.

Two existing controls already cover this — the **volume filter** (D-027) excludes the illiquid
micro-priced ETFs where this bites hardest, and the **corporate-action threshold with peer
comparison** (D-090) catches implausible single-day moves. Worth watching in the first months of
live running, but no additional rule is proposed. (Q-246)
