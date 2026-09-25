# Harvest Cost Basis — the synthetic basis, in full

**Status:** 🟢 Specified — extends D-019 with the per-unit and averaging rules
**Date:** 2026-09-25
**Applies to:** every proxy lot created by a tax-loss harvest (D-163: proxy chosen manually)

---

## 1. The principle

> **A harvest changes the tax outcome and nothing else.**

Selling a loser and buying a proxy is a *tax* action. It must be **strategy-neutral**: the
position's profit target, its deviation, and when ATOM sells it must all behave exactly as if
the harvest had never happened. If the harvest also reset the target downward, it would be
changing the strategy — which is not what harvesting is for.

This is the operator's framing, and it is right:

> "If you look at it holistically it was a holding which was bought at 100 and not at 90. It
> appears to be 90 on paper due to tax loss."

### Why it matters — the failure it prevents

| | Without carry-over | With carry-over |
|---|---|---|
| A bought | ₹100 | ₹100 |
| Harvest sale | ₹90 (loss ₹10 booked) | ₹90 (loss ₹10 booked) |
| Proxy B basis for the sell trigger | **₹90** | **₹100** |
| Sell target at 3.5% | ₹93.15 | ₹103.50 |
| ATOM reports | "+3.5% profit" ✅ | "+3.5% profit" ✅ |
| Investor's actual position | **−₹6.85 vs original capital** 🔴 | +₹3.50 ✅ |

Without the carry-over the harvest **manufactures a phantom profit**. ATOM would report a
winning trade while the investor is still below the capital they committed. That is the single
most damaging thing a reporting system can do, and the carry-over is what prevents it.

---

## 2. Two bases, two jobs — never conflated

Every lot carries **two** unit costs. They answer different questions and are used by different
parts of the system.

| | **Actual (cash) basis** | **Synthetic (strategy) basis** |
|---|---|---|
| Column | `position_lot.unit_cost` | `position_lot.synthetic_cost_basis` |
| Value | what was really paid, all-in (D-076a) | carried from the harvested lot |
| Normally | ₹45 | `NULL` — equals actual |
| After a harvest | ₹45 | ₹50 |
| **Used by** | tax engine · real P&L · cost of capital · broker reconciliation · charges | **deviation metric · sell trigger · GTT price · averaging decision** |

> 🔴 **Using the synthetic basis for tax would double-count the loss** — the ₹10 has already
> been booked at the harvest sale. Claiming it again at the proxy's disposal is wrong and
> illegal.
>
> 🔴 **Using the actual basis for the strategy manufactures the phantom profit above.**

`tax_gain` already carries no `universe_id` and computes on `unit_cost` under tax FIFO (D-167,
D-171). Nothing in the tax engine reads `synthetic_cost_basis`, and nothing in the strategy
engine reads `unit_cost` for a trigger. That separation is the whole design.

---

## 3. The carry-over is an **amount**, not a price

D-019 stated the principle with a worked figure (₹10,000 → ₹9,000 → target ₹10,350). The
general rule, which the ₹100 example hides because the numbers coincide, is that **the proxy
usually trades at a different price**, so the *quantity* differs. What survives the substitution
is the **rupee amount of original capital**, not the per-unit price.

```
carried_basis_amount  =  all-in actual cost of the harvested lot(s)
synthetic_unit_cost   =  carried_basis_amount  ÷  proxy_quantity_acquired
```

### Worked example — the general case

| Step | | |
|---|---|---|
| Buy A | 10 units × ₹100 | **₹1,000** committed |
| Price falls | A now ₹90 | |
| Harvest sale | 10 units × ₹90 | ₹900 proceeds · **₹100 loss booked** |
| Proxy B trades at | ₹45 | |
| Buy B | ₹900 ÷ ₹45 | **20 units** |
| B **actual** unit cost | ₹900 ÷ 20 | **₹45.00** → tax basis |
| B **synthetic** unit cost | **₹1,000 ÷ 20** | **₹50.00** → strategy basis |
| Sell target @ 3.5% | ₹50.00 × 1.035 | **₹51.75/unit = ₹1,035 total** |

₹1,035 is the original ₹1,000 plus 3.5%. ✅

Had the target been computed off ₹45: ₹46.575/unit = ₹931.50 total — **₹68.50 below the
original capital**, reported as a profit. That is the bug this rule exists to prevent.

---

## 4. Averaging — the new rule

> "What if a proxy is averaged at that time? It would be the average price of the security for
> which the harvest took place — so 100 at the average price, and not 90 at the average price."

Two situations, one formula.

### 4.1 The proxy is already held when the harvest happens

The harvest creates a **new lot** with its own synthetic basis. Pre-existing lots keep theirs
(synthetic = actual, no carry-over). The instrument's **strategy average** is the
quantity-weighted blend.

| Lot | Qty | Actual | Synthetic |
|---|---|---|---|
| Pre-existing B | 10 | ₹48 | ₹48 *(= actual)* |
| Harvest proxy B | 20 | ₹45 | **₹50** |

