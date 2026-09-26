# Run Lifecycle

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Scope:** everything that happens between "execute" and a `COMPLETED` run

> A **run** is one `(trading_account, universe, trade_date)` execution. It is the unit of
> atomicity, the unit of logging, and the unit of P&L. One run per universe per account per day
> (D-172), enforced by a partial unique index.

---

## 1. Trigger and batching

| Trigger | Creates |
|---|---|
| Operator picks one universe | `run_batch` of **one** run |
| Operator picks "execute all" | `run_batch` of **one run per selected universe** |
| Scheduled (future) | same shape |

Runs inside a batch execute **linearly, never in parallel** (D-057f). The reason is not
performance: two runs touching the same account's cash would race on the funds check, and two runs
touching the same instrument would race on the one-lot-per-day cap.

`run.status` is `QUEUED → EXECUTING → COMPLETED | FAILED`. The console shows all four per run and
rolls them up per batch.

### Config is frozen at run start

`run.config_snapshot` is the **fully resolved** configuration as jsonb (D-061). Nothing re-reads
live config mid-run. A threshold changed while a run is executing affects the *next* run, never
this one — which is what makes a run reproducible from its own row a year later.

`run.execution_mode` is likewise copied from the account and frozen. A run that started in `DRY`
finishes in `DRY`.

---

## 2. The seven phases

```
 0  PRE-FLIGHT     ─── any failure here aborts before anything is touched
 1  REFERENCE      ─── instruments · prices · NAV
 2  RECONCILE      ─── broker holdings vs ATOM's lots
 3  SELL PASS      ─── cancel-all → verify → place tranche GTTs
 4  BUY PASS       ─── deviation → gates → orders
 5  HARVEST        ─── only if the operator queued one
 6  SETTLE         ─── fills · lots · charges · accrual · logs
```

Phases 0–2 are read-only. **Nothing is sent to a broker until phase 3.**

---

## 3. Phase 0 — Pre-flight

Four independent gates. Each either passes or **aborts the run for that account** with a specific
reason. None is a warning.

### 3.1 Egress IP — a separate gate from everything else

```python
actual = verify_egress_ip(account)          # through the account's proxy
if actual != account.egress_ip:  ABORT("EGRESS_IP_MISMATCH")
if egress_ip_is_shared(actual):  ABORT("EGRESS_IP_SHARED")
```

> 🔴 **This cannot be folded into the token probe.** On Dhan, IP whitelisting gates **order
> placement only** — reads work from any address (D-173). A token probes green from the wrong IP
> and the first order then fails. And Dhan publishes no IP-specific error code (Q-305), so the
> rejection is not self-explanatory either. A standalone pre-flight check is the only reliable
> detection.

On Shoonya the opposite is true — a wrong IP fails at login, loudly. Which is safer, but ATOM
cannot rely on the broker being the one that tells it.

**A mismatch is an infrastructure fault, never retried.** On Dhan a changed IP cannot even be
re-registered for 7 days, so this is potentially a week-long outage and must alert immediately, not
degrade quietly.

### 3.2 Token validity — tested, never computed (D-170, D-178)

```python
probe = adapter.probe_token(account)        # PROFILE where available, else HOLDINGS
if not probe.ok:  mark session INVALID; ABORT("TOKEN_INVALID")
```

Preference order per broker:

| Broker | Probe | Why |
|---|---|---|
| Dhan | `GET /v2/profile` | Returns `tokenValidity`, `ddpi`, `dataPlan` — says *why* it is unusable |
| Zerodha | `GET /user/profile` | Also yields `meta.demat_consent` for §5.2 |
| Upstox | `GET /v2/user/profile` | |
| Groww | `GET /v1/margins/detail/user` | Doubles as the funds read |
| Shoonya | `POST /Holdings` | No profile endpoint exists |

No expiry arithmetic anywhere. A documented lifetime that changed is exactly the failure this
avoids.

### 3.3 Market calendar and clock

Trading holiday, or outside the run window → abort. The window sits **after 06:00 IST**, because
Zerodha and Groww tokens expire at 06:00 and a token generated before it is dead before the market
opens (D-184).

### 3.4 Sell authorisation (D-183a)

Read from the capability profile, not hardcoded:

| `sell_authorisation_scope` | Behaviour |
|---|---|
| `NONE` | proceed |
| `ONE_TIME` (Upstox EDIS) | check the onboarding flag; abort with the authorisation link if unset |
| `PER_SESSION` (Zerodha CDSL) | if DDPI is inactive, **authorise the whole holding up front** — never discover a 428 mid-pass |

Zerodha's pre-emptive authorisation call uses no isin/quantity pairs, which presents the entire
holding — the same thing Kite's own UI does "to avoid having to disrupt the sell transactions with
the authorisation flow every time".

---

## 4. Phase 1 — Reference data

