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

## 3a. The three cases, worked end to end

Restated from the operator's own walkthrough (2026-09-26), because the rule reads differently
depending on which case you hold in mind. **All three are the same formula** — §3's amount-based
carry-over — but that is only obvious once they are side by side.

### Case 1 — single lot, proxy at the same price

| Step | |
|---|---|
| Buy A | 10 @ ₹100 = **₹1,000** |
| A falls to ₹90 | |
| Sell A, buy proxy at ₹90 | ₹900 → 10 units. *"Our investment stays the same."* |
| Proxy synthetic basis | ₹1,000 ÷ 10 = **₹100** |
| Sell target @ 3.5% | **₹103.50** |

> "Whenever harvesting happens, the sell price of the proxy will be as of buying price of the
> initial security."

### Case 2 — the proxy is then averaged

The averaging buy is *"altogether a different trade itself"* and gets its own order.

| Tranche | Qty | Basis | Target @ 3.5% |
|---|---|---|---|
| **S** — from the harvest | 10 | ₹100 | **₹103.50** |
| **A** — averaged at ₹85 | 10 | ₹85 | **₹87.98** |

Two orders. Covered in §4.

### Case 3 — harvesting a security that was *itself* already averaged 🆕

This is the case the operator raised last, and it is the one that shows why the carry-over must be
an **amount**.

| Step | |
|---|---|
| Buy X | 10 @ ₹100 = ₹1,000 |
| Average X | 10 @ ₹90 = ₹900 |
| **X's average buy price** | ₹1,900 ÷ 20 = **₹95** |
| X falls ~10% from ₹95 | → ~₹86 |
| Harvest: sell 20 @ ₹86 | ₹1,720 · loss **₹180** booked |
| Buy proxy at ₹86 | 20 units |
| Proxy synthetic basis | ₹1,900 ÷ 20 = **₹95** |
| Sell target @ 3.5% | **₹98.33** |

> "You take the average price which is 95 rupees… the selling price of the proxy security bought
> at 85, 86 — that will be 95 plus the percentage. So that's how even an average security can be
> used for harvesting."

**The harvest collapses the source position's lots into one carried basis.** X had two lots at
₹100 and ₹90; the proxy gets **one** synthetic tranche at ₹95, not two tranches at ₹100 and ₹90.
This is D-205, and it follows automatically from §3: sum the actual cost of **all** harvested lots,
divide by the proxy quantity acquired.

**So the three cases need no special-casing.** §3's formula produces ₹100, ₹100 and ₹95
respectively without branching. That is the test of whether the rule was stated at the right level.

### 3a.1 🔴 One place where "sell at ₹100" and the arithmetic diverge

Every example above has the proxy trading at **the same price** as the harvested security's sale
price, so proxy quantity equals source quantity and "the sell price of the proxy is the buying
price of the initial security" is literally true per unit.

**When the proxy trades at a different price it stops being true per unit**, and taking it
literally overstates the target badly:

| | |
|---|---|
| A | 10 @ ₹100 = ₹1,000 |
| Sell at ₹90 | ₹900 proceeds |
| Proxy trades at **₹45** | ₹900 → **20 units** |
| ❌ Literal reading: ₹100/unit | 20 × ₹100 = **₹2,000** — double the capital committed |
| ✅ Amount-based: ₹1,000 ÷ 20 | **₹50/unit** → 20 × ₹51.75 = ₹1,035 = ₹1,000 + 3.5% |

The invariant the operator actually wants is *"recover the capital originally committed, plus the
percentage"* — which is a **rupee amount**, and only coincides with a per-unit price when the two
securities trade at similar prices. ATOM therefore stores and carries the **amount**
(`harvest_chain.carried_basis_amount`) and derives the per-unit synthetic basis from it.

> **Q-311 — confirm.** For a proxy at a materially different price from the harvested security,
> the target is `carried_amount ÷ proxy_quantity × (1 + pct)`, **not** the harvested security's
> per-unit price. In practice most proxies inside one ETF universe trade in a similar range so the
> two rarely diverge much — but a ₹45 proxy against a ₹100 source would double the target, so this
> needs to be right rather than approximately right.

---

## 4. Averaging a proxy — tranches, not a blend

> "What if a proxy is averaged at that time? It would be the average price of the security for
> which the harvest took place — so 100 at the average price, and not 90 at the average price."
>
> "Post override, the synthetic price should be considered for your sell order for the amount
> which was bought as part of synthetic, and there should be a **separate order** for the one
> which was bought as per average… This case only occurs when you average a proxy, not in the
> others. In other cases you will combine the average buy price and then put in a sell order."

### 4.1 ⚠️ This supersedes the first version of D-189

The first draft of this document said the two bases blend into a single weighted
`strategy_average` and one sell order is placed against it. **That is wrong for a proxy that has
been averaged**, and the operator's rule is better: blending would silently destroy the
carry-over it exists to protect.

