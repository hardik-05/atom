# Groww Trading API — Adapter Specification

**Status:** 🟢 Complete — every mapping traced to a Groww API page read 2026-09-25
**Order of work:** 2nd of 5 (see [`../ADAPTER-ENGINE.md`](../ADAPTER-ENGINE.md) §9)
**Pages read:** introduction · instruments · orders · smart orders · portfolio · margin ·
annexures

> **Why Groww second.** It is Zerodha's opposite. Zerodha carries **no** GTT identity and hides
> ISIN from its instrument master; Groww has a **required** idempotency key, returns ISIN in a
> public CSV, and publishes `demat_free_quantity` directly. An engine that satisfies both ends
> of that range will hold the middle three.

---

## 1. Capability profile

```python
GROWW = BrokerCapabilities(
    broker_code               = "GROWW",

    supports_gtt              = True,
    gtt_max_validity_days     = 365,           # forced by Groww, not chosen
    gtt_carries_client_ref    = True,          # 🟢 reference_id
    gtt_order_type            = "LIMIT",       # LIMIT or SL; ATOM uses LIMIT

    client_ref_field          = "order_reference_id",
    client_ref_max_len        = 20,            # 8–20, ≤2 hyphens
    client_ref_is_idempotent  = True,          # 🟢 duplicate → GA007
    lookup_by_client_ref      = True,          # 🟢 GET /v1/order/status/reference/{id}

    provides_trade_charges    = False,         # only an aggregate, see §5.6
    provides_charge_preview   = True,          # aggregate only
    provides_ledger           = False,
    provides_free_quantity    = True,          # 🟢 demat_free_quantity, direct

    requires_static_ip        = True,          # ❓ procedure undocumented (Q-274)
    static_ip_scope           = "ALL_CALLS",   # assumed strictest until confirmed
    static_ip_lock_days       = 0,

    token_probe_endpoint      = "HOLDINGS",    # no profile endpoint; see §3.3
    token_revocable           = True,          # via the web console, not the API

    requires_sell_authorisation  = False,      # ❓ not documented (Q-291)
    sell_authorisation_scope     = "NONE",

    orders_per_second         = 10,
    quote_batch_size          = None,          # not documented
)
```

---

## 2. Wire basics

| | |
|---|---|
| Base URL | `https://api.groww.in` |
| Auth | `Authorization: Bearer {ACCESS_TOKEN}` |
| Required headers | `Accept: application/json` · **`X-API-VERSION: 1.0`** |
| Encoding | JSON body on POST/PUT; query params on GET |
| Success | `{"status": "SUCCESS", "payload": {…}}` |
| Failure | `{"status": "FAILURE", "error": {"code","message","metadata"}}` |
| Segments | **`CASH` and `FNO` only** — no `COMMODITY` |

**`X-API-VERSION: 1.0` is mandatory on every call.** Groww states "all headers are mandatory".
An adapter that omits it will fail in ways that look like auth problems.

**Prerequisite:** an **active paid Trading API subscription**. Groww is the only one of the five
that charges for order APIs (Q-275).

---

## 3. Session lifecycle

### 3.1 Three methods, none fully unattended

| # | Method | Mechanism | Catch |
|---|---|---|---|
| 1 | **Access token** | Profile → Settings → Trading APIs → Generate | Expires daily **06:00** |
| 2 | **Key + secret** | `POST /v1/token/api/access`, `key_type:"approval"`, `checksum = SHA256(secret + epoch_seconds)`, timestamp valid 10 min | **Daily approval click** in Groww's console |
| 3 | **Key + TOTP** | Same endpoint, `key_type:"totp"`, `totp:"123456"` | **Daily approval click**, same page |

Response: `{token, tokenRefId, sessionName, expiry, isActive}`.

> **Groww is not fully automatable.** Methods 2 and 3 make the *call* headless, but Groww still
> requires a human to approve on its Cloud API Keys page each day. The operator action moves
> from "copy a token" to "click approve" — still a daily touch. Pattern C (paste-in) from D-177
> remains the guaranteed path.

`/v1/token/api/access` is capped at **150 requests per 24 hours** on top of the 5/s · 30/min
authentication limit.

### 3.2 The 06:00 boundary

Same as Zerodha. Tokens are generated after 06:00 IST and the market opens at 09:15, so the
boundary is never crossed (D-184).