| Step | Source | Note |
|---|---|---|
| Instrument sync | each broker's master | Daily, ~08:30 IST. Public and token-free on Groww, Upstox, Dhan |
| Resolve to `instrument_id` | **ISIN** | Never symbol, except Zerodha's curated seed (D-187) |
| Tradability | broker flags | Groww `buy_allowed` · Upstox suspended file · Dhan `BUY_SELL_INDICATOR` |
| Prices | **one provider for all accounts** (D-044) | Zerodha, Dhan and Shoonya all cap quotes at ~1/sec |
| NAV | AMFI / AMC | For the NAV-premium gate |
| `tick_size` | **ATOM's own reference data** (D-209) | Broker fields cross-checked, never used for pricing |

A broker token that changed for an existing ISIN **updates the row and logs it**. A silent change
would route the next order to a different security.

---

## 5. Phase 2 — Reconciliation

Two separate checks with two different jobs (D-182).

### 5.1 Ownership

```
total_quantity  =  Σ open ATOM lots  +  excluded_quantity  +  unattributed_quantity
```

| Residual | Meaning | Action |
|---|---|---|
| `= 0` | books agree | proceed |
| `> 0` | stock appeared — manual buy, bonus, transfer in | **warn**, never auto-attribute (D-086) |
| `< 0` | stock disappeared | 🔴 **ABORT this account's run** |

A negative residual means ATOM believes it holds what it does not, and would place sells the
broker rejects. It blocks before the sell pass, not after.

### 5.2 Sellability

`free_quantity` per instrument, derived per broker — direct on Dhan (`availableQty`) and Groww
(`demat_free_quantity`), derived from four fields on Zerodha, three on Upstox, and **seven** on
Shoonya (whose docs publish the formula).

Where a broker does not publish it, `free_quantity` is `None`, ATOM falls back to the total **and
logs that it is doing so** — that is the case where a foreseeable rejection becomes possible again.

---

## 6. Phase 3 — Sell pass

```
1  CANCEL      every ATOM-recorded GTT for this (account, universe)
2  VERIFY      re-read the book; any survivor → HALT
3  TRANCHE     compute sell tranches per instrument
4  PLACE       one GTT per tranche
```

### 6.1 Cancel and verify (D-063, D-064)

Only **ATOM-recorded** broker IDs are cancelled. A resting sell ATOM has no record of is
**reported, not cancelled** — it is either the operator's own or a reconciliation gap.

On Zerodha this is load-bearing in a way it is not elsewhere: an active GTT carries **no ATOM
identifier at all** until it fires (D-176), so ATOM's own `trigger_id` table is the only link. If
that mapping is lost there is no recovery from the broker side.

**Verification is mandatory, and on Dhan it must re-poll**: `DELETE` returns *202 Accepted*, not
*cancelled* (Q-185 answered for Dhan). Proceeding on a 202 could leave two live sells for one
holding — the failure D-055 forbids.

### 6.2 Tranches, not one order (D-195, D-198)

```
Tranche S   lots WHERE synthetic_cost_basis IS NOT NULL
            target = Σ(qty × synthetic) / Σqty × (1 + pct)
Tranche A   lots WHERE synthetic_cost_basis IS NULL
            target = Σ(qty × unit_cost) / Σqty × (1 + pct)
```

**At most two per instrument**, and for the overwhelming majority exactly one. An instrument with
no harvest history yields a single `ACTUAL` tranche — today's behaviour unchanged.

The cancel step in §6.1 must therefore expect **up to two** ATOM sells per instrument and not treat
the second as a duplicate.

Target price is rounded **up** to ATOM's own tick size — up, because rounding a sell target down
would exit below the threshold.

### 6.3 Where GTT is unavailable

`supports_gtt = False` (Shoonya today, Q-271) → a plain **DAY limit sell** each morning at the
tranche target, which the broker cancels each evening (D-129, D-164).

⚠️ The cost is explicit: **positions are unprotected on non-run days**, which is the gap GTT was
reinstated to close. An overnight `CANCELLED` on a DAY sell is therefore **expected**, not an
anomaly.

---

## 7. Phase 4 — Buy pass

```
for each instrument in the universe snapshot:
    deviation = (ltp − mean) / mean                    ← mean on the SYNTHETIC basis
    gates: liquidity → NAV premium → freeze/exclusion → one-lot-per-day
           → proxy-block → tradability → funds
    quantity = floor(trade_amount × budget_buffer_pct / ltp)
    place LIMIT BUY
```

Every candidate writes a `run_candidate` row **whether it was bought or not**, carrying every
gate's input and verdict plus `decision` and `decision_reason` (D-035). The decision is
reconstructible from SQL alone, with no log parsing.

### 7.1 Quantity (D-059b, confirmed 2026-09-26)

```
quantity = floor( (trade_amount × budget_buffer_pct) / ltp )
```

