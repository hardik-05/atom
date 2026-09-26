# Testing Strategy

**Status:** 🟢 Specified
**Date:** 2026-09-26

> ATOM moves real money once a day with no human in the loop after release. The tests that matter are
> the ones that catch a **wrong number**, not a crash — a crash is loud and stops the run; a wrong
> number gets executed.

---

## 1. Layers, and what each proves

The layering rule from [`../01-architecture/MODULE-MAP.md`](../01-architecture/MODULE-MAP.md) §1 is
what makes this cheap: nothing below needs the layer above to be tested.

| Layer | Needs | Proves |
|---|---|---|
| `domain/` | nothing | Arithmetic, rounding, deviation, tranche computation |
| `strategy/` | fake adapter | Gates, sizing, sell targets, harvest basis |
| `adapters/*` | recorded fixtures | Field mapping, normalisation, status and error maps |
| `orchestration/` | fake adapter + test DB | Phase order, abort semantics, idempotency |
| `reporting/` | test DB | P&L on three bases, charges, tax, accrual |
| `web/` | API stubs | Rendering, basis labels, offline behaviour |

**No test touches a real broker.** Not one. A test suite that needs credentials is a test suite that
does not run, and one that places orders is worse than no suite.

---

## 2. Domain tests — the arithmetic

The cheapest tests and the ones that catch the most damaging class of bug.

| Area | Must cover |
|---|---|
| Money | `Decimal` throughout; no `float` anywhere in a monetary path |
| Rounding | 4dp stored, 2dp displayed (D-026); sell targets round **up**, quantities round **down** |
| Deviation | `(ltp − mean) / mean`, 4dp, signed, and the `mean = 0` guard |
| Sizing | `floor(amount × buffer / ltp)` — including the 8.11 → 8 case, and `quantity = 0` (skip, not a zero-qty order) |
| Tick rounding | Against **ATOM's** tick (D-209); a broker's value never used |
| Tranches | Synthetic/actual split; multiple synthetic lots blending; **ceiling of two** |
| Carried basis | `carried_amount ÷ proxy_quantity` — including the ₹45-proxy case where per-unit ≠ source price |

### 2.1 Property tests where they earn their place

```
∀ lots:  Σ(tranche quantities)  ==  Σ(open lot quantities)        # nothing lost or duplicated
∀ lots:  count(tranches)  ≤  2                                    # the D-195 ceiling
∀ harvests:  Σ(carried basis × qty)  ==  Σ(actual cost of source lots)
∀ closures:  cash_pnl  ==  proceeds − Σ(qty × unit_cost)
```

The first two are worth property-testing rather than example-testing because the tranche logic has a
combinatorial input space — any number of lots, any mix of bases — and an example suite will miss the
case that matters.

---

## 3. Strategy tests

Against the **fake adapter**, so no network and no database.

| Gate | Test |
|---|---|
| Threshold | Deviation just above, just below, exactly at |
| Liquidity | Volume just above/below the configured window average |
| NAV premium | Passes at 1.9%, fails at 2.1% — and **global ETFs at +18.9% disable the category** |
| Freeze / exclusion | Excluded quantity subtracted; frozen instrument skipped with a reason |
| One-lot-per-day | Second signal on the same instrument, same day, is skipped |
| **Proxy block** | A proxy shows as a candidate, is **blocked**, and buys **only** after an override |
| Tradability | Groww `buy_allowed = 0` · Upstox suspended · Dhan `BUY_SELL_INDICATOR ≠ A` → dropped **before** placing |
| Funds | Insufficient funds **does not** drop the candidate — the order is placed and allowed to fail (D-052) |

The last row is a real distinction that a test must pin: **tradability is a pre-flight drop, funds are
a let-it-fail.** Getting them the wrong way round would either place orders that cannot succeed or
silently skip orders that would have.

### 3.1 Harvest — the three cases from the operator's own walkthrough

Each becomes a test, and all three must resolve through the **same code path**:

| Case | Expected synthetic basis |
|---|---|
| Single lot: A 10 @ ₹100 → proxy 10 @ ₹90 | **₹100** |
| Proxy then averaged at ₹85 | two tranches: ₹100 and ₹85 |
| **Averaged source**: X 10@₹100 + 10@₹90 → proxy 20 @ ₹86 | **₹95**, one tranche |
| Proxy at a different price: ₹1,000 → 20 units at ₹45 | **₹50**, not ₹100 |
| Chained harvest attempted | **Rejected** — DB CHECK `chain_depth = 1` |

The fourth row is the one that would slip through an example suite built from the operator's examples
alone, because in all three of those the prices coincide.

---

## 4. Adapter tests — fixtures, not mocks

```
tests/fixtures/{broker}/
├── instruments.json        vendor's documented sample
├── holdings.json
├── order_placed.json
├── order_rejected.json
├── gtt_list.json
└── errors/*.json
```

**Fixtures come from the vendor's own documentation, verbatim.** That has a property a hand-written
mock does not: refreshing them from the docs surfaces a vendor change as a **test failure**.

| Test | Every broker |
|---|---|
| Round trip | `OrderIntent` → wire payload → recorded response → `OrderState`, **asserted field by field against the vendor's table** |
| `free_quantity` | From that broker's real field set — 1 field on Dhan/Groww, 3 on Upstox, 4 on Zerodha, **7 on Shoonya** |
| **Unknown status** | 🔴 An **invented** status string must map to `IN_FLIGHT` (D-180) |
| Error map | Each documented code → the right canonical error |
| `GA007` | Groww duplicate reference maps to **success, already placed** — never an error |
| `stat` parsing | 🔴 Shoonya returns **HTTP 200 on rejection**; a 200 with `stat: Not_Ok` must not be read as placed |
| Decimal strings | Groww smart orders and all Shoonya fields serialise as strings |
| Tick size | A broker's `tick_size` is never used to price |
| No `MARKET` | No live path can emit it (D-174) |
| No `MTF` / `INTRADAY` | No outbound payload contains them (D-207) |

