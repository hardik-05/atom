# The Adapter Engine

**Status:** 🟢 Framework specified — per-broker mappings written one at a time
**Date:** 2026-09-24
**Scope:** The two-way translation layer between five broker APIs and ATOM's 38-table schema

> Brokers are an **input to the system**. At each broker's boundary ATOM performs whatever
> computation, adjustment, renaming and restructuring that broker needs, and the engine emits a
> **single unified output** that goes into the database. The same layer runs in reverse: ATOM's
> intent goes out through the broker's own dialect.
>
> This document specifies the engine. Each broker then gets its own document in
> [`adapters/`](adapters/) giving its complete field-by-field mapping, written only after that
> broker's developer documentation has been read end to end.

---

## 1. The shape of the problem

Round 2 of the research established that the five brokers disagree on nearly everything that is
not the price of a share:

| | Upstox | Dhan | Zerodha | Groww | Shoonya |
|---|---|---|---|---|---|
| Instrument key | `NSE_EQ\|INE669E01016` | `securityId` "1333" | `instrument_token` 408065 | `trading_symbol` "TCS" | `tsym` "CANBK-EQ" |
| Side | `BUY`/`SELL` | `BUY`/`SELL` | `BUY`/`SELL` | `BUY`/`SELL` | **`B`/`S`** |
| Delivery product | **`D`** | **`CNC`** | **`CNC`** | **`CNC`** | **`C`** |
| Order type | `LIMIT` | `LIMIT` | `LIMIT` | `LIMIT` | **`LMT`** |
| Numbers | JSON numbers | JSON numbers | form-encoded | **decimal strings** | **strings in JSON** |
| Success signal | `status: "success"` | HTTP code | `status: "success"` | `status: "SUCCESS"` | **`stat: "Ok"`** |
| ATOM's own ref | `tag` | `correlationId` | `tag` ≤20 | `order_reference_id` **required** | `remarks` |
| Charges | ❓ | per-trade on `/trades` | **`POST /charges/orders`** | ❓ | ❓ |
| GTT identity | ❓ | `correlationId` | **none until fired** | `reference_id` | ❓ |

None of this can leak past the adapter. The strategy engine, the tax engine, the reporting layer
and the console must never contain the word `tsym`, never branch on which broker an account uses,
and never learn that Shoonya says `B` where everyone else says `BUY`.

**The test of this design:** adding a sixth broker touches exactly one new directory and one row
in `atom.broker`. Changing a broker's API touches exactly one adapter. If either statement stops
being true, the engine has been designed wrong.

---

## 2. Architecture — two directions, five stages each

```
                          ┌──────────────────────────────────────┐
                          │         STRATEGY / TAX / UI          │
                          │   speaks only instrument_id, ₹,      │
                          │   BUY/SELL, canonical models         │
                          └───────────────▲──────────┬───────────┘
                                          │          │
                                  canonical models   │ intent
                                          │          ▼
   ┌──────────────────────────────────────┴──────────────────────────────────┐
   │                            ADAPTER ENGINE                               │
   │                                                                         │
   │   INBOUND  (broker → DB)              OUTBOUND  (DB → broker)           │
   │   ─────────────────────               ──────────────────────           │
   │   5. persist   ▲                      1. resolve    │                   │
   │   4. enrich    │                      2. translate  │                   │
   │   3. normalise │                      3. serialise  │                   │
   │   2. map       │                      4. transmit   │                   │
   │   1. fetch     │                      5. record     ▼                   │
   │                │                                    │                   │
   │        ┌───────┴────────┬─────────┬─────────┬───────┴──────┐            │
   │        │ UpstoxAdapter  │ Dhan…   │ Zerodha…│ Groww…       │ Shoonya…   │
   │        └───────▲────────┴────▲────┴────▲────┴──────▲───────┴─────▲──────┘
   └────────────────┼─────────────┼─────────┼───────────┼─────────────┼──────┘
                    │             │         │           │             │
                 raw HTTP over the per-investor static-IP proxy (D-011, D-173)
```

Every adapter is a **pure translator plus an HTTP client**. It holds no strategy logic, makes no
trading decision, and writes nothing to the database itself — it returns canonical objects, and
the engine persists them. That separation is what makes an adapter testable against recorded
fixtures with no database and no network.

