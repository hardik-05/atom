# Module Map

**Status:** 🟢 Specified
**Date:** 2026-09-26
**Purpose:** the file-and-package layout, and the dependency rule that keeps it honest

> The brief asked for **completely modular** code — small scripts, per-broker wrappers, so that a
> broker changing its API touches exactly one file. This document is where that requirement becomes
> a directory tree and an import rule.

---

## 1. The dependency rule

```
web  →  reporting  →  strategy  →  adapters  →  (one broker each)
                 ↘        ↓            ↓
                   persistence  ←  domain models
```

**A module may import only from layers below it, never sideways and never up.** Three consequences
that matter more than the diagram:

1. `strategy/` contains no HTTP and no SQL.
2. `adapters/<broker>/` imports `domain/` and nothing else in the project. It cannot reach the
   database, the config or another adapter.
3. `domain/` imports nothing from the project at all. It is dataclasses and pure functions.

This is enforceable in CI with an import-linter rule, and it should be — a layering convention that
is only documented decays.

---

## 2. Tree

```
atom/
├── domain/                     ← pure: dataclasses, enums, pure functions. No I/O.
│   ├── models.py                 CanonicalHolding, OrderIntent, OrderState, Fill,
│   │                             GttIntent, GttState, ChargeSet, CashEvent, Quote
│   ├── enums.py                  Side, OrderKind, RunStatus, ExecutionMode, BasisKind
│   ├── money.py                  Decimal helpers, rounding, tick rounding
│   ├── deviation.py              (ltp − mean) / mean, 4dp
│   └── errors.py                 the canonical error taxonomy
│
├── adapters/                   ← one directory per broker; imports only domain/
│   ├── base.py                   BrokerAdapter protocol · BrokerCapabilities
│   ├── http.py                   proxy-aware client, retry, backoff+jitter, rate limiter
│   ├── registry.py               broker_code → adapter
│   ├── zerodha/{client,map,normalise,capabilities}.py
│   ├── groww/…     upstox/…     dhan/…     shoonya/…
│   └── fake/                     in-memory adapter for testing the layers above
│
├── persistence/                ← the only place SQL lives
│   ├── db.py                     connection, transaction helpers
│   ├── repositories/             one per aggregate: instruments, universes, runs,
│   │                             orders, lots, charges, capital, tax, config, sessions
│   └── migrations/               numbered SQL files
│
├── strategy/                   ← no HTTP, no SQL
│   ├── universe.py               snapshot resolution, SCD-2 membership
│   ├── basis.py                  actual vs synthetic averages; tranche computation
│   ├── gates/                    liquidity · nav_premium · freeze · one_lot_per_day
│   │                             · proxy_block · tradability · funds
│   ├── buy.py        sell.py     candidate selection · tranche targets
│   ├── harvest.py                pairing, carried basis, no-chaining guard
│   └── sizing.py                 floor(amount × buffer / ltp)
│
├── orchestration/
│   ├── runner.py                 the seven phases
│   ├── preflight.py              egress IP · token · calendar · sell authorisation
│   ├── reconcile.py              ownership + sellability
│   ├── settle.py                 fills → lots → charges → accrual
│   ├── execution_list.py         deferred work queue (D-022)
│   └── gateway.py                🔒 OrderGateway — the DRY/LIVE seam
│
├── reporting/
│   ├── pnl.py                    three numbers: strategy · cash · taxable
│   ├── charges.py                computed vs reported contrast
│   ├── capital.py                DEPLOYED / SETTLEMENT / IDLE accrual
│   ├── tax/                      fifo.py · setoff.py · exemption.py · compute.py
│   └── reports/                  per-universe, per-account, per-PAN renderers
│
├── infra/
│   ├── secrets.py                SSM Parameter Store; never logs a value
│   ├── egress.py                 verify_egress_ip
│   ├── telegram.py               bot commands, allow-list by chat id
│   └── logging/                  structured logger · S3 shipper · Drive sync
│
├── web/                          FastAPI JSON API (React app lives in frontend/)
└── cli/                          small entry points, one job each
```

```
frontend/                         React · TypeScript · Tailwind
scripts/                          standalone utilities (already exist)
tests/
├── unit/         domain, strategy — no I/O at all
├── adapters/     per broker, against recorded vendor fixtures
├── fixtures/     <broker>/*.json — vendor sample payloads, verbatim
└── integration/  orchestration against the fake adapter + a test database
```

---

## 3. The `OrderGateway` seam

The single most important boundary in the codebase, because it is what makes dry-run output
trustworthy (D-045).

```python
class OrderGateway(Protocol):
    def place(self, account, intent: OrderIntent) -> OrderState: ...
    def place_gtt(self, account, intent: GttIntent) -> GttState: ...
    def cancel(self, account, broker_order_id: str) -> OrderState: ...
    def cancel_gtt(self, account, broker_gtt_id: str) -> GttState: ...

LiveGateway(adapter)      # forwards to the broker
DryGateway(price_source)  # simulates fills; still writes every row
```