### 3.3 Probe — holdings, because there is no profile endpoint

Groww publishes no `/profile` equivalent, so `token_probe_endpoint = "HOLDINGS"` — the D-170
default rather than D-178's preferred profile call. `GET /v1/holdings/user` is cheap and in the
"Non Trading" rate bucket (20/s).

`GET /v1/margins/detail/user` is an equally valid probe and additionally returns `clear_cash`,
which the buy pass needs anyway. **The adapter probes with margins and falls back to holdings**,
so one call does two jobs.

### 3.4 Revoke

Tokens are created, revoked and managed from Groww's web console. No documented API. ATOM
deletes the SSM parameter and marks the session `CLEARED`; it cannot actively destroy the token
the way it can on Zerodha.

---

## 4. Instrument master — 🟢 the easy one

**Public CSV, no authentication:**
`https://growwapi-assets.groww.in/instruments/instrument.csv`

| CSV column | → `CanonicalInstrument` | Note |
|---|---|---|
| **`isin`** | **`isin`** | 🟢 **present** — unlike Zerodha's dump |
| `trading_symbol` | `broker_token`, `broker_symbol` | **This is the order key** |
| `groww_symbol` | — | Groww's internal name; **not** what orders take |
| `exchange_token` | — | Exchange's number; not used for ordering |
| `name` | `name` | |
| `exchange` | `exchange` | `NSE` / `BSE` |
| `segment` | — | ATOM filters to `CASH` |
| `series` | — | `EQ`, `A`, `B`… |
| `instrument_type` | `instrument_type` | `EQ` · `IDX` · `FUT` · `CE` · `PE` |
| `tick_size` | `tick_size` | |
| `lot_size` | `lot_size` | |
| `buy_allowed` | `tradable` (AND) | 🟢 see §6.3 |
| `sell_allowed` | `broker_flags` | 🟢 see §6.3 |
| `is_reserved` | `broker_flags` | 🟢 see §6.3 |

**Two things this fixes that Zerodha could not.**

1. **ISIN is in the master**, so instrument resolution follows the engine's rule
   (`ADAPTER-ENGINE.md` §5) exactly — match on ISIN, never on symbol. None of the
   seed-and-confirm compromise D-187 needed for Zerodha applies here.
2. **The CSV is public**, so it is fetched **once per day for all accounts**, before any token
   exists, and outside every rate limit. On Zerodha the dump needs an authenticated call per
   session.

⚠️ `broker_token` stores **`trading_symbol`**, because that is what `POST /v1/order/create`
takes. Storing `exchange_token` or `groww_symbol` would produce orders Groww rejects. This is
the one broker where the "token" is a human-readable symbol, and the schema's `text` column
(D-187) accommodates it without special-casing.

---

## 5. Inbound mappings

### 5.1 Holdings — `GET /v1/holdings/user`

| Groww field | → Canonical | Note |
|---|---|---|
| `isin` | *(join key)* | 🟢 |
| `trading_symbol` | *(join key, secondary)* | |
| `quantity` | `total_quantity` | "net quantity" — ⚠️ see Q-289 |
| **`demat_free_quantity`** | **`free_quantity`** | 🟢 **direct** — no derivation needed |
| `t1_quantity` | `unsettled_quantity` | |
| `pledge_quantity` + `repledge_quantity` | `pledged_quantity` | Summed |
| `demat_locked_quantity` | `broker_flags` | |
| `groww_locked_quantity` | `broker_flags` | |
| `corporate_action_additional_quantity` | `broker_flags` | 🟢 feeds `CORPORATE-ACTIONS.md` |
| `active_demat_transfer_quantity` | `broker_flags` | Transfer out in flight |
| `average_price` | `average_price` | |
| — | `last_price` | ❌ **not returned** — quotes must be fetched separately |
| — | `exchange` | 🔴 **not returned** — see §6.2 |

**Groww is the only broker of the five that hands ATOM the sellable quantity directly.** On
Zerodha it is derived from four fields (`ZERODHA-ADAPTER.md` §6.1); here `demat_free_quantity`
is exactly D-182's cap. It is also the reference implementation for what the other adapters
approximate.

### 5.2 Positions — `GET /v1/positions/user`

Carries `exchange` and `symbol_isin` (which holdings does not), plus `credit_*` / `debit_*` /
`carry_forward_*` breakdowns and `realised_pnl`.