### 2.1 Inbound — broker to database

| Stage | Owner | What happens |
|---|---|---|
| **1 · Fetch** | Adapter | Raw HTTP through the account's proxy. Retries, backoff, rate-limit handling. Output: the vendor's raw JSON/CSV, **unmodified** |
| **2 · Map** | Adapter | Rename and re-type fields. `tsym` → `symbol`, `"3985.00"` → `Decimal("3985.0000")`, `B` → `BUY`. **No computation** — a pure renaming and casting step so it can be diffed against the vendor doc |
| **3 · Normalise** | Adapter | Broker-specific computation: derive `free_quantity` from whichever fields that broker exposes, collapse a multi-leg GTT into ATOM's single-leg model, sum `gst.igst + cgst + sgst`. **This is where the brokers actually differ, and where the per-broker documents spend their pages** |
| **4 · Enrich** | Engine | Broker-agnostic: resolve `broker_token` → `instrument_id` via `broker_instrument`, attach `trading_account_id`, `universe_id`, `run_id`, stamp timestamps in IST |
| **5 · Persist** | Engine | Write canonical rows to the schema. Idempotent on natural keys |

Stage 3 is the heart of it. Stages 1–2 are mechanical; stages 4–5 are identical for every broker.
**A per-broker adapter document is largely a specification of its stage 3.**

### 2.2 Outbound — database to broker

| Stage | Owner | What happens |
|---|---|---|
| **1 · Resolve** | Engine | `instrument_id` → that broker's `broker_token` and `broker_symbol`. Load the account's capability profile and config |
| **2 · Translate** | Adapter | Canonical intent → the broker's vocabulary: product code, order type, validity, side, and the `client_ref` mapped to whichever field the broker offers |
| **3 · Serialise** | Adapter | The broker's wire format — JSON, form-encoded, or `jData=` text/plain. Decimal→string where required |
| **4 · Transmit** | Adapter | Send. Classify the response into the canonical error taxonomy (§6) |
| **5 · Record** | Engine | Persist `broker_order_id` **before returning** (D-176), update `order_request.status` |

> **Write-before-send, always.** `order_request` with `idempotency_key` and status `INTENT` is
> committed *before* the HTTP call (D-094). If ATOM crashes mid-call, the next run finds an
> `INTENT` row and reconciles against the broker's order book rather than placing a second order.
> On Zerodha this is not merely prudent — an unrecorded GTT is **permanently unidentifiable**
> (D-176), so the recording step is part of correctness, not of logging.

---

## 3. Canonical models

The complete vocabulary between the engine and everything above it. Types are the DB's types, so
persistence is a field copy.

### 3.1 `Instrument` — inbound only, from the broker's instrument master

```python
@dataclass(frozen=True)
class CanonicalInstrument:
    isin:          str | None      # the join key; None means unresolvable → REVIEW
    symbol:        str
    exchange:      str             # NSE | BSE
    name:          str
    broker_token:  str             # verbatim, whatever the broker calls it
    broker_symbol: str
    lot_size:      int   = 1
    tick_size:     Decimal | None = None
    tradable:      bool  = True
    instrument_type: str | None = None   # EQ / ETF as the broker labels it
```

→ `atom.broker_instrument` (+ `atom.instrument` on first sight, status `REVIEW` until classified)

**ISIN is the only universal join key.** Zerodha publishes it in the instruments dump *and* in
holdings; Dhan on trades; Groww on holdings and trades; Upstox embeds it in the token itself. A
broker row whose ISIN cannot be resolved is **never** matched by symbol — symbols collide across
exchanges and get renamed by corporate actions. It goes to `REVIEW` for a human (D-091).

### 3.2 `Holding`

```python
@dataclass(frozen=True)
class CanonicalHolding:
    instrument_id:   int
    total_quantity:  int             # everything owned, for the attribution identity
    free_quantity:   int | None      # sellable TODAY; None = broker doesn't say
    average_price:   Decimal
    last_price:      Decimal | None
    pledged_quantity:    int = 0
    unsettled_quantity:  int = 0     # T1
    broker_flags:   dict = field(default_factory=dict)   # e.g. Zerodha's `discrepancy`
```