### 4.1 The two tests that would have caught real bugs

**The invented-status test** is mandatory because Zerodha states "there may be other values as well".
Mapping an unrecognised status to `REJECTED` would make ATOM re-place an order that is about to fill —
the one bug in this layer that loses money silently.

**The Shoonya `stat` test** is mandatory because HTTP 200 on rejection means a status-code branch
records rejected orders as placed. The failure surfaces a *day later* as a negative attribution
residual and a blocked run, with no obvious link back to the cause.

---

## 5. Orchestration tests

Fake adapter, real test database.

| Test | Asserts |
|---|---|
| Phase order | Nothing reaches a broker before phase 3 |
| Egress abort | Mismatch → run `FAILED`, **no orders**, no retry |
| Token abort | Invalid token → account halted |
| **Negative residual** | Run blocked **before** the sell pass |
| Cancel unverified | Run halts; no new GTT placed |
| Write-before-send | `order_request` exists with `INTENT` before the HTTP call (D-094) |
| Crash mid-placement | Re-running finds `INTENT` and **reconciles**, never double-places |
| Settlement idempotency | Running settle twice produces identical rows |
| `FAILED` does not consume the day | Same-day re-run permitted (partial unique index) |
| Config frozen | Changing config mid-run does not affect the run |
| Batch linearity | Runs in a batch never overlap |

The crash test is worth building properly — with a real abort between the write and the send — because
it validates the single most important durability property in the order path.

---

## 6. Reporting and tax tests

| Area | Must cover |
|---|---|
| Three bases | Strategy / cash / taxable computed independently; equal when no harvest exists |
| Two FIFOs | Universe FIFO ≠ tax FIFO on a cross-universe disposal |
| Charges | Every component; **GST on services only**, not on STT or stamp duty |
| DP charges | One per instrument per day, **not** per fill |
| Cost of capital | Three buckets summing to `principal_outstanding` (the CHECK constraint) · Actual/365 · idle excluded from universe level |
| Tax rates | Equity STCG 20% flat · commodity/global at slab · all LTCG 12.5% |
| Exemption | ₹1.25 L cap, **equity only**, per PAN per FY; cannot be exceeded |
| Loss pool | 8-year vintage expiry; set-off in legal order |
| Term boundary | 12-month boundary — a **warning**, not a block |
| Provenance | ATOM vs EXTERNAL; set-off uses ATOM's gains, display shows all (D-070c) |

### 6.1 The worked example becomes a golden test

The harvest-then-average-then-partial-sell example in
[`../08-reporting/UNIFIED-PNL.md`](../08-reporting/UNIFIED-PNL.md) §8 is a fixture, asserting all
three numbers simultaneously: cash +₹30, strategy +₹30, taxable net −₹70, remaining position needing
₹103.50.

A single golden case that pins all three at once is worth more than three separate assertions, because
the bug this class of code produces is not a wrong number — it is the **right number under the wrong
basis**.

---

## 7. Dry run as an integration test

Because dry and live share every line of strategy, gate, lot, tax and reporting code (D-045), **a dry
run is a real integration test** rather than a smoke test. So:

| | |
|---|---|
| Every release | A dry run per account before `LIVE` is restored |
| Every new account | At least one full dry run before promotion |
| Checked | `run_candidate` rows, gate verdicts, tranche targets, computed charges, lot creation |

This is the highest-value test in the system and it costs nothing, because it is a normal operation of
the software.

---

## 8. What is not tested, and why

| Not tested | Why |
|---|---|
| Live broker APIs | No credentials in CI; no test may place an order |
| Broker latency and availability | Not ours; handled by retry and backoff |
| AWS infrastructure | Verified by the deployment procedure, not by a test |
| The Telegram bot end-to-end | Manual; the surface is six commands |
| Visual regression | One operator, one browser; the cost exceeds the benefit |
| Load and concurrency | One run at a time, linear by design (D-057f) |

---

## 9. CI

```
on push:
  ruff · mypy --strict · import-linter (the §1 layering rule)
  pytest tests/unit tests/adapters          # no network, no DB
  pytest tests/integration                  # ephemeral Postgres
  secret scan
  frontend: tsc · vitest · build
on release:
  pip-audit · npm audit
```

### 9.1 Two CI checks specific to this system

**The import-linter check enforces the layering rule.** A documented convention decays; a failing
build does not. It is what keeps a broker name out of `strategy/`.

**The secret scan asserts that a planted token does not appear in shipped log output** — testing the
redaction *formatter* (D-069e), not just scanning the repository. Repository scanning would not have
caught the X1 exposure pattern, which was a credential in committed source; formatter testing catches
the other half, a credential in emitted logs.

---

## 10. Coverage targets

Targets by risk, not a single number.

| Area | Target |
|---|---|
| `domain/` | **100%** — it is pure arithmetic with no excuse |
| `strategy/` gates | **100% branch** — each gate has few branches and each is a money decision |
| `adapters/*/normalise.py` | **100%** — stage 3 is where brokers differ |
| `adapters/*/map.py` | Exercised by round-trip tests |
| `orchestration/` | 90% |
| `reporting/` | 95% |
| `web/` | 70% |

> **A single project-wide coverage number would hide the thing that matters.** 85% overall is
> compatible with an untested gate, and an untested gate is an untested money decision.