ATOM trades delivery only, so positions are read for **reconciliation and same-day awareness**,
not as the position of record. `realised_pnl` is **not ingested** — ATOM computes P&L per lot
per universe from its own fills (D-156, D-166). Same rule as Zerodha §5.1.

### 5.3 Orders — `GET /v1/order/list` · `GET /v1/order/detail/{id}` · `GET /v1/order/status/reference/{ref}`

| Groww | → `OrderState` |
|---|---|
| `groww_order_id` | `broker_order_id` |
| `order_reference_id` | `client_ref` |
| `order_status` | `status` (via §8) |
| *(raw)* | `raw_status` |
| `filled_quantity` | `filled_quantity` |
| `remaining_quantity` | `pending_quantity` |
| `average_fill_price` | `average_price` |
| `remark` | `reject_reason` |

🟢 **`GET /v1/order/status/reference/{order_reference_id}` looks an order up by ATOM's own
identifier.** This is what makes Groww's recovery path exact rather than a race — see §6.1.

Pagination: `page` from 0, `page_size` max **100** for `/order/list`, max **50** for
`/order/trades`.

### 5.4 Fills — `GET /v1/order/trades/{groww_order_id}?segment=CASH`

| Groww | → `CanonicalFill` |
|---|---|
| `groww_trade_id` | `broker_trade_id` |
| `groww_order_id` | `broker_order_id` |
| `quantity` | `quantity` |
| `price` | `fill_price` |
| `trade_date_time` | `filled_at` |

Also returns `isin`, `exchange_trade_id`, `exchange_order_id`, `settlement_number` and
`trade_status`. One row per fill — the grain D-166 needs.

🟢 **`settlement_number`** is unique to Groww among the five and is a real signal for
`COST-OF-CAPITAL.md`: the SETTLEMENT bucket currently infers T+1 from the trade date (D-050,
D-080 — "observed, never assumed"). A settlement identifier is closer to observation than a
date computation. Worth exploring (Q-290).

### 5.5 Smart Orders (GTT) — `GET /v1/order-advance/list`

| Groww | → `GttState` |
|---|---|
| `smart_order_id` | `broker_gtt_id` |
| `reference_id` | `client_ref` 🟢 |
| `status` | `status` (§8.2) |
| `trigger_price` | `trigger_price` (string → Decimal) |
| `quantity` | `quantity` |
| `is_cancellation_allowed` | `broker_flags` — **read before cancelling** |
| `is_modification_allowed` | `broker_flags` |
| `expire_at` | `broker_flags` |