→ feeds the reconciliation in `HOLDINGS-ATTRIBUTION.md` §1 and §1a.

**Two fields, two different jobs.** `total_quantity` answers *do our books agree with the
broker's*; `free_quantity` answers *can this sell actually execute*. The sell pass caps at
`free_quantity` and defers the remainder with a logged reason rather than attempting it and
taking the rejection (Q-272, resolved). Where `free_quantity` is `None` the engine falls back to
`total_quantity` **and logs that it is doing so** — that is precisely the case where a
foreseeable rejection becomes possible again.

### 3.3 `OrderIntent` (outbound) and `OrderState` (inbound)

```python
@dataclass(frozen=True)
class OrderIntent:
    trading_account_id: int
    universe_id:        int
    instrument_id:      int
    side:               Literal["BUY", "SELL"]
    quantity:           int
    limit_price:        Decimal          # always; MARKET does not exist (D-174)
    client_ref:         str              # ≤20 chars, ATOM-generated (D-175)
    product:            Literal["DELIVERY"] = "DELIVERY"
    validity:           Literal["DAY"] = "DAY"
    algo_id:            str | None = None     # reserved, unset (D-181)

@dataclass(frozen=True)
class OrderState:
    broker_order_id:  str
    client_ref:       str | None
    status:           Literal["INTENT","PLACED","PARTIAL","FILLED",
                              "CANCELLED","REJECTED","IN_FLIGHT"]
    filled_quantity:  int
    pending_quantity: int
    average_price:    Decimal | None
    reject_reason:    str | None         # the broker's verbatim text (D-042)
    raw_status:       str                # kept for forensics
```

> **`IN_FLIGHT` is the mandatory default.** Zerodha alone publishes eight transient statuses and
> warns "there may be other values as well". Every adapter's status map ends in
> `_ => IN_FLIGHT`. Mapping an unrecognised status to `REJECTED` would make ATOM re-place an
> order that is about to fill — the one bug in this layer that loses real money silently (D-180).

### 3.4 `Fill`

```python
@dataclass(frozen=True)
class CanonicalFill:
    broker_order_id: str
    broker_trade_id: str
    quantity:        int
    fill_price:      Decimal
    filled_at:       datetime            # IST, tz-aware
```

→ `atom.order_fill`, and **one `position_lot` per fill** (D-166). Never aggregate fills before
persisting: the lot grain is the fill, and averaging them destroys the tax-FIFO basis.

### 3.4a Sell tranches — the sell pass emits a list, not an order (D-195, D-198)

A position whose lots carry a **mix** of synthetic and actual cost bases cannot be sold against
one blended average: the proxy units would exit below the capital they are recovering and the
shortfall would be booked as a gain. So the sell pass produces **tranches**:

```python
@dataclass(frozen=True)
class SellTranche:
    instrument_id: int
    basis_kind:    Literal["SYNTHETIC", "ACTUAL"]
    quantity:      int
    target_price:  Decimal     # weighted basis × (1 + threshold)
```

At most **two** per (account, universe, instrument): synthetic lots blend with each other, actual
lots blend with each other, and only the boundary between them splits. An instrument with no
synthetic lots yields a single `ACTUAL` tranche — today's behaviour exactly.

Each tranche becomes one `GttIntent`. D-156 already requires multiple GTTs per instrument and
D-164 confirmed all five brokers support it, so this needs no capability change — but the
cancel-all-first step must expect **up to two** ATOM sell orders per instrument and not treat the
second as a duplicate. Full derivation in
[`../04-strategy/HARVEST-COST-BASIS.md`](../04-strategy/HARVEST-COST-BASIS.md) §4.

### 3.5 `GttOrder`

```python
@dataclass(frozen=True)
class GttIntent:
    instrument_id: int
    side:          Literal["SELL"]       # ATOM only ever places sell GTTs
    quantity:      int
    trigger_price: Decimal
    limit_price:   Decimal
    client_ref:    str
    last_price:    Decimal | None = None # required by Zerodha at placement

@dataclass(frozen=True)
class GttState:
    broker_gtt_id: str
    client_ref:    str | None            # None where the broker cannot carry one
    status:        Literal["ACTIVE","TRIGGERED","CANCELLED","EXPIRED","REJECTED","UNKNOWN"]
    instrument_id: int | None
    trigger_price: Decimal | None
    quantity:      int | None
    is_ours:       bool                  # see below
```