Worked through with the operator's own numbers:

| | Qty | Actual | Synthetic |
|---|---|---|---|
| Proxy lot (A @ ₹100 harvested at ₹90) | 1 | ₹90 | **₹100** |
| Averaged lot (bought later at ₹85) | 1 | ₹85 | ₹85 |

**Blended** (the wrong answer): strategy average = (100 + 85) / 2 = **₹92.50**. One sell order at
3.5% → ₹95.74 for both units. The proxy unit exits at ₹95.74 against ₹100 of committed
capital — **a ₹4.26 loss booked as a 3.5% gain.** Averaging would have re-introduced the exact
phantom-profit bug the synthetic basis exists to prevent, one step removed.

**Tranched** (the rule): two sell orders.

| Tranche | Qty | Basis | Target @ 3.5% |
|---|---|---|---|
| **Synthetic** | 1 | ₹100 | **₹103.50** |
| **Actual** | 1 | ₹85 | **₹87.98** |

Each tranche recovers the capital actually committed to it. Nothing is cross-subsidised.

### 4.2 The rule

> **Lots carrying a synthetic basis form their own sell tranche. Lots without one blend
> normally. At most two sell orders per (account, universe, instrument).**

```sql
-- Tranche S — synthetic lots
qty_s    = SUM(quantity_open) WHERE synthetic_cost_basis IS NOT NULL
target_s = SUM(quantity_open * synthetic_cost_basis) / qty_s  ×  (1 + threshold)

-- Tranche A — everything else
qty_a    = SUM(quantity_open) WHERE synthetic_cost_basis IS NULL
target_a = SUM(quantity_open * unit_cost) / qty_a             ×  (1 + threshold)
```

Two GTTs go out, not one. D-156 already requires multiple GTTs per instrument and D-164 confirmed
every broker supports it, so no new capability is needed — but the **sell pass must now emit a
list of tranches per instrument rather than a single order**, which is a change to its shape.

**Where the ordinary case still blends.** An instrument with no synthetic lots has exactly one
tranche, computed on `unit_cost` — identical to today's behaviour. The operator's "in other cases
you will combine the average buy price and then put in a sell order" is simply tranche A with
tranche S empty. Nothing about the normal path changes.

### 4.3 Multiple synthetic lots blend *with each other*

**First, within one harvest.** If the harvested security had several lots (§3a case 3), they
collapse into **one** carried basis — the weighted average of their actual costs — and produce
**one** synthetic tranche. A source position with five lots does not create five tranches.

**Second, across harvests.** Chaining is banned (§4.4), but two different securities may be
harvested into the **same** proxy instrument at different times — A → B in March, C → B in July.
B then holds two synthetic lots with different bases.

**These blend into one synthetic tranche**, weighted by `synthetic_cost_basis`. The alternative —
one sell order per harvest — would grow the order count without bound and make the GTT book
unreadable. Blending *within* tranche S is safe because every lot in it is recovering committed
capital on the same principle; blending *across* S and A is what breaks (§4.1).

So the ceiling stays at **two sell orders per instrument, always**.

### 4.4 🔴 Chained harvests are not allowed

> "Chained harvest is not allowed in this system because that will complicate it to a very deep
> extent. So if you buy a proxy for one of the instruments, you should not be able to sell that
> proxy and put in a third proxy. That dilutes the whole process."

**A lot carrying a synthetic basis can never itself be harvested.** This closes Q-282 by removing
the question rather than answering it: `chain_depth` is always 1.

The column stays in `harvest_chain` as a **guard, not a variable** —
`CHECK (chain_depth = 1)` — so a violation is impossible at the database level rather than merely
discouraged in code. That is worth more than the flexibility it gives up: the alternative was an
ever-widening gap between synthetic basis and cash, with positions drifting toward unsellable.

Enforcement: the harvest candidate list **excludes any lot with a non-null
`synthetic_cost_basis`**, and the reason is shown rather than the lot silently omitted — *"already
a harvest proxy; cannot be re-harvested"*.

### 4.5 Averaging a proxy is blocked by default, with an override

> "Those securities in the averaging page, if they come, they should [say] **not harvesting
> because proxy applied**… but if at all the user still wants to buy them, there should be an
> override where they click on average, an override screen comes up, they override and then do."

Because the buy side uses the synthetic basis (§5.1), a proxy bought at ₹90 with a ₹100 synthetic
basis shows a **−10% deviation** and therefore appears as a buy candidate immediately. Left alone,
ATOM would average into the proxy it just bought, concentrating the position — which is the
concentration risk the operator wants avoided.

So the proxy **appears on the averaging screen, flagged and blocked**:

```
GOLDBEES   LTP 90.00   synthetic 100.00   actual 90.00   dev −10.00%
           ⚠ PROXY APPLIED — averaging blocked.  [ Override ]
```

