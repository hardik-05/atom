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

**Two checks, both must be satisfied to clear an ETF (D-090).**

```
daily, per ETF in the universe:

  # Check 1 — absolute move
  move_pct = |close_today − close_yesterday| / close_yesterday × 100

  # Check 2 — peer comparison
  peer_median = median(one-day move % of all ETFs in the same SUB-CATEGORY)
  divergence  = |move_pct − peer_median|

  if move_pct > corp_action_threshold_pct:            → BLOCKED (absolute)
  elif divergence > peer_divergence_threshold_pct:    → BLOCKED (peer divergence)
  else:                                               → clear
```

### Why the peer check earns its place

A corporate action moves **one ETF**. A market fall moves **the whole sub-category**. Every
peer price is already held, so this costs one median per group:

| Scenario | Absolute move | Peer median | Verdict |
|---|---|---|---|
| GOLDBEES −20%, other gold ETFs flat | −20% | ~0% | **Corporate action** — blocked |
| GOLDBEES −20%, gold ETFs −18% | −20% | −18% | **Real market move** — 2% divergence, cleared |
| An ETF −12% (4:5-ish split), peers flat | −12% | ~0% | **Caught** — the absolute check alone would have missed this |

It fixes the blind spot **in both directions**. It catches small-ratio splits that slip under
the absolute threshold, *and* it stops a genuine sector-wide crash from deactivating an entire
category — which is the more common everyday risk, and precisely when the strategy most wants
to be buying.

**Peer group is the NSE `SUB-CATEGORY`**, not the broad bucket: GOLD against GOLD, `Nifty Bank`
against `Nifty Bank`. Comparing a bank ETF against all of EQUITY would be meaningless.

> ⚠️ **Sub-categories are often tiny.** The 17-Sep data shows many with a single member
> (`Nifty Pharma`, `BSE Power`, `Nifty CPSE` …) and `GLOBAL INDICES` has six. With one member
> there are no peers and the check cannot run.
> **Rule:** the peer check requires a **minimum peer count** (proposed: 3). Below it, the check
> is skipped, only the absolute threshold applies, and the log records that peers were
> unavailable. (Q-194)

| Config key | Scope | Suggested | Meaning |
|---|---|---|---|
| `corp_action_threshold_pct` | account × category | 20.0000 | Absolute one-day move |
| `peer_divergence_threshold_pct` | account × category | 10.0000 | Divergence from sub-category median |
| `peer_min_count` | global | 3 | Below this, skip the peer check |

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

## 3. Three-stage lifecycle: BLOCKED → REVIEW → RELEASED (D-091)

> "The weekly job should move them from blocked to review, and post review by the user we can
> release. Instead of block-to-release, we make it a three-stage process."

```
                    detection                weekly job              operator
   [ ACTIVE ] ──────────────────► [ BLOCKED ] ──────────► [ REVIEW ] ──────────► [ ACTIVE ]
                                        │                      │
                                        └──── stays blocked ◄──┘
                                          (history still inconsistent)
```

| Stage | Set by | Meaning | Buying | Selling |
|---|---|---|---|---|
| **BLOCKED** | The engine, automatically on detection | Suspect price discontinuity | ❌ | ✅ (D-082) |
| **REVIEW** | **The weekly universe job**, when refreshed history looks consistent again | Candidate for release — a machine opinion, not a decision | ❌ | ✅ |
| **ACTIVE** | **The operator only** | Cleared and trading normally | ✅ | ✅ |

**This separates the machine's opinion from the operator's decision**, which is what makes
D-084 workable in practice. The weekly job does useful work — it re-fetches history and judges
whether the discontinuity has resolved — but it can only move an ETF *towards* release, never
complete it. **No automatic transition ever reaches ACTIVE.**

An ETF sitting in REVIEW is still fully blocked from buying. Nothing changes behaviourally
until the operator acts; REVIEW is a queue, not a permission.

The ETF master screen shows a **Review queue** with, per ETF: the original move that triggered
the block, the date, the refreshed history, and whether the discontinuity now appears resolved.
Release is one explicit action per ETF.

*Trade-off accepted: an ETF stays out of the universe until someone works the review queue.
That is the deliberate cost of never letting an automatic process put a suspect instrument back
in front of the buy logic.*

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
| ~~Q-186~~ | ✅ Resolved by D-090 — the peer-comparison check catches small-ratio splits |
| Q-194 | Confirm `peer_min_count = 3`, and that below it only the absolute check applies |
| Q-195 | Does the three-stage lifecycle apply only to corporate-action blocks, or also to freezes and exclusions? *(Rec: corp-action only — a freeze is a deliberate operator choice needing no review queue)* |
| ~~Q-187~~ | ✅ D-082 — yes, sells continue; only buying is blocked |
| ~~Q-188~~ | ✅ D-083 — whatever close the broker returns |