**`is_ours` is computed by the engine, not the broker.** Where the broker carries a `client_ref`
(Dhan, Groww) it is read back and matched. Where it does not (Zerodha), `is_ours` is `True` only
if `broker_gtt_id` is in ATOM's own table. **An unknown GTT is never cancelled** — it may be the
investor's own (D-064).

### 3.6 `ChargeSet`

```python
@dataclass(frozen=True)
class CanonicalCharges:
    brokerage:  Decimal = Decimal(0)
    stt:        Decimal = Decimal(0)
    exchange:   Decimal = Decimal(0)
    sebi:       Decimal = Decimal(0)
    stamp:      Decimal = Decimal(0)
    gst:        Decimal = Decimal(0)     # igst + cgst + sgst collapsed
    dp:         Decimal = Decimal(0)
    source:     Literal["COMPUTED", "BROKER"]
```

→ `atom.charge`, one row per non-zero component. `source` is what makes the estimated-vs-reported
contrast possible (D-024) — both sets coexist for the same order, which is why `atom.charge` is
deliberately not unique on `(order, type)`.

### 3.7 `CashEvent`

```python
@dataclass(frozen=True)
class CanonicalCashEvent:
    event_date:  date
    amount:      Decimal                 # signed: + credit, − debit
    event_type:  Literal["DEPOSIT","WITHDRAWAL","SETTLEMENT","CHARGE","UNKNOWN"]
    narration:   str                     # verbatim
    running_balance: Decimal | None      # where the broker gives it
    broker_ref:  str | None
```

→ `atom.cash_ledger`. `UNKNOWN` is a first-class outcome: an unrecognised narration is stored as
`UNKNOWN` and surfaced for classification, never guessed into a bucket that would corrupt the
cost-of-capital model.

### 3.8 `Quote`

```python
@dataclass(frozen=True)
class CanonicalQuote:
    instrument_id: int
    last_price:    Decimal
    close_price:   Decimal | None
    volume:        int | None
    as_of:         datetime
```

Used for GTT placement inputs and dry-run pricing. **Not** the strategy's price source — that
comes from a single provider for all accounts (D-044), because Zerodha's `/quote` and Dhan's
quote API are both capped at **1 request per second**.

---

## 4. The capability profile

Each adapter declares what it can do. The engine reads the declaration and adapts; it never
branches on a broker's name.

```python
@dataclass(frozen=True)
class BrokerCapabilities:
    broker_code: str

    # GTT
    supports_gtt:            bool
    gtt_max_validity_days:   int | None
    gtt_carries_client_ref:  bool      # False → identification is DB-only (D-176)
    gtt_order_type:          Literal["LIMIT", "LIMIT_OR_MARKET"]

    # Orders
    client_ref_field:        str | None
    client_ref_max_len:      int
    client_ref_is_idempotent: bool     # True → safe blind retry (Groww)
    lookup_by_client_ref:    bool

    # Data
    provides_trade_charges:  bool
    provides_charge_preview: bool      # pre-trade estimate from the broker itself
    provides_ledger:         bool
    provides_free_quantity:  bool

    # Infrastructure
    requires_static_ip:      bool
    static_ip_scope:         Literal["ORDERS_ONLY", "ALL_CALLS"]
    static_ip_lock_days:     int
    token_probe_endpoint:    Literal["PROFILE", "HOLDINGS"]
    token_revocable:         bool
    requires_sell_authorisation: bool
    sell_authorisation_scope: Literal["ONE_TIME", "PER_SESSION", "NONE"]

    # Limits
    orders_per_second:       int
    quote_batch_size:        int | None
```

This turns every round-2 finding into a machine-readable fact. `static_ip_scope = ORDERS_ONLY`
is why Dhan needs egress verified separately from the token probe (D-173).
`sell_authorisation_scope` is where Upstox's one-time EDIS and Zerodha's **per-session** CDSL
authorisation stop being footnotes and start being code.

---

## 5. Instrument resolution

The single most important inbound mapping, and the one that must never be approximate.

