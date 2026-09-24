# Zerodha (Kite Connect v3) — Adapter Specification

**Status:** 🟢 Complete — every mapping below traced to a Kite Connect v3 page read 2026-09-24
**Order of work:** 1st of 5 (see [`../ADAPTER-ENGINE.md`](../ADAPTER-ENGINE.md) §9)
**Pages read:** introduction · user · orders · GTT · portfolio · margins · market quotes ·
postbacks · exceptions

> **Why Zerodha first.** It is the hardest of the five on identity and authorisation: an active
> GTT carries **no ATOM identifier at all**, and selling holdings needs a depository
> authorisation that is **valid for one trading session only**. Both force the engine to be
> right about durable state and about pre-flight gates. Everything else is easier than this.

---

## 1. Capability profile

```python
ZERODHA = BrokerCapabilities(
    broker_code               = "ZERODHA",

    supports_gtt              = True,
    gtt_max_validity_days     = None,          # broker returns expires_at; ~1 year observed
    gtt_carries_client_ref    = False,         # 🔴 see §12.1
    gtt_order_type            = "LIMIT",       # LIMIT only inside a GTT

    client_ref_field          = "tag",
    client_ref_max_len        = 20,            # alphanumeric
    client_ref_is_idempotent  = False,         # `guid` exists but is undocumented for our use
    lookup_by_client_ref      = False,         # must scan the order book

    provides_trade_charges    = True,          # POST /charges/orders  🟢
    provides_charge_preview   = True,          # same endpoint accepts imaginary orders 🟢
    provides_ledger           = False,         # console reports only
    provides_free_quantity    = True,          # derived, see §6.1

    requires_static_ip        = True,          # ❓ procedure undocumented (Q-274)
    static_ip_scope           = "ALL_CALLS",   # assumed strictest until confirmed
    static_ip_lock_days       = 0,             # unknown; assume none

    token_probe_endpoint      = "PROFILE",     # GET /user/profile
    token_revocable           = True,          # 🟢 DELETE /session/token

    requires_sell_authorisation  = True,
    sell_authorisation_scope     = "PER_SESSION",   # 🔴 daily, not one-time — see §12.2

    orders_per_second         = 10,
    quote_batch_size          = 500,           # /quote; 1000 for /quote/ltp and /quote/ohlc
)
```

---

## 2. Wire basics

| | |
|---|---|
| Base URL | `https://api.kite.trade` |
| Version header | `X-Kite-Version: 3` — **required on every call** |
| Auth header | `Authorization: token <api_key>:<access_token>` |
| Request encoding | **form-encoded** for orders/GTT; **`application/json`** for `/margins/*` and `/charges/*` |
| Response | JSON, may be gzipped |
| Envelope | `{"status": "success", "data": …}` or `{"status":"error","message":…,"error_type":…}` |
| Not CORS-enabled | Server-side only — fine, ATOM is server-side |

**Two encodings in one API.** The order endpoints are form-encoded; the margin and charge
endpoints are JSON and reject form encoding. The adapter must carry both serialisers, and the
round-trip tests must cover both — this is the kind of detail that costs an afternoon if
discovered at runtime.

---

## 3. Session lifecycle

### 3.1 Login

```
1.  GET  https://kite.zerodha.com/connect/login?v=3&api_key=<key>
         &redirect_params=<urlencoded>          ← ATOM carries trading_account_id here
2.  →    redirect to registered URL with ?request_token=<token>     (lifetime: minutes)
3.  POST https://api.kite.trade/session/token
         api_key, request_token,
         checksum = SHA256(api_key + request_token + api_secret)
4.  →    access_token
```

Account prerequisite: **2FA TOTP must be enabled** on the Zerodha account.

`redirect_params` is a URL-encoded query string echoed back at the redirect. ATOM puts
`trading_account_id` in it, so the console knows which account a returning token belongs to
without holding server-side state across the redirect.

### 3.2 Expiry — a hard 6 AM boundary

> "…it'll expire at **6 AM on the next day (regulatory requirement)**."

`refresh_token` is returned but is "only available to certain approved platforms" — **not
available to ATOM**. There is no refresh path; it is a fresh login every day.