`DryGateway` writes **real** `order_request`, `order_fill`, `position_lot`, `charge` and accrual
rows. Dry and live share every line of strategy, gate, lot, tax and reporting code — which is the
whole point. A dry run that took a different code path would tell you nothing about the live one.

Selected once per run from the frozen `run.execution_mode`, never re-checked mid-run.

---

## 4. Adapter internals — the same four files, five times

| File | Contains | Cross-broker? |
|---|---|---|
| `capabilities.py` | the filled-in `BrokerCapabilities` | no |
| `client.py` | endpoints, auth header, serialisation, error classification | no |
| `map.py` | **stage 2** — pure field renaming and type casting | no |
| `normalise.py` | **stage 3** — the broker-specific computation | no |

Stage 3 is where the brokers actually differ, so `normalise.py` is where a reviewer should look
first. It holds, for example, `free_quantity` — one field on Dhan and Groww, four on Zerodha, three
on Upstox, **seven** on Shoonya.

`map.py` is deliberately dumb: a pure rename-and-cast step with no arithmetic, so it can be diffed
line-by-line against the vendor's documented field table. Anything that computes belongs in
`normalise.py`.

---

## 5. Module sizes worth holding to

Not arbitrary — each reflects a boundary that, once crossed, hides a decision.

| Module | Target | Why |
|---|---|---|
| A single gate | < 80 lines | One gate, one reason, one `decision_reason` string |
| `map.py` | mechanical, any length | It mirrors a vendor table; splitting it obscures the correspondence |
| `normalise.py` | < 300 lines | Beyond this, a broker's quirks are being smuggled in |
| `runner.py` | < 400 lines | It should read as the seven phases and delegate everything |
| A repository | one aggregate | Cross-aggregate queries belong in `reporting/` |

---

## 6. What must never appear where

The concrete form of §1, and the list CI should check:

| Forbidden | Where | Because |
|---|---|---|
| A broker name | `strategy/`, `reporting/`, `web/` | The adapter boundary would be leaking |
| `requests` / `httpx` | anywhere but `adapters/http.py` and `infra/` | One place for retries, proxy and rate limits |
| Raw SQL | anywhere but `persistence/` | |
| `float` for money | anywhere | `Decimal` only — `money.py` |
| `datetime.now()` without a timezone | anywhere | IST, tz-aware, always |
| A token value in a log line | anywhere | `secrets.py` returns opaque handles; `broker_session` stores the SSM **path** (D-079) |
| `MARKET` in a live order path | `adapters/*/client.py` | Not permitted via API since 1 Apr 2026 (D-174) |
| `MTF` / `INTRADAY` / `MIS` / `NRML` | any outbound payload | Delivery only (D-207) |
| A broker's `tick_size` used for pricing | `strategy/`, `adapters/` | ATOM's own value is authoritative (D-209) |

---

## 7. Build order

Each step is runnable and testable before the next begins. Nothing here needs a live broker until
step 7.

| # | Step | Needs |
|---|---|---|
| 1 | `domain/` | nothing |
| 2 | `persistence/` + migrations | Supabase (**X3**) |
| 3 | `adapters/base.py` · `http.py` · `fake/` | nothing |
| 4 | `strategy/` + gates, against `fake/` | steps 1–3 |
| 5 | `orchestration/` + `DryGateway` | steps 1–4 |
| 6 | `reporting/` + tax engine | step 5 |
| 7 | **Dhan adapter** — the strongest surface, fully headless auth | credentials (**X6**) |
| 8 | Zerodha adapter — hardest identity and per-session authorisation | credentials |
| 9 | Groww · Upstox adapters | credentials |
| 10 | `web/` + `frontend/` | step 6 |
| 11 | `infra/` — EC2, Lambda, proxy, Elastic IP | AWS (**X4**, **X5**) |
| 12 | Shoonya adapter | **Q-271** (GTT) and **Q-310** (token transport) |

**Dhan first among the adapters**, not Upstox as the earlier phase plan assumed (D-140). The
research changed the answer: Dhan is the only broker with a fully headless TOTP token, itemised
per-trade charges, a real ledger and lookup by ATOM's own reference — so it exercises the most of
the engine with the least operator involvement. Zerodha second precisely because it is hardest
(no GTT identity, per-session sell authorisation), and getting the two extremes working early
proves the abstraction holds.

**Shoonya last and gated on two open questions**, not merely scheduled late.

---

## 8. Related

[`SYSTEM-OVERVIEW.md`](SYSTEM-OVERVIEW.md) · [`RUN-LIFECYCLE.md`](RUN-LIFECYCLE.md) ·
[`CONFIGURATION-MODEL.md`](CONFIGURATION-MODEL.md) ·
[`EXECUTION-MODES-AND-DRY-RUN.md`](EXECUTION-MODES-AND-DRY-RUN.md) ·
[`../03-brokers/ADAPTER-ENGINE.md`](../03-brokers/ADAPTER-ENGINE.md) ·
[`../05-data/DATABASE-SCHEMA.md`](../05-data/DATABASE-SCHEMA.md)