```
  daily 08:30 IST
       │
       ▼
  broker instrument master  (CSV dump or JSON list)
       │
       ├── has ISIN? ──no──► REVIEW queue, never auto-match on symbol
       │
      yes
       ▼
  match atom.instrument on (isin, exchange)
       │
       ├── found ────► upsert broker_instrument(broker_id, instrument_id, broker_token)
       │
       └── not found ► insert instrument(status='REVIEW') + notify
```

**Rules, all of them learned from a specific broker's documentation:**

1. **Match on ISIN, never on symbol.** Symbols collide across exchanges and are renamed by
   corporate actions; ISIN survives both.
2. **Store the broker's token verbatim.** `broker_instrument.broker_token` is a `text` column
   precisely so it can hold `NSE_EQ|INE669E01016`, `"1333"` and `408065` without coercion.
3. **Refresh daily, before the run.** Zerodha states the dump "is generated once everyday" and
   recommends ~08:30 AM.
4. **Never key ATOM's own storage on a broker's numeric token.** Zerodha warns exchanges may
   *reuse* instrument tokens after expiry. The schema's `UNIQUE (broker_id, instrument_id)` plus
   a daily re-resolve is what protects against it.
5. **A token that changes for an existing ISIN updates the row and logs it.** A silent change
   would send the next order to a different security.

---

## 6. Error taxonomy

Every adapter maps its broker's failures onto one closed set. The engine's retry, alert and
abort behaviour keys off this and nothing else.

| Canonical | Meaning | Engine behaviour |
|---|---|---|
| `AuthError` | Token expired/invalid/revoked | Mark `broker_session` INVALID, **halt this account's run**, alert |
| `IpBlockedError` | Egress IP not whitelisted | **Halt everything, never retry.** Infrastructure fault (D-173) |
| `RateLimitError` | Throttled | Exponential backoff **with jitter**, bounded retries |
| `InsufficientFundsError` | Margin/cash shortfall | Record verbatim reason, **continue to the next order** (D-052) |
| `InsufficientHoldingsError` | Not enough sellable stock | Halt account, trigger reconciliation — ATOM's books are wrong |
| `AuthorisationRequiredError` | Depository/EDIS authorisation needed | Halt the sell pass, alert operator with the authorisation link |
| `ValidationError` | Bad payload | **Bug.** Fail loudly, never retry |
| `DuplicateRefError` | `client_ref` already used | **Success, already placed.** Fetch and reconcile, never re-place |
| `TransientError` | Network, 502/503/504, OMS down | Bounded retry, then halt account |
| `UnknownError` | Anything unmapped | Halt account, preserve the raw payload |

**`DuplicateRefError` is not a failure.** Groww's `GA007` means the order exists. Treating it as
an error would report a false failure on a perfectly good order and, worse, invite a re-place.

---

## 7. What every adapter must implement

```python
class BrokerAdapter(Protocol):
    capabilities: BrokerCapabilities

    # session
    def build_auth_url(self, account) -> str | None: ...
    def exchange_code(self, account, code: str) -> Token: ...
    def probe_token(self, account) -> TokenProbe: ...          # D-170 / D-178
    def revoke_token(self, account) -> None: ...               # no-op where unsupported

    # reference data
    def fetch_instruments(self) -> Iterable[CanonicalInstrument]: ...

    # read
    def fetch_holdings(self, account) -> list[CanonicalHolding]: ...
    def fetch_positions(self, account) -> list[CanonicalHolding]: ...
    def fetch_quotes(self, account, tokens) -> list[CanonicalQuote]: ...
    def fetch_orders(self, account) -> list[OrderState]: ...
    def fetch_fills(self, account, since: date) -> list[CanonicalFill]: ...
    def fetch_charges(self, account, orders) -> dict[str, CanonicalCharges]: ...
    def fetch_ledger(self, account, frm: date, to: date) -> list[CanonicalCashEvent]: ...

    # write
    def place_order(self, account, intent: OrderIntent) -> OrderState: ...
    def cancel_order(self, account, broker_order_id: str) -> OrderState: ...
    def place_gtt(self, account, intent: GttIntent) -> GttState: ...
    def cancel_gtt(self, account, broker_gtt_id: str) -> GttState: ...
    def fetch_gtts(self, account) -> list[GttState]: ...

    # optional, declared in capabilities
    def preview_charges(self, account, intents) -> dict[str, CanonicalCharges]: ...
    def initiate_sell_authorisation(self, account, isins) -> AuthorisationRequest: ...
```