Default buffer **99%**, configurable. It exists because a naive `amount / price` goes over budget
once brokerage is added — ₹1,000 at ₹100/unit is 10 units costing ₹1,010–1,020, and is rejected.
`floor` is explicit: ₹20,000 × 0.99 ÷ ₹2,440 = 8.11 → **8 units**. No fractional shares exist in
Indian equity markets; the remainder stays as cash.

### 7.2 The proxy block (D-196)

A harvest proxy shows a negative deviation against its synthetic basis and therefore **appears as
a buy candidate**. It is surfaced, flagged `PROXY APPLIED — averaging blocked`, and **not bought**
without an explicit operator override logged to `action_audit`.

Concentration is controlled by the gate, not by hiding the row.

### 7.3 Funds

Read from the broker (`clear_cash` on Groww, `available.live_balance` on Zerodha, and so on). If
the money is not there, **the order is allowed to fail** and the broker's verbatim reason is
recorded (D-052). Funds genuinely cannot be known reliably ahead of the exchange.

Tradability is the opposite case — it *can* be known in advance, so a candidate the broker marks
untradable is dropped **before** placing (Groww, Upstox, Dhan).

---

## 8. Phase 5 — Harvest

Runs only when the operator has queued a harvest. Proxies are chosen **manually** (D-163); there
is no correlation matching in v1.

```
1  operator pairs a loss-making position with a proxy from the same universe
2  block if the source lot already carries a synthetic basis  ← no chaining (D-193)
3  sell the source; book the loss
4  buy the proxy, funded from buffer cash, not sale proceeds (D-021)
5  carried_basis_amount = Σ actual cost of ALL harvested lots
6  synthetic_cost_basis = carried_basis_amount ÷ proxy_quantity_acquired
7  write harvest_chain: sold_lot → proxy_lot, booked_loss, carried amount, chain_depth = 1
```

Step 5 collapses a multi-lot source into **one** carried basis (D-205): a position of 10 @ ₹100 and
10 @ ₹90 carries ₹1,900, producing a ₹95 synthetic basis on the proxy — one tranche, not two.

A harvest that cannot execute immediately is written to the **execution list** and drained by a
later run (D-022). It is never shown as "executable tomorrow".

---

## 9. Phase 6 — Settle

| Step | Writes |
|---|---|
| Poll order states | `order_request.status`, `reject_reason` |
| Ingest fills | `order_fill` — **one row per fill** |
| Create lots | `position_lot` — **one per fill** (D-166) |
| Close lots | `lot_closure` under universe FIFO; `tax_gain` under tax FIFO |
| Charges | `charge` rows, `source = 'COMPUTED'` always; `'BROKER'` where available |
| Cost of capital | `capital_accrual_daily` + `capital_accrual_universe_daily` |
| Destroy tokens | `broker_session → CLEARED`; `DELETE /session/token` on Zerodha |
| Ship logs | local → S3 → Drive |

### 9.1 Charges reality per broker

| Broker | Per-order | Components |
|---|---|---|
| Dhan | ✅ | ✅ |
| Zerodha | ✅ (and prices imaginary orders) | ✅ |
| Upstox | ❌ period total | ✅ incl. DP |
| Groww | ✅ | ❌ aggregate |
| Shoonya | ❌ | ❌ |

Where a broker cannot supply a figure, the UI shows **computed only and says so**. An empty broker
column that reads as zero would be worse than an honest gap.

### 9.2 Idempotent settlement

Settlement re-runs safely. Fills key on `broker_trade_id`, lots on `order_fill_id`, accruals on
`(account, date)`. A crashed run is resumed by re-running, not by manual repair.

---

## 10. Failure taxonomy

| Failure | Scope | Retry? |
|---|---|---|
| Egress IP mismatch | 🔴 everything | **Never** — infrastructure |
| Token invalid | account | No — regenerate |
| Negative attribution residual | account | No — reconcile first |
| GTT cancel unverified | account | No — halt |
| Sell authorisation missing | account's sell pass | No — operator acts |
| Insufficient funds | **one order** | No — record, continue (D-052) |
| Rate limited | one call | Yes — exponential backoff **with jitter** |
| Transient / 5xx | one call | Yes — bounded |
| Unknown order status | one order | **Treat as in-flight** (D-180) |
| Unmapped error | account | No — halt, preserve payload |

**An aborted run is `FAILED`, and the partial unique index excludes `FAILED`** — so the operator
can fix the cause and re-run the same day. That is deliberate: a failed run must not consume the
day's slot.

---

## 11. What a completed run leaves behind

Everything needed to answer "why did you do that?" without re-running anything:

- `run` — frozen config, mode, timings, status
- `run_candidate` — every instrument considered, every gate, every verdict
- `order_request` / `order_fill` / `position_lot` / `lot_closure`
- `charge` — computed and, where available, reported
- `capital_accrual_*` — the day's cost of capital
- `action_audit` — every operator override
- `run_log` — the narrative, also shipped to S3

> **The test of this design:** a year later, a single `run_id` should explain a decision
> completely — with no log archaeology and no guessing at what the thresholds were that day.