```
actual average    = (10×48 + 20×45) / 30  =  ₹46.00   → tax, real P&L, cost of capital
strategy average  = (10×48 + 20×50) / 30  =  ₹49.33   → deviation, sell trigger, GTT
```

Sell trigger at 3.5% = ₹49.33 × 1.035 = **₹51.06**, not ₹47.61.

### 4.2 The proxy is averaged down later with fresh capital

A new lot, no carry-over, synthetic = actual. It blends by the same formula, so the carry-over
is **diluted proportionally** — which is correct: the new money genuinely entered at the market
price and has no original capital to recover.

### 4.3 The formula, once

```sql
strategy_average = SUM(quantity_open * COALESCE(synthetic_cost_basis, unit_cost))
                 / SUM(quantity_open)

actual_average   = SUM(quantity_open * unit_cost)
                 / SUM(quantity_open)
```

`COALESCE(synthetic_cost_basis, unit_cost)` is the entire mechanism. The existing schema column
(`position_lot.synthetic_cost_basis`, nullable, D-019) already supports it — **no migration is
needed** for the core rule. Because it is per-lot and per-unit, partial sells, partial harvests
and repeated averaging all fall out correctly without special cases.

---

## 5. Everything downstream, and what it reads

| Component | Reads | Why |
|---|---|---|
| **Deviation metric** (`DEVIATION-METRIC-ANALYSIS.md`) | strategy average | The deviation is *from what we committed*, not from what we paid after a tax manoeuvre |
| **Sell logic** (`SELL-LOGIC.md`) | strategy average | Target = strategy avg × (1 + threshold%) |
| **GTT trigger price** | strategy average | It is the sell logic, expressed as a resting order |
| **Averaging / buy logic** | strategy average | See §7 Q-286 — this one is a genuine open question |
| **Tax engine** (`TAX-ENGINE.md`) | **actual** | The loss was booked once already |
| **Cost of capital** (`COST-OF-CAPITAL.md`) | **actual** | Interest accrues on real money — ₹900 is deployed, not ₹1,000 |
| **Real P&L / charges** | **actual** | What the investor's cash actually did |
| **Broker reconciliation** | **actual** | The broker only knows ₹45 |
| **ATOM-vs-broker contrast screen** (D-020) | **both** | That screen exists *because* the two diverge |

### The reporting triple

Q-207 already established that "profit" and "taxable gain" are reported as different numbers.
The synthetic basis makes it **three**, and all three must be visible on the position:

| Number | Basis | Reads as |
|---|---|---|
| **Strategy return** | vs synthetic | "Are we back above the capital we committed?" |
| **Cash return** | vs actual | "What did this position's money actually do?" |
| **Taxable gain** | vs actual, tax FIFO | "What does the tax engine see?" |

Showing only one of these would mislead. The position detail screen shows all three with the
basis named beside each figure — never a bare "P&L".

---

## 6. Rules the model implies

1. **Per-unit, so partials are free.** Selling half the proxy leaves the remainder's synthetic
   basis untouched. Harvesting only part of a source lot carries a proportional amount.
2. **The proxy must sit in the same universe as the harvested lot.** Lots belong to a universe
   (D-156), and carrying capital across universes would distort exactly the per-universe
   comparison universes exist to enable. Proposed as a hard constraint — see Q-287.
3. **A synthetic basis is never silently removed.** If a position becomes effectively unsellable
   because its synthetic target is unreachable, that is a decision for the operator, made
   explicitly and audited — never a quiet write-down (§7, Q-285).
4. **`harvest_chain` is the audit trail.** Every proxy lot links back to the lot it replaced,
   with the booked loss and the carried amount, so any synthetic basis can be explained years
   later.

### 6.1 🔴 Schema correction required

`atom.harvest_chain` was written before D-163 and is now inconsistent with it:

```sql
correlation  numeric(18,4) NOT NULL,   -- ❌ v1 computes no correlation (D-163)
proxy_tier   text NOT NULL,            -- ❌ v1 has no tiers (D-163)
```

D-163 made proxy selection **manual** — "no predefined proxy buckets, no correlation floor, no
automatic matching in v1" — so these two `NOT NULL` columns demand data v1 never produces. They
must become nullable (they stay in the schema for V2-14, which restores correlation matching),
and the table must gain the fields this document actually requires:

```sql
ALTER TABLE atom.harvest_chain
    ALTER COLUMN correlation DROP NOT NULL,
    ALTER COLUMN proxy_tier  DROP NOT NULL,
    ADD COLUMN carried_basis_amount numeric(18,4),  -- what was carried forward
    ADD COLUMN chain_depth          integer NOT NULL DEFAULT 1,
    ADD COLUMN selected_by          text;           -- operator, for the manual pairing (D-163)
```