Seventeen required methods plus two optional. `modify_order` and `modify_gtt` are **deliberately
absent** — ATOM cancels and re-places (D-063), and an unused method is a liability that invites
someone to use it.

---

## 8. Testing contract

Each adapter ships with:

1. **Recorded fixtures** — the vendor's own documented sample payloads, verbatim, in
   `tests/fixtures/<broker>/`. They come from the documentation, so a vendor change shows up as
   a test failure when the fixtures are refreshed.
2. **Round-trip tests** — `OrderIntent → wire payload → recorded response → OrderState`, with the
   payload asserted field by field against the vendor doc.
3. **A status-mapping test that includes a deliberately invented status string** and asserts it
   maps to `IN_FLIGHT`. This is the D-180 guard, and it is not optional.
4. **An error-mapping test per canonical error**, driven by the broker's own documented error
   codes.
5. **A normalisation test for `free_quantity`** built from that broker's real field set.

No adapter test touches the network or the database. The engine is tested once, against a fake
adapter, and the adapters are tested against fixtures — so five brokers cost five fixture sets,
not five integration environments.

---

## 9. Per-broker document template

Every file in [`adapters/`](adapters/) follows this structure, so the five are diffable:

```
1. Capability profile               — the dataclass, filled in
2. Wire basics                      — base URL, auth header, content type, envelope
3. Session lifecycle                — auth URL, code exchange, probe, revoke
4. Instrument master                — source, columns, ISIN availability, resolution notes
5. Inbound mappings                 — one table per canonical model:
                                      broker field → canonical field → DB column
6. Stage-3 normalisation            — the computations unique to this broker
7. Outbound mappings                — OrderIntent and GttIntent → wire payload
8. Status map                       — every documented status → canonical, + default
9. Error map                        — every documented code → canonical error
10. Charges                         — where they come from, or why they don't
11. Ledger / cash events            — narration classification
12. Broker-specific hazards         — the things that will break if forgotten
13. Open questions
14. Sources                         — every page read, with fetch date
```

### Order of work

**Zerodha → Groww → Upstox → Dhan → Shoonya.**

Zerodha and Groww first because they are the two extremes: Zerodha carries no GTT identity and
needs per-session sell authorisation, Groww has the strongest identity and idempotency model of
the five. **An engine that satisfies both ends of that range will hold the middle.** Shoonya last
because its GTT surface is still unpublished (Q-271) and it is the only broker whose adapter
might need to fall back to DAY limit orders (D-129).

---

## 10. Related decisions

D-056b (raw HTTP, not vendor SDKs) · D-063/D-064 (GTT cancel-all-first, ATOM's own only) ·
D-094 (write intent before send) · D-166 (one lot per fill) · D-170/D-178 (token probed, not
assumed) · D-173 (static IP; egress verified separately) · D-174 (no MARKET) · D-175
(`client_ref`) · D-176 (Zerodha GTT identity is DB-only) · D-179 (charges ground truth) ·
D-180 (unknown status is in-flight) · D-195/D-198 (sell tranches) · D-199 (`lookup_by_client_ref`
on Dhan)

---

## 11. Per-broker documents

| # | Broker | Document |
|---|---|---|
| 1 | Zerodha | [`adapters/ZERODHA-ADAPTER.md`](adapters/ZERODHA-ADAPTER.md) |
| 2 | Groww | [`adapters/GROWW-ADAPTER.md`](adapters/GROWW-ADAPTER.md) |
| 3 | Upstox | [`adapters/UPSTOX-ADAPTER.md`](adapters/UPSTOX-ADAPTER.md) |
| 4 | Dhan | [`adapters/DHAN-ADAPTER.md`](adapters/DHAN-ADAPTER.md) |
| 5 | Shoonya | [`adapters/SHOONYA-ADAPTER.md`](adapters/SHOONYA-ADAPTER.md) |

A side-by-side comparison of what each broker does and does not provide is in
[`BROKER-CAPABILITY-MATRIX.md`](BROKER-CAPABILITY-MATRIX.md) §6.