Clicking **Override** opens a confirmation screen stating what will happen — a second sell
tranche will be created — and requires explicit confirmation, logged to `action_audit` with the
operator and the reason. This follows the standing three-stage posture (block → review →
release): the block is the default, the override is deliberate and audited, and it is never
implicit.

**The concentration control is the override gate, not the price choice.** Using the synthetic
basis makes the proxy *more* visible as a candidate, not less; what prevents the concentration is
that ATOM refuses to act on it without a human saying so.

### 4.6 The averaging screen shows both prices

> "Out of a big universe not everything would be having a synthetic price. So we would like to
> see a synthetic price and an original price in the average screen, so that it helps the user
> take the decision more easily."

Two columns, always present, on every row:

| Column | Value | For a normal holding |
|---|---|---|
| **Actual avg** | `SUM(qty × unit_cost) / SUM(qty)` | the only number that exists |
| **Synthetic avg** | `SUM(qty × COALESCE(synthetic, unit_cost)) / SUM(qty)` | **identical to actual** |
| **Deviation** | computed against **synthetic** | identical either way |

For most of the universe the two columns match, and that sameness is the point: it tells the
operator at a glance which rows carry a harvest history and which do not. A row where they differ
is a proxy, and it will also carry the blocked flag from §4.5.

> **Open — Q-294.** The deviation shown and used for the averaging *decision* is computed on the
> **synthetic** average; the actual average is displayed for context only. That is my reading of
> "use the synthetic price," and it is what produces the −10% that triggers the block. Confirming
> it explicitly because the alternative (decide on actual, display synthetic) would mean the proxy
> never appears as a candidate at all and the block never fires.

## 5. Everything downstream, and what it reads

### 5.1 ✅ The buy side uses the synthetic basis (Q-286 answered)

The operator's answer is **yes**. The deviation that drives averaging is computed against the
synthetic average, not the market entry price.

The reasoning is worth recording because the mechanism is counter-intuitive: using the synthetic
basis makes a proxy look **more** attractive to average into, not less (₹90 against a ₹100 basis
is −10%, where ₹90 against a ₹90 basis is 0%). Concentration is then prevented not by hiding the
candidate but by **blocking it and demanding an override** (§4.5). The proxy is surfaced
*because* it is cheap relative to committed capital, and refused *because* it is already a proxy.
Both facts are true and the operator sees both.


| Component | Reads | Why |
|---|---|---|
| **Deviation metric** (`DEVIATION-METRIC-ANALYSIS.md`) | strategy average | The deviation is *from what we committed*, not from what we paid after a tax manoeuvre |
| **Sell logic** (`SELL-LOGIC.md`) | **per tranche** (§4.2) | Synthetic lots and actual lots get **separate targets and separate orders** |
| **GTT trigger price** | **per tranche** | Two GTTs where a synthetic tranche exists, one otherwise |
| **Averaging / buy logic** | synthetic average | ✅ **Q-286 answered** — see §5.1 |
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

1. **Per-unit, so partials are free.** Selling half a tranche leaves the remainder's synthetic
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
    ADD COLUMN selected_by          text,           -- operator, for the manual pairing (D-163)
    ADD CONSTRAINT harvest_no_chaining_ck CHECK (chain_depth = 1);   -- D-193
```

The `CHECK (chain_depth = 1)` is the enforcement of the no-chaining rule (§4.4). A proxy lot can
never itself be harvested, so the database refuses to record a second hop rather than trusting
application code to remember.

`carried_basis_amount` is deliberately stored rather than recomputed: it is the number that
explains a synthetic basis, and recomputing it years later would depend on data that may have
been corrected in the meantime.

---

## 7. Open questions — these change the numbers

Raised under D-054c, because a new rule touches every connected component.

### ✅ Q-282 — Chained harvests: **closed, not allowed** (D-193)

The question is removed rather than answered: a lot carrying a synthetic basis can never itself
be harvested. `chain_depth` is always 1 and the database enforces it (§6.1). The harvest
candidate list excludes proxy lots with a visible reason.

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

### ✅ Q-286 — The buy side uses the synthetic basis (D-194)

Answered yes. Concentration is controlled by the **override gate** (§4.5), not by the choice of
price — the proxy is surfaced because it is cheap against committed capital, and blocked because
it is already a proxy.

### Q-294 — Which number drives the averaging *decision*?

My reading: the **synthetic** average drives the deviation and therefore the candidate list; the
actual average is shown alongside for context. Confirming because the alternative (decide on
actual, display synthetic) would mean the proxy never becomes a candidate and the §4.5 block
never fires.

### Q-295 — Does the override persist, or is it per-run?

Once the operator overrides and averages a proxy, does that instrument stay unblocked for future
runs, or does each additional average need a fresh override? **Recommendation: per-run.** An
override is consent to one specific action at one specific price, and a standing exemption would
quietly rebuild the concentration risk the block exists to prevent — consistent with the standing
"never auto-un-release" posture.

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