`carried_basis_amount` is deliberately stored rather than recomputed: it is the number that
explains a synthetic basis, and recomputing it years later would depend on data that may have
been corrected in the meantime.

---

## 7. Open questions — these change the numbers

Raised under D-054c, because a new rule touches every connected component.

### Q-282 🔴 — Chained harvests: does the synthetic basis carry again?

B (synthetic ₹1,000, actual ₹900) falls further and is itself harvested into C.

| Option | C's carried amount | Effect |
|---|---|---|
| **A — carry the synthetic** | ₹1,000 | Target never decays; the original capital is always the benchmark |
| **B — carry the actual** | ₹810 (say) | Target resets at each harvest, reintroducing the phantom-profit bug one step removed |

**Recommendation: A.** The principle is "recover the capital originally committed", and B
quietly abandons it after the first hop. But A has a cost worth naming: after repeated harvests
the synthetic basis drifts ever further above cash and the position can become effectively
unsellable. Proposed mitigation — **store `chain_depth`, surface it in the UI, and warn above a
configurable depth (default 3)** rather than capping it silently.

### Q-283 — Leftover cash when proceeds don't divide evenly

₹900 proceeds, B at ₹45.30 → 19 units = ₹860.70, **₹39.30 left over**.

| Option | Synthetic unit cost | |
|---|---|---|
| **A — full amount on fewer units** | ₹1,000 ÷ 19 = ₹52.63 | Inflates the target by the leftover, which is *not* invested in B |
| **B — scale to what was deployed** | ₹1,000 × (860.70/900) ÷ 19 = ₹50.33 | The ₹39.30 returns to idle cash, where its share of the loss is already booked |

**Recommendation: B.** Option A asks the proxy to earn back money that is sitting in cash.

### Q-284 — Do harvest transaction charges join the carried amount?

A harvest costs real money: sell-side charges on A, buy-side charges on B. Should ATOM have to
earn those back too?

**Recommendation: yes — carry `original cost + sell charges`.** The buy charges are already
inside B's actual `unit_cost` (D-076a). Excluding the sell charges means the harvest silently
costs the investor and the strategy never sees it. Including them makes the true cost of
harvesting visible in the one place that will act on it. Counter-argument worth weighing: on a
thin gain threshold, adding charges to the target can make it unreachable — which is arguably
the correct signal that the harvest was not worth doing.

### Q-285 — Does a synthetic basis ever expire?

If the proxy never reaches its synthetic target, ATOM holds it indefinitely while cost of
capital accrues (already flagged in `COST-OF-CAPITAL.md`).

**Recommendation: no automatic expiry, ever.** Add an explicit, audited operator action —
*"release synthetic basis"* — that writes it down to actual with a mandatory reason, logged to
`action_audit`. This matches the standing posture on the block/review/release flow: *never
auto-un-release*. The 12-month holding warning already surfaces these positions for review.

### Q-286 🔴 — Does the **buy** side use the synthetic basis too?

B trades at ₹45 against a synthetic average of ₹50 — a −10% deviation, which is a **buy
signal**. ATOM would average down into the proxy it just bought.

| Option | |
|---|---|
| **A — yes, synthetic everywhere** | Consistent; one number drives both sides. But ATOM doubles down on a position it is already carrying at a premium, concentrating risk in the proxy |
| **B — synthetic for sell, actual for buy** | The buy decision uses the real market entry (₹45), so no artificial buy signal. But the position now has two different "averages" depending on direction, which is hard to explain on a screen |

**No recommendation — this is genuinely yours to call.** My weak lean is **A** for consistency
and explainability, with the per-instrument daily cap (one lot per instrument per day) already
limiting how fast concentration can build. But B is defensible and I do not want to assume it.

### Q-287 — Must the proxy be in the same universe?

**Recommendation: yes, enforced as a constraint.** Carrying basis across universes moves capital
between them and corrupts the per-universe P&L comparison. Confirm, and I will add a CHECK.

### Q-288 — Should the tax benefit reduce the carried amount?

The ₹100 booked loss produces a real tax benefit (~₹20 at 20% STCG), so arguably only ₹980 needs
recovering.

**Recommendation: no.** The benefit depends on year-end set-offs, exemption usage and slab —
making the sell trigger depend on it would be circular and unstable, and would change a resting
GTT's price every time the tax picture moved. Carry the gross amount; the benefit belongs in the
tax report, where it is visible, rather than smuggled into a trigger. Recording it as a
deliberate, conservative choice rather than an oversight.

---

## 8. Related

D-019 (synthetic basis, original) · D-020 (ATOM-vs-broker contrast screen) · D-021 (proxy funded
from buffer cash) · D-022 (deferred work queued to the execution list) · D-076a (`unit_cost` is
all-in) · D-156 (lots belong to a universe) · D-163 (manual proxy selection) · D-166 (one lot
per fill) · D-167/D-171 (tax FIFO is separate) · Q-207 (profit vs taxable gain reported
separately) · V2-14 (correlation-matched proxies, parked)