⚠️ **The list window is capped at one month** (`start_date_time` / `end_date_time`, "must not
exceed one month") and defaults to *today only*. The cancel-all-first verification (D-063) must
pass an explicit window and page through results — a default call would return only GTTs created
today and report the book clean when it is not.

### 5.6 Charges — aggregate only 🟡

`POST /v1/margins/detail/orders?segment=CASH` returns `brokerage_and_charges` and
`total_requirement`. `GET /v1/margins/detail/user` returns a `brokerage_and_charges` total.

**There is no per-component breakdown** — no separate STT, stamp duty, exchange or SEBI turnover,
no GST split. Nothing in the order, trade or portfolio responses carries one either.

This answers Q-273 for Groww, and the answer is partial:

| | Dhan | Zerodha | **Groww** |
|---|---|---|---|
| Per-component breakdown | ✅ per trade | ✅ `/charges/orders` | ❌ |
| Aggregate total | ✅ | ✅ | ✅ |
| Prices imaginary orders | ❌ | ✅ | ✅ (pre-trade) |

So on Groww the charges-contrast view (D-024, D-179) shows **ATOM's computed breakdown against
a single broker total**. The components remain ATOM's model; only the sum can be checked. That
degradation must be visible in the UI, not silent — the per-component column is labelled
*computed* and the total carries a *broker* badge.

`cash_cnc_margin_required` and `clear_cash` give the buy pass a real funds check before placing
(D-052).

### 5.7 Ledger — not available

No ledger endpoint. Same position as Zerodha: `atom.cash_ledger` is populated from ATOM's own
fills plus manual statement upload. Only Dhan gives a true ledger with `runbal` (D-179). Q-279
extends to Groww.

---

## 6. Stage-3 normalisation

### 6.1 `client_ref` — the reference implementation

Groww is where the canonical `client_ref` (D-175) came from:

- **Required** on `POST /v1/order/create` — 8–20 alphanumeric, at most two hyphens
- Duplicate → **`GA007`**, which is `DuplicateRefError`, which the engine treats as
  **success, already placed** (`ADAPTER-ENGINE.md` §6)
- Looked up directly via `GET /v1/order/status/reference/{ref}`
- Smart Orders use the same mechanism under the name `reference_id`

**The recovery path is therefore exact.** A network timeout during placement resolves by
retrying with the same reference: either the order is placed, or `GA007` says it already exists
and one lookup confirms its state. No order-book scan, no race, no duplicate. Every other
adapter approximates this; Groww simply has it.

ATOM generates `client_ref` ≤ 20 characters (Zerodha's `tag` ceiling), which also satisfies
Groww's 8–20 window as long as the generator's **minimum is 8** — a constraint that comes from
Groww alone and must be enforced in the shared generator, not in this adapter.

### 6.2 🔴 Holdings carry no `exchange`

`GET /v1/holdings/user` returns `isin` and `trading_symbol` but **no exchange field**, while
`atom.instrument` is keyed `UNIQUE (isin, exchange)`. An ISIN listed on both NSE and BSE cannot
be disambiguated from the holdings response alone.

**Resolution:** match on ISIN and, when more than one `atom.instrument` row matches, resolve
via `broker_instrument` on `trading_symbol` — which *is* exchange-specific in Groww's CSV. If
that still leaves an ambiguity, the account's run **blocks** rather than guessing: attributing a
holding to the wrong exchange row would put lots in the wrong instrument and corrupt the
attribution identity.

In practice ATOM's ETF universe is NSE-only, so this should never fire. It is specified because
"should never fire" is not the same as "cannot".

### 6.3 Pre-flight tradability — unique to Groww

The instrument CSV carries `buy_allowed`, `sell_allowed` and `is_reserved`. No other broker of
the five publishes per-instrument trading permission in its master.

```python
tradable = buy_allowed and not is_reserved
# sell_allowed is checked separately, at the sell pass
```

This lets ATOM **drop a candidate before placing an order that would be rejected**, which is
strictly better than D-052's "let it fail" for a condition that is knowable in advance. D-052 is
about *funds*, which genuinely cannot be known reliably ahead of the exchange; tradability can.

The flags are read at instrument-sync time and stored on `broker_instrument.tradable`. A
`sell_allowed = 0` on a held instrument is a **warning on the reconciliation row** — ATOM holds
something it cannot currently exit.

### 6.4 Decimal strings

Smart Orders take and return prices as **strings** (`"3985.00"`). Regular orders take JSON
numbers. The adapter's serialiser must differ per endpoint family — the same split-personality
problem Zerodha has with form vs JSON encoding (`ZERODHA-ADAPTER.md` §12.5), in a different
place.

### 6.5 GTT ownership

```python
is_ours = (reference_id is not None and reference_id in atom_known_refs)
```

Groww returns `reference_id` on the smart order, so `is_ours` is answerable **from broker data**
— unlike Zerodha, where only ATOM's database knows (D-176). The DB mapping is still maintained
as the primary source; Groww's field is a cross-check that would have caught an orphan.

---

## 7. Outbound mappings

### 7.1 `OrderIntent` → `POST /v1/order/create`

| Canonical | Groww field | Value |
|---|---|---|
| `instrument_id` → resolve | `trading_symbol` | from `broker_instrument.broker_token` |
| — | `exchange` | `NSE` |
| — | `segment` | `CASH` |
| `side` | `transaction_type` | `BUY` / `SELL` |
| `quantity` | `quantity` | integer |
| `limit_price` | `price` | number |
| `order_kind` | `order_type` | **always `LIMIT`** (D-174) |
| `product` | `product` | `CNC` |
| `validity` | `validity` | `DAY` — **the only value Groww documents** |
| `client_ref` | `order_reference_id` | **required**, 8–20 alphanumeric |

Not sent: `trigger_price` (SL orders only).

⚠️ **`DAY` is the only documented validity.** Groww's annexure lists no `IOC`. Harmless —
ATOM uses `DAY` everywhere (D-057) — but the adapter must not offer `IOC` as an option the
engine could pick.

### 7.2 `GttIntent` → `POST /v1/order-advance/create`

```json
{
  "reference_id": "atom-20260925-071",
  "smart_order_type": "GTT",
  "segment": "CASH",
  "exchange": "NSE",
  "trading_symbol": "GOLDBEES",
  "quantity": 100,
  "trigger_price": "72.50",
  "trigger_direction": "UP",
  "order": {"order_type": "LIMIT", "price": "72.45", "transaction_type": "SELL"},
  "product_type": "CNC",
  "duration": "DAY"
}
```

🟢 **`trigger_direction` is explicit.** ATOM's sell GTT always sets `UP` — the trigger is above
the strategy average. Every other broker infers direction from trigger price versus LTP, which
is one more thing that can be wrong; Groww simply asks.

⚠️ **`duration: "DAY"` refers to the order placed *after* the trigger fires**, not to the GTT's
own life. The GTT itself is forced to **one year** ("GTT orders placed via API automatically
default to a one-year validity period"). Reading `duration` as the GTT's validity would be a
serious misreading — it would suggest the GTT expires tonight when it survives a year.

### 7.3 Cancel

| | |
|---|---|
| Order | `POST /v1/order/cancel` with `{segment, groww_order_id}` |
| GTT | `POST /v1/order-advance/cancel/{segment}/{smart_order_type}/{smart_order_id}` |

Both are **POST**, not DELETE — unlike Zerodha. The GTT cancel puts all three identifiers in the
**path**.

---

## 8. Status map

### 8.1 Orders — twelve documented values

| Groww | → Canonical | Note |
|---|---|---|
| `EXECUTED` | `FILLED` | |
| `COMPLETED` | `FILLED` | ⚠️ see below |
| `DELIVERY_AWAITED` | `FILLED` | Executed, awaiting delivery — the trade happened |
| `REJECTED` | `REJECTED` | |
| `FAILED` | `REJECTED` | |
| `CANCELLED` | `CANCELLED` | |
| `APPROVED` | `PLACED` | Ready for execution |
| `ACKED` | `PLACED` | Acknowledged |
| `NEW` | `IN_FLIGHT` | |
| `TRIGGER_PENDING` | `IN_FLIGHT` | |
| `CANCELLATION_REQUESTED` | `IN_FLIGHT` | **Not yet cancelled** |
| `MODIFICATION_REQUESTED` | `IN_FLIGHT` | |
| **anything else** | **`IN_FLIGHT`** | D-180 default |

⚠️ **`EXECUTED` and `COMPLETED` both exist** and Groww's descriptions do not distinguish them
("successfully executed" vs "completed"). Both map to `FILLED`, and the fill quantities come
from `/order/trades` rather than from the status — so the ambiguity cannot affect ATOM's books.
Recorded because a reader will notice it and wonder. Q-292.

⚠️ **`CANCELLATION_REQUESTED` is not `CANCELLED`.** Mapping it to terminal would let the
cancel-all-first step believe the book is clean while an order is still live.

### 8.2 Smart Orders

| Groww | → Canonical |
|---|---|
| `ACTIVE` | `ACTIVE` |
| `COMPLETED` | `TRIGGERED` |
| `CANCELLED` | `CANCELLED` |
| anything else | `UNKNOWN` |

Groww documents only `ACTIVE` / `CANCELLED` / `COMPLETED` as `status` filter values; the round-1
research also saw `TRIGGERED`, `EXPIRED` and `FAILED` referenced. The default branch covers it.

---

## 9. Error map

| Groww | → Canonical | Engine behaviour |
|---|---|---|
| `GA000` Internal error | `TransientError` | Bounded retry |
| `GA001` Bad request | `ValidationError` | Bug — fail loudly, never retry |
| `GA003` Unable to serve request currently | `TransientError` | Backoff |
| `GA004` Entity does not exist | `ValidationError` | |
| `GA005` Not authorised | `AuthError` | Halt account |
| `GA006` Cannot process | `UnknownError` | Halt, preserve payload |
| **`GA007` Duplicate order reference id** | **`DuplicateRefError`** | 🟢 **Success, already placed** — look up by reference, never re-place |
| HTTP 401 / 403 | `AuthError` | |
| HTTP 429 | `RateLimitError` | Backoff with jitter |
| HTTP 5xx | `TransientError` | |

Groww's taxonomy is coarser than Zerodha's — there is no distinct margin or holdings error, so
an insufficient-funds rejection arrives as `GA001` or `GA006` with the reason in `message`. The
adapter keeps the verbatim `message` in `reject_reason` (D-042) and does **not** attempt to
parse it into a canonical subtype: string-matching a broker's prose is exactly the kind of
mapping that breaks silently when they reword it. Q-293.

---

## 10. Rate limits

| Type | /sec | /min |
|---|---|---|
| Authentication | 5 | 30 (+ **150/day** on `/v1/token/api/access`) |
| Orders (create, modify, cancel) | 10 | 250 |
| Live Data (quote, LTP, OHLC) | 10 | 300 |
| Non Trading (status, lists, trades, positions, holdings, margin) | 20 | 500 |

⚠️ **Limits apply per *type*, not per endpoint.** Exhausting one endpoint throttles every
endpoint in its group — so a holdings-polling loop can starve order-status checks, which share
the Non Trading bucket. ATOM's volume is far below all of these.

Groww's Live Data ceiling (10/s) is an order of magnitude better than Zerodha's and Dhan's
1/s — but D-044 stands regardless: market data comes from one provider for all accounts.

---

## 11. Postbacks

Not offered. Order updates are polled. ATOM's orders rest and are reconciled on the next run
(D-053), so this costs nothing.

---

## 12. Broker-specific hazards

### 12.1 ⚠️ `duration` is the triggered order's validity, not the GTT's

Covered in §7.2 and repeated here because it is the easiest mistake to make in this adapter: the
GTT lives **one year**, forced; `duration: "DAY"` governs the order that fires.

### 12.2 ⚠️ The smart-order list defaults to today and caps at one month

The cancel-all-first verification must pass an explicit window and paginate. A default call
reports a clean book while year-old GTTs are still live.

### 12.3 ⚠️ Holdings have no `exchange`

§6.2. Blocks rather than guesses when an ISIN is ambiguous.

### 12.4 ⚠️ `client_ref` minimum length is 8

Groww is the **only** broker with a *lower* bound. The shared generator must satisfy
`8 ≤ len ≤ 20`, alphanumeric, ≤2 hyphens — Groww's floor and Zerodha's ceiling together define
the canonical format.

### 12.5 ⚠️ Two serialisation styles

Regular orders take JSON numbers; smart orders take decimal **strings**. Same class of trap as
Zerodha's form-vs-JSON split.

### 12.6 ⚠️ Paid subscription is a hard prerequisite

Without an active Trading API subscription, nothing works. It belongs on the onboarding
checklist beside credentials, and its cost is an unquantified line in the running-cost model
(Q-275).

---

## 13. Open questions

| ID | Question | Blocks |
|---|---|---|
| Q-289 | Does Groww's holdings `quantity` ("net quantity") **include** `t1_quantity`, as Zerodha's does not? The attribution identity's `total_quantity` depends on the answer | Attribution correctness |
| Q-290 | Can `settlement_number` on trades give **observed** settlement dates for the SETTLEMENT capital bucket, rather than inferred T+1? | Cost-of-capital fidelity |
| Q-291 | Does Groww require any depository/EDIS-style sell authorisation? Not mentioned anywhere in the docs — absence is not confirmation | Sell pass |
| Q-292 | `EXECUTED` vs `COMPLETED` — what actually distinguishes them? | Nothing (both → `FILLED`); documentation clarity only |
| Q-293 | Which error code does an insufficient-funds rejection arrive as, and is the reason machine-readable in `metadata`? | Funds-failure handling |
| Q-274 | Static-IP whitelisting procedure — not in the developer docs | Live trading |
| Q-275 | Trading API subscription cost per account | Running-cost model |
| Q-279 | No ledger endpoint — how are deposits/withdrawals captured? | Cost of capital |

---

## 14. Sources

All fetched 2026-09-25:
[introduction](https://groww.in/trade-api/docs/curl) ·
[instruments](https://groww.in/trade-api/docs/curl/instruments) ·
[orders](https://groww.in/trade-api/docs/curl/orders) ·
[smart orders](https://groww.in/trade-api/docs/curl/smart-orders) ·
[portfolio](https://groww.in/trade-api/docs/curl/portfolio) ·
[margin](https://groww.in/trade-api/docs/curl/margin) ·
[annexures](https://groww.in/trade-api/docs/curl/annexures) ·
[instrument CSV](https://growwapi-assets.groww.in/instruments/instrument.csv)
