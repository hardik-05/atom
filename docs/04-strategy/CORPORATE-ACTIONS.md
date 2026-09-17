# Corporate Actions

**Status:** 🟢 Specified
**Implements:** D-064 · supersedes D-058b (which declined corp-action handling)

---

## 1. The risk

ETFs do split. Nippon has split GOLDBEES, and several Indian ETFs have split specifically to
improve retail accessibility. A split is not a price move — but in unadjusted data it looks
exactly like one.

**A 1:2 split shows as a −50% single-day fall.** This strategy ranks candidates by how far
below their mean they trade, so an unadjusted split would be ranked as **the single most
attractive buy in its category**, and bought with conviction, on entirely fictional data.

---

## 2. The approach — detect and deactivate, don't adjust (D-064)

> "If you see a drastic move — say more than 30%, 40%, 50% — mark the security out of the
> universe. A corp action takes place on Wednesday; on Thursday you see a crazy price
> difference, and Thursday's and Friday's buying would be impacted. So just make those
> securities inactive. As part of the weekend run, we recompute based on the adjustments."

ATOM does **not** attempt to detect, source or apply corporate-action adjustments itself. It
detects the *symptom* — an implausible price move — and removes the instrument from play until
the weekly job can rebuild its history cleanly.

```
daily check, per ETF in the universe:

    move_pct = |close_today − close_yesterday| / close_yesterday × 100

    if move_pct > corp_action_threshold_pct:
            mark ETF INACTIVE
            exclude from ranking, from buying, from averaging
            log it, and report it
```

**Deactivation is immediate and blocks buying from that day**, covering exactly the Thursday
and Friday exposure described.

### Why detect rather than adjust

| Adjusting ourselves | Detecting and deactivating |
|---|---|
| Needs a corporate-action feed nobody currently has | Needs one subtraction |
| Needs the whole price history restated correctly | Needs a status flag |
| Silently wrong if the ratio or date is wrong | Fails safe — worst case a valid ETF sits out a few days |
| Double-adjusts if the broker already adjusted | Unaffected by whether the broker adjusted |

**The broker very likely adjusts history automatically.** If it does, nothing further is
needed — the weekly rebuild picks up clean data and the ETF reactivates on its own. If it does
not, the ETF simply stays inactive, and no bad trade is ever placed. **Both paths are safe,
which is the point.**

---

## 3. Reactivation — the weekly universe job

The Saturday universe job (D-058e) rebuilds from freshly fetched history. An ETF flagged
inactive is re-evaluated then:

| On rebuild | Outcome |
|---|---|
| History now consistent (broker adjusted) | **Reactivated**, re-enters the universe for the week |
| History still shows the discontinuity | **Stays inactive**, reported again |

Because the universe is frozen weekly (D-058e), an ETF deactivated on Thursday sits out the
rest of that week at most, then returns the following Monday if its data is clean. Worst case
is a couple of missed trading days in one instrument — a cheap insurance premium against
buying a phantom 50% discount.

---

## 4. Configuration

| Key | Scope | Suggested starting value | Notes |
|---|---|---|---|
| `corp_action_threshold_pct` | trading account × category | **20.0000** | No default is applied (D-038) — the operator sets it |

Set to 20% for now, adjustable at any time. Worth noting the trade-off in both directions:

- **Too low** (say 10%) → genuine crashes get deactivated, and a real crash is exactly the
  buying opportunity this strategy exists to capture.
- **Too high** (say 60%) → a 1:2 split (−50%) slips through and gets bought.

**20% sits comfortably between the two:** larger than almost any single-day ETF move in normal
markets, smaller than any split ratio in common use (1:2 = −50%, 1:5 = −80%, 1:10 = −90%).

> ⚠️ **The one genuine blind spot: small-ratio splits.** A 4:5 split is a −20% move and sits
> right on the threshold. Nothing in this design distinguishes it from an ordinary sharp fall.
> This is an accepted limitation of a symptom-based approach — the alternative is a corporate
> action data feed. Raised as Q-186.

---

## 5. Reporting

A deactivated ETF is never silent:

1. Logged in the run log with the observed move and the threshold breached (D-035).
2. Listed on the Daily Status screen with an `INACTIVE — possible corporate action` marker.
3. Included in the **rejected-ETF CSV** pushed to Telegram by the weekly job (D-058g).
4. Held in the ETF master with the deactivation date and reason, so the history is auditable.

---

## 6. Open items

| ID | Item |
|---|---|
| Q-186 | Small-ratio splits (e.g. 4:5 = −20%) are indistinguishable from a sharp fall. Accept, or add a corporate-action feed later? |
| Q-187 | Should an existing **holding** in a deactivated ETF still get its sell order placed? *(Recommendation: yes — the holding is real, and its average buy price comes from our own lot records, not from the suspect price series. Only buying is blocked.)* |
| Q-188 | Does the threshold check use adjusted or raw close, given D-058b declined adjustment? *(Recommendation: whatever the broker returns — that is the series the strategy consumes.)* |