ATOM generates tokens after 06:00 IST and runs before market close, so the boundary is never
crossed in practice. Recorded as a constraint rather than a risk.

### 3.3 Probe — `GET /user/profile`

Returns `user_id`, `exchanges[]`, `products[]`, `order_types[]`, `meta.demat_consent`. Notably it
does **not** return any token, which makes it safe to log the whole response.

`meta.demat_consent` ∈ `""` / `"consent"` / `"physical"` is captured at probe time — it is the
Zerodha equivalent of Dhan's `givenPowerOfAttorney` and feeds §12.2.

### 3.4 Revoke — `DELETE /session/token?api_key=&access_token=`

Zerodha is **the only one of the five** that lets ATOM actively destroy the token. D-170's
end-of-run `CLEARED` step calls it here, rather than merely deleting the SSM parameter.

| Canonical | Zerodha |
|---|---|
| `build_auth_url` | `https://kite.zerodha.com/connect/login?v=3&api_key=…&redirect_params=…` |
| `exchange_code` | `POST /session/token` with the SHA-256 checksum |
| `probe_token` | `GET /user/profile` |
| `revoke_token` | `DELETE /session/token` |

---

## 4. Instrument master

`GET /instruments` → **gzipped CSV**, all exchanges. `GET /instruments/NSE` for one exchange.

```
instrument_token, exchange_token, tradingsymbol, name, last_price,
expiry, strike, tick_size, lot_size, instrument_type, segment, exchange
408065,1594,INFY,INFOSYS,0,,,0.05,1,EQ,NSE,NSE
```

