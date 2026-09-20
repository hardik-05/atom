# Bucket Management

**Status:** 🟢 Specified
**Implements:** D-107 · governs `etf-tradable-buckets-*.csv` and the ETF master

---

## 1. Principle

Automatic classification gets the shape right and the edges wrong — demonstrated, not asserted,
in [`SECTOR-BUCKETS.md`](./SECTOR-BUCKETS.md) §4. So the classifier **proposes** and the
operator **disposes**, and the operator's decision is never overwritten.

---

## 2. States

Every ETF carries an assignment status:

| Status | Meaning | Set by |
|---|---|---|
| **AUTO** | Placed by the classifier and accepted | Classifier + operator acceptance |
| **MANUAL** | Placed by the operator, overriding or absent any automatic result | Operator |
| **UNASSIGNED** | In no bucket — new, removed, or rejected | Classifier (new/unknown) or operator (removal) |

```
                  classifier run
   [ new ETF ] ──────────────────► [ PENDING REVIEW ] ──accept──► [ AUTO ]
                                          │                          │
                                       reject                    operator
                                          │                       removes
                                          ▼                          │
                                   [ UNASSIGNED ] ◄──────────────────┘
                                          │
                                   operator assigns
                                          │
                                          ▼
                                     [ MANUAL ]
```

**The unassigned pool is a real, visible place**, not an error state. An ETF sits there
safely: it is excluded from ranking, buying and harvest proxy matching until assigned.

---

## 3. The classifier run — on demand only

> "This process should be on demand. Most probably once in 6 months or a year this process will
> run and reviews will be made."

- **Never scheduled.** The operator triggers it from the Bucket Management screen.
- Expected cadence: every 6–12 months, or when a batch of new ETFs lists.
- It is **not** part of the weekly universe job, which only recomputes volumes and liquidity.

### What a run does

1. Re-reads the NSE export and re-runs `scripts/build_etf_buckets.py`.
2. **Leaves every `MANUAL` assignment untouched.** This is the hard rule (§5).
3. For everything else, computes a proposed bucket and produces a **change set**:
   - newly listed ETFs → proposed assignment
   - ETFs whose proposed bucket differs from their current `AUTO` bucket → proposed move
   - ETFs no longer present in the export → proposed retirement
4. Presents the change set for review. **Nothing is applied until reviewed.**

---

## 4. Review

The run ends with a confirmation dialog listing **every** change, each with accept/reject:

```
Classifier run — 2026-09-20 — 14 proposed changes

  NEW (6)
    ▸ GROWWAUTO    → SECTOR / AUTO / AUTO                 [accept] [reject]
    ▸ MOSILVER     → COMMODITY / SILVER                   [accept] [reject]
  MOVED (5)
    ▸ HEALTHCARE   INDEX/BROAD_500 → SECTOR/PHARMA        [accept] [reject]
  RETIRED (3)
    ▸ OLDETF       no longer listed → UNASSIGNED          [accept] [reject]

  [ accept all ]  [ reject all ]  [ apply 9 accepted ]
```

| Action | Result |
|---|---|
| **Accept** | Applied, status `AUTO` |
| **Reject** | Moves to **UNASSIGNED** — never silently left in its old bucket |
| **No decision** | Stays pending; the run is not complete until every item is decided |

**Rejection sends an ETF to the unassigned pool rather than reverting it.** A rejection means
"the classifier is wrong", which says nothing about the previous value being right.

---

## 5. 🔴 Manual assignments are never overwritten

**The single most important rule here.** An operator who corrects a bucket must not have that
correction silently undone by the next classifier run six months later — the run would look
successful while quietly reintroducing a harvesting bug.

- A `MANUAL` ETF is **skipped entirely** by the classifier.
- Where the classifier *would* have proposed something different, that is shown as an
  **informational note**, never as a change to accept: *"classifier suggests SECTOR/BANKING;
  manual assignment SECTOR/FINANCIAL_SERVICES retained."*
- Returning an ETF to automatic control is an explicit operator action: clear the manual
  assignment, which sends it to UNASSIGNED, and re-run.

---

## 6. Manual editing

From the Bucket Management screen, at any time and independent of a run:

| Action | Effect |
|---|---|
| **Add ETF to bucket** | Assigns bucket, tier-2 group and tier-1 index; status → `MANUAL` |
| **Remove ETF from bucket** | Status → `UNASSIGNED`; drops out of ranking and proxy matching immediately |
| **Move between buckets** | Status → `MANUAL` |
| **Create a tier-2 group** | For a new theme NSE has not covered (Q-199) |
| **Clear manual flag** | Status → `UNASSIGNED`, returning it to automatic control on the next run |

Every edit is audited: who, what changed, when, and the previous value (D-068).

### Effect on a live position

Removing an ETF to UNASSIGNED **does not affect existing holdings**. Sell orders continue from
our own lot records (the same principle as D-082). Only buying and proxy matching stop. An ETF
cannot be orphaned in a way that strands a position.

---

## 7. Screen

| Section | Contents |
|---|---|
| **Bucket tree** | INDEX / SECTOR / FACTOR / COMMODITY / GLOBAL → tier-2 groups → tier-1 indices → ETFs, with counts and liquid counts |
| **Unassigned pool** | Everything awaiting assignment, with the classifier's suggestion shown as a hint |
| **Search** | By symbol, ISIN or index |
| **Per ETF** | Bucket, tier-2, tier-1, status, assigned by, assigned at, volume, liquid, harvest peers |
| **Run classifier** | Triggers §3, opens the review dialog |
| **Export** | The current taxonomy as CSV, matching the committed file format |

Rows show status plainly: `AUTO` · **`MANUAL`** · `UNASSIGNED`.

---

## 8. Open items

| ID | Item |
|---|---|
| Q-204 | Should the classifier run be blocked while any previous run has undecided items? *(Rec: yes — two overlapping change sets would be confusing)* |
| Q-205 | Should an ETF in the unassigned pool still be shown on Daily Status as excluded, or hidden entirely? *(Rec: shown, greyed, so it is not forgotten)* |