| CSV column | → `CanonicalInstrument` | → DB |
|---|---|---|
| `instrument_token` | `broker_token` | `broker_instrument.broker_token` |
| `tradingsymbol` | `symbol`, `broker_symbol` | `instrument.symbol`, `broker_instrument.broker_symbol` |
| `name` | `name` | `instrument.name` |
| `exchange` | `exchange` | `instrument.exchange` |
| `tick_size` | `tick_size` | `instrument.tick_size` |
| `lot_size` | `lot_size` | `instrument.lot_size` |
| `instrument_type` | `instrument_type` | — (classification is ATOM's, D-091) |
| — | `isin` = **`None`** | — |

### 🔴 4.1 The instruments dump has no ISIN column

This is the single biggest inbound problem on Zerodha, and it is specific to this broker.

ATOM's resolution rule is *match on ISIN, never on symbol* (`ADAPTER-ENGINE.md` §5) — and
Zerodha's instrument master cannot satisfy it. The ISIN **is** available from
`GET /portfolio/holdings`, but only for instruments the investor already holds, which by
definition excludes everything ATOM is about to buy for the first time.

**Resolution strategy, in order:**

1. **Seed from ATOM's own reference data.** `data/reference/etf-reference-data-*.csv` already
   resolves 311/311 ETF ISINs from NSE, AMFI and broker sources. Zerodha rows are matched on
   `(tradingsymbol, exchange)` **against that curated set**, not against a free-text symbol space.
2. **Confirm from holdings** whenever the instrument appears there — `portfolio/holdings`
   carries both `isin` and `tradingsymbol`, so every holding silently validates the mapping. A
   mismatch between the seeded ISIN and the holdings ISIN **blocks the account's run**: it means
   ATOM would trade the wrong security.
3. **Anything unmatched goes to `REVIEW`.** Never auto-match on symbol alone.

The symbol-based match is acceptable *only* because it runs against a closed, curated universe of
a few hundred ETFs whose symbols ATOM already knows — not against the ~80,000-row full dump.
That distinction is what keeps rule 1 of §5 intact rather than quietly broken.

### 4.2 Token reuse

> "Exchanges may reuse instrument tokens for different derivative instruments after each expiry."

ATOM stores tokens but never keys on them, and re-resolves daily at ~08:30 IST (Zerodha's own
recommendation, since the dump regenerates once a day). A changed token for an existing ISIN
updates the row **and logs it** — a silent change would route the next order to a different
security.

---

## 5. Inbound mappings

### 5.1 Holdings — `GET /portfolio/holdings`

| Zerodha field | → Canonical | Note |
|---|---|---|
| `isin` | *(join key)* | 🟢 present here, unlike the instruments dump |
| `instrument_token` | *(join key)* | |
| `quantity` | *(input to §6.1)* | **"Realised Quantity (T+2)"** — *not* the total |
| `t1_quantity` | `unsettled_quantity` | Bought, not yet in demat |
| `realised_quantity` | *(input)* | "Quantity delivered to Demat" |
| `used_quantity` | *(input)* | **"Quantity sold from the net holding quantity"** |
| `authorised_quantity` | *(input)* | Authorised at the depository for sale |
| `opening_quantity` | *(input)* | Carried forward overnight |
| `collateral_quantity` | `pledged_quantity` | |
| `short_quantity` | *(input)* | |
| `average_price` | `average_price` | |
| `last_price` | `last_price` | |
| `discrepancy` | `broker_flags["discrepancy"]` | 🟢 see §6.2 |
| `authorisation` / `authorised_date` | `broker_flags[…]` | Feeds §12.2 |
| `product` | — | Always `CNC` for ATOM |
| `pnl`, `day_change*`, `close_price`, `mtf` | — | **Deliberately dropped**, see below |

**P&L from the broker is not ingested.** Zerodha's `pnl` is computed against its own average
cost across the whole holding. ATOM computes P&L per lot, per universe, from its own fills
(D-156, D-166). Storing the broker's number alongside would create two answers to one question
and invite the wrong one into a report. The single exception is reconciliation display, where it
may be *shown* beside ATOM's figure but never persisted as fact.

### 5.2 Orders — `GET /orders`

| Zerodha | → `OrderState` |
|---|---|
| `order_id` | `broker_order_id` |
| `tag` | `client_ref` |
| `status` | `status` (via §8) |
| `raw` `status` | `raw_status` |
| `filled_quantity` | `filled_quantity` |
| `pending_quantity` | `pending_quantity` |
| `average_price` | `average_price` |
| `status_message` \|\| `status_message_raw` | `reject_reason` |

`tags[]` (plural) also exists and may carry Zerodha-added entries; ATOM reads the singular `tag`
and ignores the array.

### 5.3 Fills — `GET /trades`

| Zerodha | → `CanonicalFill` | → DB |
|---|---|---|
| `trade_id` | `broker_trade_id` | `order_fill.broker_trade_id` |
| `order_id` | `broker_order_id` | → `order_request` |
| `quantity` | `quantity` | `order_fill.quantity` |
| `average_price` | `fill_price` | `order_fill.fill_price` |
| `fill_timestamp` | `filled_at` | `order_fill.filled_at` |

Zerodha returns **one row per fill**, which is exactly the grain D-166 needs — one
`position_lot` per `order_fill`, no aggregation.

⚠️ The response attribute table documents a field named `filled`, while the sample payload shows
`quantity`. The adapter reads `quantity` (the payload) and falls back to `filled`. Logged as
Q-278.

### 5.4 Quotes — `GET /quote/ltp?i=NSE:INFY`

Keyed by `exchange:tradingsymbol`, **not** by instrument token. Batch limits: 500 for `/quote`,
1000 for `/quote/ltp` and `/quote/ohlc`.

> "If there is no data available for a given key, **the key will be absent** from the response."

The adapter must check for presence rather than index blindly — a missing key means no data, not
a zero price. A zero price silently entering the deviation calculation would produce a −100%
deviation and a maximum-size buy signal. **The adapter raises on a missing key; it never
defaults.**

### 5.5 Charges — `POST /charges/orders` 🟢

The round-2 summary listed Zerodha's per-trade charges as unverified. **They are available**, via
the "virtual contract note".

```json
[{"order_id":"111111111","exchange":"NSE","tradingsymbol":"SBIN",
  "transaction_type":"BUY","variety":"regular","product":"CNC",
  "order_type":"MARKET","quantity":1,"average_price":560}]
```

| Zerodha `charges.*` | → `CanonicalCharges` | → `charge.charge_type` |
|---|---|---|
| `brokerage` | `brokerage` | `BROKERAGE` |
| `transaction_tax` (`transaction_tax_type: "stt"`) | `stt` | `STT` |
| `exchange_turnover_charge` | `exchange` | `EXCHANGE` |
| `sebi_turnover_charge` | `sebi` | `SEBI` |
| `stamp_duty` | `stamp` | `STAMP` |
| `gst.igst + gst.cgst + gst.sgst` | `gst` | `GST` |

`transaction_tax_type` is `stt` for equity and `ctt` for commodity futures — ATOM trades
NSE-listed ETFs, so it is always `stt`. The adapter asserts this rather than assuming it.

**🟢 The same endpoint prices imaginary orders.** Zerodha states `order_id` "can be any random
string to calculate charges for an imaginary order". That gives ATOM three things it did not
have:

1. **Real charge figures in dry-run mode** — from the broker's own calculator, not ATOM's model
   (this is what D-045's dry-run charge requirement asked for).
2. **Pre-trade estimates**, so the execution list can show expected charges before the operator
   releases it.
3. **A genuine estimated-vs-actual contrast on Zerodha**, not just on Dhan (D-179) — call it
   before with the intended price, and after with the achieved `average_price`. Both rows land in
   `atom.charge` with `source` `COMPUTED` and `BROKER` respectively.

`POST /margins/orders` returns the same `charges` block alongside margin requirements, so a
single pre-flight call can answer "is there enough money" and "what will this cost".

### 5.6 Ledger — not available

No ledger endpoint exists in Kite Connect v3. `GET /user/margins` gives a point-in-time snapshot
(`available.opening_balance`, `available.live_balance`, `utilised.payout`, `utilised.delivery`)
but no transaction history.

**Consequence:** `provides_ledger = False`. On Zerodha, `atom.cash_ledger` is populated from
ATOM's own fills and from manually uploaded statements, and Dhan's `runbal` reconciliation
anchor (D-179) has no Zerodha equivalent. `utilised.payout` — "funds paid out or withdrawn to
bank account during the day" — is the one signal that a withdrawal happened, and it is a daily
total, not an event list. Q-279.

---

## 6. Stage-3 normalisation — the Zerodha-specific computation

### 6.1 `free_quantity`

Zerodha exposes **eight** quantity fields and no single "sellable" number. The names are also
counter-intuitive: `quantity` is documented as "Realised Quantity(T+2)", not the gross holding.

```python
total_quantity = quantity + t1_quantity          # everything owned
free_quantity  = max(0, quantity
                        - used_quantity          # already sold today
                        - collateral_quantity    # pledged
                        - short_quantity)
```

`t1_quantity` is deliberately **excluded** from `free_quantity` — it is owned but not yet
deliverable — while being **included** in `total_quantity`, which is what the attribution
identity reconciles against (`HOLDINGS-ATTRIBUTION.md` §1a).

`authorised_quantity` is *not* subtracted. It is an authorisation ceiling, not an encumbrance,
and it is handled as a separate gate in §12.2.

### 6.2 `discrepancy` — a free health signal

Zerodha publishes a boolean `discrepancy` flag: "Indicates whether holding has any price
discrepancy."

ATOM treats a `true` as a **warning on that instrument's reconciliation row**, surfaced beside
the `unattributed_quantity` residual. It does not block the run — it is the broker's flag about
its own pricing, not about quantity — but it is exactly the kind of signal that explains an
anomalous average cost, and dropping it would mean investigating from scratch later.

### 6.3 GTT ownership

```python
is_ours = broker_gtt_id in atom_known_trigger_ids   # DB lookup, nothing else
```

There is no broker-side alternative. See §12.1.

### 6.4 GST collapse

Zerodha splits GST three ways (`igst`, `cgst`, `sgst`) by the investor's state relative to the
broker's. ATOM's `charge` table has one `GST` type, so the three are summed. The split is
preserved in the raw payload archive for anyone who later needs it.

---

## 7. Outbound mappings

### 7.1 `OrderIntent` → `POST /orders/regular`

⚠️ **`variety` is a URL path segment, not a body field.** ATOM always uses `regular`.

| Canonical | Zerodha param | Value |
|---|---|---|
| — | *(path)* | `regular` |
| `instrument_id` → resolve | `tradingsymbol` + `exchange` | from `broker_instrument` |
| `side` | `transaction_type` | `BUY` / `SELL` |
| `quantity` | `quantity` | |
| `limit_price` | `price` | |
| `order_kind` | `order_type` | **always `LIMIT`** (D-174) |
| `product` | `product` | `CNC` |
| `validity` | `validity` | `DAY` |
| `client_ref` | `tag` | **≤ 20 alphanumeric** |

Not sent: `trigger_price`, `disclosed_quantity`, `market_protection`, `autoslice`,
`iceberg_*`, `validity_ttl`.

**`autoslice` is never set.** With `autoslice=true` the response `data` becomes an *array* of
per-slice results mixing `order_id` and `error` objects. Since ATOM never sets it, the adapter
treats an array response to a single order as a fault rather than trying to interpret it.

### 7.2 `GttIntent` → `POST /gtt/triggers`

```
type      = single
condition = {"exchange":"NSE","tradingsymbol":"GOLDBEES",
             "trigger_values":[72.50],"last_price":71.80}
orders    = [{"exchange":"NSE","tradingsymbol":"GOLDBEES",
              "transaction_type":"SELL","quantity":100,
              "order_type":"LIMIT","product":"CNC","price":72.45}]
```

Both `condition` and `orders` are **JSON strings inside a form-encoded body** — a JSON document
passed as a form value. A serialiser that form-encodes the nested structure instead of embedding
JSON will be silently rejected.

**`last_price` is mandatory at placement.** ATOM must hold a live quote before it can place a
GTT, which means `fetch_quotes` is a hard dependency of the sell pass on Zerodha — unlike the
other brokers, where it is optional. Sequence: quote → GTT, in that order, per instrument.

**No `tag` field exists on a GTT.** See §12.1.

### 7.3 Cancel

| | |
|---|---|
| Order | `DELETE /orders/regular/{order_id}` |
| GTT | `DELETE /gtt/triggers/{trigger_id}` |

Both return `{"status":"success","data":{"order_id"\|"trigger_id": …}}`.

---

## 8. Status map

### 8.1 Orders

| Zerodha | → Canonical |
|---|---|
| `COMPLETE` | `FILLED` |
| `REJECTED` | `REJECTED` |
| `CANCELLED` | `CANCELLED` |
| `OPEN` | `PLACED` (`PARTIAL` if `filled_quantity > 0`) |
| `PUT ORDER REQ RECEIVED` | `IN_FLIGHT` |
| `VALIDATION PENDING` | `IN_FLIGHT` |
| `OPEN PENDING` | `IN_FLIGHT` |
| `MODIFY VALIDATION PENDING` | `IN_FLIGHT` |
| `MODIFY PENDING` | `IN_FLIGHT` |
| `MODIFIED` | `IN_FLIGHT` |
| `TRIGGER PENDING` | `IN_FLIGHT` |
| `CANCEL PENDING` | `IN_FLIGHT` |
| `AMO REQ RECEIVED` | `IN_FLIGHT` |
| **anything else** | **`IN_FLIGHT`** |

> Zerodha's own words: "There may be other values as well." The default branch is mandatory
> (D-180), and the test suite asserts it with an invented status string.

### 8.2 GTT

| Zerodha | → Canonical |
|---|---|
| `active` | `ACTIVE` |
| `triggered` | `TRIGGERED` |
| `cancelled`, `deleted` | `CANCELLED` |
| `expired` | `EXPIRED` |
| `rejected` | `REJECTED` |
| `disabled` | `UNKNOWN` — **needs operator attention**, Zerodha says "action is expected from the user" |
| anything else | `UNKNOWN` |

`GET /gtt/triggers` returns active triggers **plus the previous 7 days** of other states, so the
cancel-all-first verification must filter on `status == active` rather than assuming the list is
live-only.

---

## 9. Error map

Zerodha returns a named `error_type` on every error — the cleanest taxonomy of the five, and it
maps almost one-to-one.

| Zerodha | HTTP | → Canonical |
|---|---|---|
| `TokenException` | 403 | `AuthError` — clear session, halt account, re-login |
| `MarginException` | 400 | `InsufficientFundsError` — record reason, continue (D-052) |
| `HoldingException` | 400 | `InsufficientHoldingsError` — halt, reconcile |
| *(no name)* | **428** | **`AuthorisationRequiredError`** — see §12.2 |
| `InputException` | 400 | `ValidationError` — bug, fail loudly |
| `OrderException` | 400/500 | `UnknownError` — halt account, preserve payload |
| `UserException` | 4xx | `AuthError` |
| `NetworkException` | 502 | `TransientError` |
| `DataException` | 500 | `TransientError` |
| `GeneralException` | 500 | `UnknownError` |
| — | 429 | `RateLimitError` |
| — | 503 / 504 | `TransientError` |

`OrderException` covers "placement failures, a corrupt fetch etc." — too broad to retry safely,
so it halts rather than retries.

---

## 10. Rate limits

| Endpoint | Limit |
|---|---|
| **`/quote`** | **1 req/sec** |
| Historical candles | 3 req/sec |
| Order placement | 10 req/sec |
| All others | 10 req/sec |
| Orders/minute | 400 |
| Orders/day | 5,000 |
| Modifications per order | 25 |

**Zerodha's `/quote` is 1 req/sec — the same ceiling as Dhan.** Two of five brokers cap quotes at
one per second, which is the decisive argument for D-044's single-data-source design. Note the
batch sizes partly offset this: `/quote/ltp` takes **1000 instruments in one call**, so a 60-ETF
universe is one request, not sixty. The adapter always batches; it never loops per instrument.

---

## 11. Postbacks — deferred

`POST` to a registered `postback_url` on `COMPLETE` / `CANCEL` / `REJECTED` / `UPDATE`, carrying
`checksum = SHA256(order_id + order_timestamp + api_secret)`.

**Not used in v1.** ATOM's orders rest and are reconciled on the next run (D-053), and a
postback receiver means a public HTTPS endpoint — new attack surface for no gain at one run a
day. Recorded because it is the right answer if ATOM ever moves to intraday runs. If adopted,
**the checksum must be verified**: the endpoint is public and anyone can POST to it.

---

## 12. Broker-specific hazards

### 12.1 🔴 An active GTT carries no ATOM identifier

Regular orders have `tag`. **GTTs do not.** An active trigger returns `"meta": {}` or `null`; the
`app_id` appears only inside `orders[].result.meta` *after* the trigger fires.

Consequences, all of which are engine behaviour rather than documentation:

- `gtt_carries_client_ref = False` in the capability profile.
- `is_ours` is decided **solely** by ATOM's `broker_gtt_id` table.
- The `broker_gtt_id` is persisted **before `place_gtt` returns** (D-176). A crash between the
  broker accepting the GTT and ATOM recording it leaves an orphan that ATOM can never
  identify — and therefore, under D-064, can never cancel.
- The cancel-all-first step cancels **only** known IDs. An unknown GTT is the investor's until
  proven otherwise.
- **Recovery for an orphan requires a human.** There is no API path. The console must expose the
  broker's GTT list beside ATOM's known IDs so the operator can spot and manually clear a
  divergence.

### 12.2 🔴 Sell authorisation is **per trading session**, not one-time

This is the finding that most changes ATOM's daily run, and it is not what the Upstox EDIS
analogy suggested.

> "…a broker either requires a **PoA** or an electronic authorisation at the depository from the
> user… The authorisations are valid for **a single trading session in a day** (beginning of the
> day till 5:30 PM)."

The documented sequence:

1. Investor holds 50 INFY. No authorisation.
2. `POST /orders` to sell 10 → **HTTP 428**, "10 quantity needs authorisation at depository."
3. ATOM calls `POST /portfolio/holdings/authorise` with `isin`/`quantity` pairs → `request_id`.
4. Operator is sent to
   `https://kite.zerodha.com/connect/portfolio/authorise/holdings/:api_key/:request_id`,
   enters their **demat PIN** (known only to them and CDSL — never to ATOM or to Zerodha).
5. Completion redirects to `…/finish?status=success`.
6. Retry the sell. The remaining authorised quantity covers the rest of the day.

**What this means for ATOM:**

- `sell_authorisation_scope = "PER_SESSION"`. Unless the investor has **DDPI/PoA** — which
  `meta.demat_consent` from `/user/profile` reports — this is a **daily operator action**, in the
  same category as generating the token, not a one-time onboarding step.
- The sell pass has a **pre-flight**: authorise **all** holdings ATOM might sell, once, before
  the first sell order, rather than discovering a 428 mid-pass. Zerodha does this by default in
  its own UI "to avoid having to disrupt the sell transactions with the authorisation flow every
  time", and ATOM should do the same — call `authorise` with no isin/quantity pairs, which
  presents the entire holding.
- A 428 mid-pass is **not** an error to log and move past. It halts the sell pass, raises
  `AuthorisationRequiredError` carrying the authorisation URL, and waits for the operator.
- **The console needs an "Authorise holdings" action beside "Generate token"** for any Zerodha
  account without DDPI. Adding it to the token screen is the natural place, since both are daily
  and both are operator-in-the-loop.

**Open question Q-280:** does the investor's Zerodha account have DDPI active? If yes, this
entire flow disappears. It is the single cheapest thing that could be done to simplify ATOM's
Zerodha sell path, and it is worth checking before building the authorisation UI.

### 12.3 ⚠️ `quantity` does not mean total quantity

`quantity` is documented as "Realised Quantity(T+2)". A reader who assumes it is the gross
holding will under-count by `t1_quantity` and mis-report the attribution residual as negative —
which, under `HOLDINGS-ATTRIBUTION.md`, **blocks the run**. §6.1 is the authority.

### 12.4 ⚠️ `last_price` is required to place a GTT

Unique to Zerodha among the five. It makes `fetch_quotes` a hard dependency of the sell pass and
adds an ordering constraint: quote first, then place.

### 12.5 ⚠️ Two encodings

Form-encoded for orders and GTT; `application/json` for `/margins/*` and `/charges/*`. Mixing
them up produces confusing 400s from `InputException`.

### 12.6 ⚠️ Missing quote keys are absent, not zero

`/quote/ltp` omits the key entirely when there is no data. Defaulting to zero would feed a −100%
deviation into the strategy and produce a maximum-size buy. The adapter raises.

---

## 13. Open questions

| ID | Question | Blocks |
|---|---|---|
| **Q-274** | Zerodha's static-IP whitelisting procedure is not in the developer docs. Where is it registered, and does it gate all calls or orders only? | Live trading |
| **Q-280** 🔴 | Is **DDPI/PoA** active on the investor's Zerodha account? If not, holdings authorisation is a **daily** operator step (§12.2) | Sell pass design |
| Q-278 | `/trades` documents a `filled` attribute but the sample payload shows `quantity`. Confirm against a live response | Fill ingestion |
| Q-279 | With no ledger endpoint, how are Zerodha deposits/withdrawals captured — manual statement upload, or `utilised.payout` deltas? | Cost of capital |
| Q-281 | Does a Zerodha GTT survive its underlying holding being sold by other means, or is it auto-`disabled`? (broker-specific instance of Q-186) | GTT hygiene |

---

## 14. Sources

All fetched 2026-09-24 from Kite Connect v3:
[introduction](https://kite.trade/docs/connect/v3/) ·
[user](https://kite.trade/docs/connect/v3/user/) ·
[orders](https://kite.trade/docs/connect/v3/orders/) ·
[GTT](https://kite.trade/docs/connect/v3/gtt/) ·
[portfolio](https://kite.trade/docs/connect/v3/portfolio/) ·
[margins & charges](https://kite.trade/docs/connect/v3/margins/) ·
[market quotes & instruments](https://kite.trade/docs/connect/v3/market-quotes/) ·
[postbacks](https://kite.trade/docs/connect/v3/postbacks/) ·
[exceptions](https://kite.trade/docs/connect/v3/exceptions/)
